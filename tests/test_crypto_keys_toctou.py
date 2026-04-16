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


def test_file_set_uses_unique_temp_via_mkstemp(tmp_path):
    """El fitxer temporal es crea amb `tempfile.mkstemp` (nom únic,
    `O_CREAT|O_EXCL|O_RDWR` internament). Això protegeix contra dues
    crides concurrents dins el mateix procés que intentessin escriure
    el mateix path de temp.
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


def test_file_set_ignores_pre_existing_stale_temp(tmp_path):
    """Un .master.key.tmp.<pid> orfe d'un crash previ no ha de bloquejar.

    El nou patró (tempfile.mkstemp) genera un nom únic cada cop, així que
    un fitxer vell amb un altre suffix queda intacte i la nova escriptura
    continua sense conflicte. La netja dels stale és opcional (no ens posa
    en risc perquè cada crida usa un path nou).
    """
    key_path = tmp_path / "master.key"
    stale = tmp_path / f".master.key.tmp.{os.getpid()}"
    stale.write_bytes(b"stale-junk")
    assert stale.exists()

    key = b"\x05" * crypto_keys.KEY_SIZE
    ok = crypto_keys._try_file_set(key, path=key_path)
    assert ok is True
    assert key_path.read_bytes() == key
    # L'stale no bloqueja la nova escriptura, tot i que no el netegem
    # (innòcu: no conté cap clau vàlida i no interfereix en reads futurs).


def test_file_set_round_trip_with_get(tmp_path):
    """_try_file_get retorna la clau que _try_file_set ha escrit."""
    key_path = tmp_path / "master.key"
    key = b"\x06" * crypto_keys.KEY_SIZE
    crypto_keys._try_file_set(key, path=key_path)
    loaded = crypto_keys._try_file_get(key_path)
    assert loaded == key
