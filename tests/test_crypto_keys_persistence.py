"""
Tests for core/crypto/keys.py — Fix bug #19b pre-release (persistent MEK).

Objective: guarantee that the Master Encryption Key (MEK) is never regenerated while
at least ONE persistent source exists, and that it is always replicated to
BOTH sources (file + keyring) to survive a Keychain reset.

Critical scenario: autonomous robot restarts. If the Keychain is wiped (OS reset,
upgrade), the server must read from `~/.nexe/master.key`, not generate
a new key that would invalidate all previously encrypted sessions.

Strategy:
- `tmp_path` to isolate the real key file.
- Monkeypatch of `_try_keyring_get`/`_try_keyring_set` wrappers to simulate
  Keychain state without touching the real Keychain.
"""

import pytest

from core.crypto import keys as crypto_keys


@pytest.fixture
def fake_keyring(monkeypatch):
    """In-memory Keychain for tests."""
    store = {"value": None}

    def _get():
        return store["value"]

    def _set(key):
        store["value"] = key
        return True

    monkeypatch.setattr(crypto_keys, "_try_keyring_get", _get)
    monkeypatch.setattr(crypto_keys, "_try_keyring_set", _set)
    return store


@pytest.fixture
def fake_keyring_broken(monkeypatch):
    """Keyring that always fails (e.g. headless Linux without secretservice)."""
    monkeypatch.setattr(crypto_keys, "_try_keyring_get", lambda: None)
    monkeypatch.setattr(crypto_keys, "_try_keyring_set", lambda key: False)


@pytest.fixture(autouse=True)
def no_env_mek(monkeypatch):
    """Ensure NEXE_MASTER_KEY does not contaminate tests."""
    monkeypatch.delenv(crypto_keys.ENV_VAR_NAME, raising=False)


def test_file_written_even_when_keychain_succeeds(tmp_path, fake_keyring):
    """BUG #19b: when generating a new MEK, the file must exist IN ANY CASE.

    Current state (buggy): `if not _try_keyring_set(key): _try_file_set(...)`
    → if keyring succeeds, the file is NOT created. This leaves the server
    dependent on a single source (Keychain) that can be invalidated.
    """
    key_path = tmp_path / "master.key"
    assert not key_path.exists()
    assert fake_keyring["value"] is None

    key = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert len(key) == crypto_keys.KEY_SIZE
    assert key_path.exists(), "File backup NOT written despite Keychain OK — total loss risk"
    assert key_path.read_bytes() == key
    assert fake_keyring["value"] == key, "Keychain must also hold the key"


def test_file_read_first_before_keychain(tmp_path, fake_keyring):
    """The file is the primary source. If a file with a valid key exists,
    it is read from there without consulting the keyring (which might hold a different,
    old or incompatible key)."""
    key_path = tmp_path / "master.key"
    file_key = b"\x11" * crypto_keys.KEY_SIZE
    keyring_key = b"\x22" * crypto_keys.KEY_SIZE

    crypto_keys._try_file_set(file_key, path=key_path)
    fake_keyring["value"] = keyring_key

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == file_key, "Read file first: it is the permanent source of truth"


def test_no_regeneration_when_file_exists(tmp_path, fake_keyring):
    """With file present and empty keyring, do NOT generate a new key."""
    key_path = tmp_path / "master.key"
    original_key = b"\x33" * crypto_keys.KEY_SIZE
    crypto_keys._try_file_set(original_key, path=key_path)
    assert fake_keyring["value"] is None

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == original_key, "Never regenerate if the file exists"


def test_keychain_synced_to_file_on_read(tmp_path, fake_keyring):
    """If only the keychain exists (no file), reading it must sync to the file.

    Real case: user comes from a previous version that only saved to the Keychain.
    On first startup with the new code, replicate to file to survive
    future Keychain resets.
    """
    key_path = tmp_path / "master.key"
    keyring_key = b"\x44" * crypto_keys.KEY_SIZE
    fake_keyring["value"] = keyring_key
    assert not key_path.exists()

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == keyring_key
    assert key_path.exists(), "File was not synced from the keyring"
    assert key_path.read_bytes() == keyring_key


def test_restart_roundtrip_same_mek_despite_keychain_reset(tmp_path, fake_keyring):
    """Autonomous robot scenario: first start (generates key). Keychain reset.
    Second start: must read from file, NOT generate a new one."""
    key_path = tmp_path / "master.key"

    first = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert key_path.exists()

    # Reset Keychain (simulates OS upgrade, corruption, etc.)
    fake_keyring["value"] = None

    second = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert second == first, "Key changed between restarts — old sessions lost"


def test_keyring_broken_falls_back_to_file_only(tmp_path, fake_keyring_broken):
    """Headless Linux without secretservice: keyring always fails. The server
    must work with file only."""
    key_path = tmp_path / "master.key"

    first = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert key_path.exists()
    assert len(first) == crypto_keys.KEY_SIZE

    # Second start: do NOT regenerate
    second = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert second == first


def test_file_corrupt_refuses_to_continue(tmp_path, fake_keyring):
    """WS3-02: a wrong-length (corrupt/tampered) master.key must FAIL CLOSED —
    not silently fall through and regenerate, which would quarantine the existing
    encrypted DB. It raises even when the keyring holds a valid key: the corrupt
    file is a red flag, not to be bypassed silently. Removing the bad file lets the
    keyring recovery path take over on the next start (asserted below)."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"corrupted-too-short")
    keyring_key = b"\x55" * crypto_keys.KEY_SIZE
    fake_keyring["value"] = keyring_key

    with pytest.raises(RuntimeError, match="wrong length"):
        crypto_keys.get_or_create_master_key(key_file_path=key_path)

    # Operational recovery: once the corrupt file is removed, the key is recovered
    # from the keyring — no regeneration, no quarantine of the encrypted DB.
    key_path.unlink()
    recovered = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert recovered == keyring_key


def test_generate_populates_both_sources(tmp_path, fake_keyring):
    """When generating a new MEK from scratch, BOTH sources are populated."""
    key_path = tmp_path / "master.key"
    assert fake_keyring["value"] is None
    assert not key_path.exists()

    key = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert fake_keyring["value"] == key
    assert key_path.read_bytes() == key


def test_file_set_failure_is_logged(tmp_path, monkeypatch, caplog):
    """If the file write fails, it is logged as an error and returns False.
    Robustness for systems with unexpected permissions."""
    import logging
    key = b"\x77" * crypto_keys.KEY_SIZE
    bad_path = tmp_path / "nonwritable.key"

    def _boom(*a, **kw):
        raise OSError("simulated write failure")

    monkeypatch.setattr("os.open", _boom)

    with caplog.at_level(logging.ERROR, logger="core.crypto.keys"):
        ok = crypto_keys._try_file_set(key, path=bad_path)

    assert ok is False
    assert any("Failed to write key file" in r.getMessage() for r in caplog.records)


def test_file_get_read_failure_raises(tmp_path, monkeypatch):
    """B043: if the key file EXISTS but read_bytes() raises (I/O error, lock,
    permission flip, NFS/iCloud stall), _try_file_get must FAIL-CLOSED (raise),
    NOT return None. Returning None is read by get_or_create as 'key absent' →
    a new key is generated → the existing encrypted DB is quarantined as
    .unrecoverable-* (silent data loss). A present-but-unreadable key is a
    transient fault, not an absent key."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"\x88" * crypto_keys.KEY_SIZE)

    def _raise(_self):
        raise OSError("simulated read failure")

    from pathlib import Path as _Path
    monkeypatch.setattr(_Path, "read_bytes", _raise)

    with pytest.raises(RuntimeError):
        crypto_keys._try_file_get(key_path)


def test_present_but_unreadable_key_fails_closed(tmp_path, monkeypatch):
    """B043 (end-to-end): a present-but-unreadable master.key must NOT be
    treated as absent. get_or_create_master_key must fail-closed (raise)
    instead of generating a new key that quarantines the existing encrypted DB."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"\x88" * crypto_keys.KEY_SIZE)

    def _raise(_self):
        raise OSError("EIO/lock/permission")

    from pathlib import Path as _Path
    monkeypatch.setattr(_Path, "read_bytes", _raise)

    with pytest.raises(RuntimeError):
        crypto_keys.get_or_create_master_key(key_path)


def test_env_key_warns_and_is_not_persisted(tmp_path, fake_keyring_broken, monkeypatch, caplog):
    """BONUS-04: a key loaded from NEXE_MASTER_KEY is ephemeral by policy.

    Conservative security policy: we do NOT silently mirror the env-supplied
    secret to master.key nor to the keyring. Instead we emit a clear WARNING so
    the operator knows the key won't survive a restart once the env var is
    unset on a persistent host. This asserts BOTH: (1) the warning fires, and
    (2) nothing is written to disk (no silent persistence).
    """
    import logging

    key_path = tmp_path / "master.key"
    env_key = b"\xab" * crypto_keys.KEY_SIZE
    monkeypatch.setenv(crypto_keys.ENV_VAR_NAME, env_key.hex())
    assert not key_path.exists()

    with caplog.at_level(logging.WARNING, logger="core.crypto.keys"):
        loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    # Positive: the env key is returned as-is.
    assert loaded == env_key
    # Negative: it must NOT be silently written to disk (durability warning, not mirror).
    assert not key_path.exists(), "env-only key must NOT be silently persisted to disk"
    # The operator is warned about the ephemeral nature.
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        crypto_keys.ENV_VAR_NAME in m and "ephemeral" in m.lower() for m in warnings
    ), f"expected an ephemeral-key WARNING mentioning {crypto_keys.ENV_VAR_NAME}, got: {warnings}"


def test_keyring_read_failure_returns_none(monkeypatch):
    """If keyring.get_password crashes, return None silently."""
    def _import_error():
        raise RuntimeError("keyring unavailable")

    # Simulate exception inside _try_keyring_get by intercepting the import
    import sys
    original_keyring = sys.modules.get("keyring")

    class _Failing:
        def get_password(self, *a, **kw):
            raise RuntimeError("broken keychain")

    sys.modules["keyring"] = _Failing()
    try:
        assert crypto_keys._try_keyring_get() is None
    finally:
        if original_keyring is not None:
            sys.modules["keyring"] = original_keyring
        else:
            sys.modules.pop("keyring", None)
