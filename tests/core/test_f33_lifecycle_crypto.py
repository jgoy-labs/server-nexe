"""
F3.3 lifecycle + crypto hardening regression tests.

Covers:
- BUG-NC-37: master key fail-fast when file persistence fails on a newly-generated key
- BUG-C5: `STARTUP_TIMEOUT` respects new `NEXE_LIFESPAN_TIMEOUT` alias + default raised
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestMasterKeyFailFast:
    """BUG-NC-37 — refuse to return a newly-generated key that wasn't persisted."""

    def test_get_or_create_raises_when_file_set_fails(self, tmp_path):
        from core.crypto import keys as crypto_keys

        key_file = tmp_path / "master.key"

        # All sources empty + file write fails → must raise RuntimeError, not
        # return an ephemeral key.
        with patch.object(crypto_keys, "_try_file_get", return_value=None), \
             patch.object(crypto_keys, "_try_keyring_get", return_value=None), \
             patch.object(crypto_keys, "_try_env_get", return_value=None), \
             patch.object(crypto_keys, "_try_file_set", return_value=False), \
             patch.object(crypto_keys, "_try_keyring_set", return_value=False):
            with pytest.raises(RuntimeError) as exc:
                crypto_keys.get_or_create_master_key(key_file)
            assert "Failed to persist" in str(exc.value)
            assert "unrecoverable" in str(exc.value).lower()

    def test_get_or_create_succeeds_when_file_set_works(self, tmp_path):
        from core.crypto import keys as crypto_keys

        key_file = tmp_path / "master.key"
        with patch.object(crypto_keys, "_try_file_get", return_value=None), \
             patch.object(crypto_keys, "_try_keyring_get", return_value=None), \
             patch.object(crypto_keys, "_try_env_get", return_value=None), \
             patch.object(crypto_keys, "_try_file_set", return_value=True), \
             patch.object(crypto_keys, "_try_keyring_set", return_value=True):
            key = crypto_keys.get_or_create_master_key(key_file)
            assert isinstance(key, bytes)
            assert len(key) == crypto_keys.KEY_SIZE

    def test_existing_file_does_not_trigger_fail_fast(self, tmp_path):
        """Read paths (file already exists) must NOT fail when file_set isn't called."""
        from core.crypto import keys as crypto_keys

        key_file = tmp_path / "master.key"
        existing = b"\xff" * crypto_keys.KEY_SIZE
        with patch.object(crypto_keys, "_try_file_get", return_value=existing), \
             patch.object(crypto_keys, "_try_keyring_get", return_value=None), \
             patch.object(crypto_keys, "_try_keyring_set", return_value=False):
            key = crypto_keys.get_or_create_master_key(key_file)
            assert key == existing


class TestLifespanTimeoutConfig:
    """BUG-C5 — `NEXE_LIFESPAN_TIMEOUT` overrides legacy alias and default is 120.

    Tests target the pure `_resolve_startup_timeout()` resolver (avoids
    `importlib.reload`, which contaminates global state for other tests).
    """

    def test_new_alias_wins_when_set(self, monkeypatch):
        from core.lifespan import _resolve_startup_timeout
        monkeypatch.setenv("NEXE_LIFESPAN_TIMEOUT", "45")
        monkeypatch.setenv("NEXE_STARTUP_TIMEOUT", "999")
        assert _resolve_startup_timeout() == 45.0

    def test_legacy_alias_still_honoured(self, monkeypatch):
        from core.lifespan import _resolve_startup_timeout
        monkeypatch.delenv("NEXE_LIFESPAN_TIMEOUT", raising=False)
        monkeypatch.setenv("NEXE_STARTUP_TIMEOUT", "75")
        assert _resolve_startup_timeout() == 75.0

    def test_default_is_120s_when_neither_set(self, monkeypatch):
        from core.lifespan import _resolve_startup_timeout
        monkeypatch.delenv("NEXE_LIFESPAN_TIMEOUT", raising=False)
        monkeypatch.delenv("NEXE_STARTUP_TIMEOUT", raising=False)
        assert _resolve_startup_timeout() == 120.0
