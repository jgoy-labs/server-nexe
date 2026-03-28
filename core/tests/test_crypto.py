"""
Tests per core/crypto/ — CryptoProvider, key management, encrypt/decrypt.
"""
import os
import stat
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.crypto.provider import CryptoProvider, KEY_SIZE, NONCE_SIZE
from core.crypto.keys import (
    get_or_create_master_key,
    _try_keyring_get,
    _try_keyring_set,
    _try_env_get,
    _try_file_get,
    _try_file_set,
    ENV_VAR_NAME,
)


class TestCryptoProvider:
    """Core encrypt/decrypt functionality."""

    def test_encrypt_decrypt_roundtrip(self):
        key = os.urandom(32)
        crypto = CryptoProvider(master_key=key)
        plaintext = b"Hello, server-nexe!"
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_empty(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        encrypted = crypto.encrypt(b"")
        assert crypto.decrypt(encrypted) == b""

    def test_encrypt_decrypt_large_data(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        plaintext = os.urandom(1024 * 1024)  # 1 MB
        encrypted = crypto.encrypt(plaintext)
        assert crypto.decrypt(encrypted) == plaintext

    def test_different_nonces_per_encrypt(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        plaintext = b"same plaintext"
        enc1 = crypto.encrypt(plaintext)
        enc2 = crypto.encrypt(plaintext)
        # Nonces should differ (first 12 bytes)
        assert enc1[:NONCE_SIZE] != enc2[:NONCE_SIZE]
        # But both decrypt to same plaintext
        assert crypto.decrypt(enc1) == crypto.decrypt(enc2) == plaintext

    def test_wrong_key_fails(self):
        crypto1 = CryptoProvider(master_key=os.urandom(32))
        crypto2 = CryptoProvider(master_key=os.urandom(32))
        encrypted = crypto1.encrypt(b"secret")
        with pytest.raises(Exception):  # InvalidTag
            crypto2.decrypt(encrypted)

    def test_tampered_data_fails(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        encrypted = bytearray(crypto.encrypt(b"secret"))
        encrypted[-1] ^= 0xFF  # flip last byte
        with pytest.raises(Exception):
            crypto.decrypt(bytes(encrypted))

    def test_too_short_data_raises(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        with pytest.raises(ValueError, match="too short"):
            crypto.decrypt(b"short")

    def test_invalid_master_key_length(self):
        with pytest.raises(ValueError, match="must be 32 bytes"):
            CryptoProvider(master_key=b"too_short")

    def test_encrypt_format(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        encrypted = crypto.encrypt(b"test")
        # nonce (12) + ciphertext (4) + tag (16) = 32 minimum
        assert len(encrypted) >= NONCE_SIZE + 16

    def test_different_purposes_different_keys(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        key_sqlite = crypto.derive_key("sqlite")
        key_sessions = crypto.derive_key("sessions")
        assert key_sqlite != key_sessions
        assert len(key_sqlite) == KEY_SIZE
        assert len(key_sessions) == KEY_SIZE

    def test_derive_key_deterministic(self):
        master = os.urandom(32)
        crypto1 = CryptoProvider(master_key=master)
        crypto2 = CryptoProvider(master_key=master)
        assert crypto1.derive_key("sqlite") == crypto2.derive_key("sqlite")

    def test_derive_key_cached(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        key1 = crypto.derive_key("sqlite")
        key2 = crypto.derive_key("sqlite")
        assert key1 is key2  # same object from cache

    def test_derive_key_hex(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        hex_key = crypto.derive_key_hex("sqlite")
        assert len(hex_key) == 64  # 32 bytes = 64 hex chars
        bytes.fromhex(hex_key)  # should not raise

    def test_encrypt_with_purpose(self):
        crypto = CryptoProvider(master_key=os.urandom(32))
        plaintext = b"cross-purpose test"
        enc_sessions = crypto.encrypt(plaintext, purpose="sessions")
        enc_backup = crypto.encrypt(plaintext, purpose="backup")
        # Decrypt with matching purpose works
        assert crypto.decrypt(enc_sessions, purpose="sessions") == plaintext
        assert crypto.decrypt(enc_backup, purpose="backup") == plaintext
        # Decrypt with wrong purpose fails
        with pytest.raises(Exception):
            crypto.decrypt(enc_sessions, purpose="backup")


class TestKeyManagement:
    """Master key retrieval fallback chain."""

    def test_env_var_get(self, monkeypatch):
        key = os.urandom(32)
        monkeypatch.setenv(ENV_VAR_NAME, key.hex())
        result = _try_env_get()
        assert result == key

    def test_env_var_wrong_length(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR_NAME, "aabbccdd")  # 4 bytes, not 32
        assert _try_env_get() is None

    def test_env_var_invalid_hex(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR_NAME, "not-hex-at-all!")
        assert _try_env_get() is None

    def test_env_var_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _try_env_get() is None

    def test_file_get_and_set(self, tmp_path):
        key_path = tmp_path / "test.key"
        key = os.urandom(32)
        assert _try_file_set(key, key_path)
        assert _try_file_get(key_path) == key

    def test_file_get_nonexistent(self, tmp_path):
        assert _try_file_get(tmp_path / "nope.key") is None

    def test_file_get_wrong_length(self, tmp_path):
        key_path = tmp_path / "bad.key"
        key_path.write_bytes(b"short")
        assert _try_file_get(key_path) is None

    def test_file_set_permissions(self, tmp_path):
        key_path = tmp_path / "perm.key"
        _try_file_set(os.urandom(32), key_path)
        mode = key_path.stat().st_mode
        assert mode & stat.S_IRWXG == 0  # no group access
        assert mode & stat.S_IRWXO == 0  # no other access
        assert mode & stat.S_IRUSR != 0  # owner can read
        assert mode & stat.S_IWUSR != 0  # owner can write

    def test_file_set_creates_parent_dirs(self, tmp_path):
        key_path = tmp_path / "sub" / "dir" / "test.key"
        assert _try_file_set(os.urandom(32), key_path)
        assert key_path.exists()

    def test_keyring_get_failure_returns_none(self):
        with patch.dict("sys.modules", {"keyring": None}):
            # Force reimport to hit ImportError
            import importlib
            import core.crypto.keys as keys_mod
            # Simulate keyring raising on import inside function
            mock_keyring = MagicMock()
            mock_keyring.get_password.side_effect = Exception("keyring broken")
            with patch.dict("sys.modules", {"keyring": mock_keyring}):
                assert _try_keyring_get() is None

    def test_keyring_set_failure_returns_false(self):
        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = Exception("keyring broken")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            assert _try_keyring_set(os.urandom(32)) is False

    def test_get_or_create_from_env(self, monkeypatch, tmp_path):
        key = os.urandom(32)
        monkeypatch.setenv(ENV_VAR_NAME, key.hex())
        # Mock keyring to fail so we test env var path
        with patch("core.crypto.keys._try_keyring_get", return_value=None):
            result = get_or_create_master_key(tmp_path / "unused.key")
        assert result == key

    def test_get_or_create_from_file(self, tmp_path):
        key = os.urandom(32)
        key_path = tmp_path / "master.key"
        key_path.write_bytes(key)
        with patch("core.crypto.keys._try_keyring_get", return_value=None), \
             patch.dict(os.environ, {}, clear=True):
            result = get_or_create_master_key(key_path)
        assert result == key

    def test_get_or_create_generates_new(self, tmp_path):
        key_path = tmp_path / "master.key"
        with patch("core.crypto.keys._try_keyring_get", return_value=None), \
             patch("core.crypto.keys._try_keyring_set", return_value=False), \
             patch.dict(os.environ, {}, clear=True):
            result = get_or_create_master_key(key_path)
        assert len(result) == 32
        # Should have been saved to file as fallback
        assert key_path.exists()
        assert key_path.read_bytes() == result

    def test_get_or_create_from_keyring(self, tmp_path):
        key = os.urandom(32)
        with patch("core.crypto.keys._try_keyring_get", return_value=key):
            result = get_or_create_master_key(tmp_path / "unused.key")
        assert result == key

    def test_provider_auto_creates_key(self, tmp_path):
        key_path = tmp_path / "auto.key"
        with patch("core.crypto.keys._try_keyring_get", return_value=None), \
             patch("core.crypto.keys._try_keyring_set", return_value=False), \
             patch.dict(os.environ, {}, clear=True):
            crypto = CryptoProvider(key_file_path=key_path)
        # Should be functional
        enc = crypto.encrypt(b"test")
        assert crypto.decrypt(enc) == b"test"
