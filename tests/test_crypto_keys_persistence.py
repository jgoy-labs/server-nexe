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


def test_file_corrupt_falls_through_to_keyring(tmp_path, fake_keyring):
    """If the file exists but has the wrong size (corrupt/tampered),
    the system must fall through to the keyring, not crash."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"corrupted-too-short")
    keyring_key = b"\x55" * crypto_keys.KEY_SIZE
    fake_keyring["value"] = keyring_key

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == keyring_key, "Must fall back to keyring if file is corrupt"


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


def test_file_get_read_failure_returns_none(tmp_path, monkeypatch):
    """If Path.read_bytes() fails for unexpected reasons, _try_file_get
    returns None and the fallback continues."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"\x88" * crypto_keys.KEY_SIZE)

    def _raise(_self):
        raise OSError("simulated read failure")

    from pathlib import Path as _Path
    monkeypatch.setattr(_Path, "read_bytes", _raise)

    assert crypto_keys._try_file_get(key_path) is None


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
