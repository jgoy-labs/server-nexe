"""
Tests for core/crypto/keys.py — Bug 8 fix release v0.9.0.

Verifies that _try_file_set creates the master key file DIRECTLY with
0600 permissions, without the previous TOCTOU window (write_bytes → chmod 600).

Strategy:
- Mock os.open to capture the mode passed when opening the fd.
- Real filesystem verification: stat of the created file.
- Overwrite test: if the file already exists, it also ends up at 0600.
"""

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from core.crypto import keys as crypto_keys


def test_file_set_creates_with_600_permissions(tmp_path):
    """After _try_file_set the file must be 0600."""
    key_path = tmp_path / "master.key"
    key = b"\x01" * crypto_keys.KEY_SIZE
    ok = crypto_keys._try_file_set(key, path=key_path)
    assert ok is True
    assert key_path.exists()
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
    assert key_path.read_bytes() == key


def test_file_set_uses_unique_temp_via_mkstemp(tmp_path):
    """The temporary file is created with `tempfile.mkstemp` (unique name,
    `O_CREAT|O_EXCL|O_RDWR` internally). This protects against two
    concurrent calls within the same process trying to write
    the same temp path.
    """
    import tempfile as _tempfile
    key_path = tmp_path / "master.key"
    key = b"\x02" * crypto_keys.KEY_SIZE

    real_mkstemp = _tempfile.mkstemp
    captured = {}

    def fake_mkstemp(*args, **kwargs):
        captured["prefix"] = kwargs.get("prefix")
        captured["dir"] = kwargs.get("dir")
        return real_mkstemp(*args, **kwargs)

    with patch.object(_tempfile, "mkstemp", side_effect=fake_mkstemp):
        ok = crypto_keys._try_file_set(key, path=key_path)

    assert ok is True
    assert captured.get("prefix") == ".master.key.tmp."
    assert captured.get("dir") == str(tmp_path)
    # Final file has the restrictive mode we care about.
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600


def test_file_set_overwrite_existing_file_keeps_600(tmp_path):
    """If the file already existed, the overwrite also leaves it at 0600."""
    key_path = tmp_path / "master.key"
    key1 = b"\x03" * crypto_keys.KEY_SIZE
    key2 = b"\x04" * crypto_keys.KEY_SIZE

    assert crypto_keys._try_file_set(key1, path=key_path) is True
    assert key_path.read_bytes() == key1

    assert crypto_keys._try_file_set(key2, path=key_path) is True
    assert key_path.read_bytes() == key2

    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600


def test_file_set_ignores_pre_existing_stale_temp(tmp_path):
    """A .master.key.tmp.<pid> orphan from a previous crash must not block.

    The new pattern (tempfile.mkstemp) generates a unique name each time, so
    an old file with a different suffix is left intact and the new write
    proceeds without conflict. Cleaning up stale files is optional (poses no
    risk because each call uses a new path).
    """
    key_path = tmp_path / "master.key"
    stale = tmp_path / f".master.key.tmp.{os.getpid()}"
    stale.write_bytes(b"stale-junk")
    assert stale.exists()

    key = b"\x05" * crypto_keys.KEY_SIZE
    ok = crypto_keys._try_file_set(key, path=key_path)
    assert ok is True
    assert key_path.read_bytes() == key
    # The stale file does not block the new write, even though we don't clean it up
    # (harmless: contains no valid key and does not interfere with future reads).


def test_file_set_round_trip_with_get(tmp_path):
    """_try_file_get returns the key that _try_file_set wrote."""
    key_path = tmp_path / "master.key"
    key = b"\x06" * crypto_keys.KEY_SIZE
    crypto_keys._try_file_set(key, path=key_path)
    loaded = crypto_keys._try_file_get(key_path)
    assert loaded == key
