"""B044 — _startup_encryption must fail CLOSED when encryption was requested.

Before the fix, the outer except only re-raised RuntimeError; any other
exception (e.g. an exotic ImportError/OSError/ValueError while building the
CryptoProvider on a fresh install) was swallowed and crypto_provider set to
None → the server booted in PLAINTEXT when the user had asked for encryption,
writing PII to disk unencrypted. Only crypto-disabled boots may swallow init
errors.
"""
import asyncio
from types import SimpleNamespace

import pytest

import core.lifespan_crypto as lc


def _server_state(tmp_path):
    return SimpleNamespace(
        config={'security': {'encryption': {'warn_unencrypted': False}}},
        crypto_provider="sentinel",
        project_root=tmp_path,
    )


def test_startup_encryption_fails_closed_when_requested(monkeypatch, tmp_path):
    """Encryption requested (crypto_enabled=True) + non-RuntimeError init error
    → re-raise (fail-closed), NOT crypto_provider=None / plaintext boot."""
    monkeypatch.setattr(lc, "_check_sqlcipher_required", lambda *a, **k: None)
    monkeypatch.setattr(lc, "_resolve_encryption_enabled", lambda *a, **k: True)
    monkeypatch.setattr(lc, "_check_plaintext_db_exists", lambda ss, enabled, env: enabled)

    import core.crypto as cc

    class _BoomProvider:
        def __init__(self):
            raise ValueError("exotic CryptoProvider init failure")

    monkeypatch.setattr(cc, "CryptoProvider", _BoomProvider)

    server_state = _server_state(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(lc._startup_encryption(server_state))


def test_startup_encryption_swallows_when_disabled(monkeypatch, tmp_path):
    """Encryption NOT requested → a non-RuntimeError init error is still
    swallowed (crypto_provider=None). Only requested-crypto fails closed."""
    monkeypatch.setattr(lc, "_check_sqlcipher_required", lambda *a, **k: None)
    monkeypatch.setattr(lc, "_resolve_encryption_enabled", lambda *a, **k: False)
    monkeypatch.setattr(lc, "_check_plaintext_db_exists", lambda ss, enabled, env: enabled)

    def _boom(*a, **k):
        raise ValueError("boom after crypto_enabled computed")

    monkeypatch.setattr(lc, "_apply_crypto_provider", _boom)

    server_state = _server_state(tmp_path)
    asyncio.run(lc._startup_encryption(server_state))  # must NOT raise
    assert server_state.crypto_provider is None
