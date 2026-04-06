"""
Tests per core/crypto/keys.py — Bug 8 fix release v0.9.0.

Verifica que _try_file_set crea el fitxer de master key DIRECTAMENT amb
permisos 0600, sense la finestra TOCTOU prèvia (write_bytes → chmod 600).

Estratègia:
- Mock os.open per capturar el mode passat al obrir el fd.
- Verificació real al filesystem: stat del fitxer creat.
- Test de reescriptura: si ja existeix, també queda 0600.
"""

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from core.crypto import keys as crypto_keys


def test_file_set_creates_with_600_permissions(tmp_path):
    """Després de _try_file_set el fitxer ha de ser 0600."""
    key_path = tmp_path / "master.key"
    key = b"\x01" * crypto_keys.KEY_SIZE
    ok = crypto_keys._try_file_set(key, path=key_path)
    assert ok is True
    assert key_path.exists()
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
    assert key_path.read_bytes() == key


def test_file_set_uses_o_excl_via_temp(tmp_path):
    """El fitxer temporal s'obre amb O_CREAT|O_EXCL|O_WRONLY i mode 0o600.

    Capturem la trucada a os.open per verificar els flags i mode.
    """
    key_path = tmp_path / "master.key"
    key = b"\x02" * crypto_keys.KEY_SIZE

    real_open = os.open
    captured = {}

    def fake_open(path, flags, mode=0o777, *args, **kwargs):
        # Només capturem la trucada al fitxer temp dins del nostre directori
        if str(tmp_path) in str(path) and "master.key.tmp" in str(path):
            captured["path"] = path
            captured["flags"] = flags
            captured["mode"] = mode
        return real_open(path, flags, mode, *args, **kwargs)

    with patch.object(os, "open", side_effect=fake_open):
        ok = crypto_keys._try_file_set(key, path=key_path)

    assert ok is True
    assert "flags" in captured, "os.open never called for the tmp key file"
    assert captured["flags"] & os.O_CREAT
    assert captured["flags"] & os.O_EXCL
    assert captured["flags"] & os.O_WRONLY
    assert captured["mode"] == 0o600


def test_file_set_overwrite_existing_file_keeps_600(tmp_path):
    """Si el fitxer ja existia, la sobreescriptura també queda a 0600."""
    key_path = tmp_path / "master.key"
    key1 = b"\x03" * crypto_keys.KEY_SIZE
    key2 = b"\x04" * crypto_keys.KEY_SIZE

    assert crypto_keys._try_file_set(key1, path=key_path) is True
    assert key_path.read_bytes() == key1

    assert crypto_keys._try_file_set(key2, path=key_path) is True
    assert key_path.read_bytes() == key2

    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600


def test_file_set_cleans_stale_temp(tmp_path):
    """Un .master.key.tmp.<pid> orfe d'un crash previ no ha de bloquejar."""
    key_path = tmp_path / "master.key"
    stale = tmp_path / f".master.key.tmp.{os.getpid()}"
    stale.write_bytes(b"stale-junk")
    assert stale.exists()

    key = b"\x05" * crypto_keys.KEY_SIZE
    ok = crypto_keys._try_file_set(key, path=key_path)
    assert ok is True
    assert key_path.read_bytes() == key
    # El temp s'ha consumit (renomenat al final)
    assert not stale.exists()


def test_file_set_round_trip_with_get(tmp_path):
    """_try_file_get retorna la clau que _try_file_set ha escrit."""
    key_path = tmp_path / "master.key"
    key = b"\x06" * crypto_keys.KEY_SIZE
    crypto_keys._try_file_set(key, path=key_path)
    loaded = crypto_keys._try_file_get(key_path)
    assert loaded == key
