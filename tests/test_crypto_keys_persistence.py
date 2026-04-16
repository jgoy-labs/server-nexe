"""
Tests per core/crypto/keys.py — Fix bug #19b pre-release (MEK persistent nivell militar).

Objectiu: garantir que la Master Encryption Key (MEK) mai es regenera mentre
existeixi com a mínim UNA font persistent, i que sempre queda replicada a
AMBDUES fonts (file + keyring) per resistir un reset del Keychain.

Escenari crític: robot autònom es reinicia. Si el Keychain es buida (reset OS,
upgrade), el servidor ha de llegir del fitxer `~/.nexe/master.key`, no generar
una clau nova que invalidi totes les sessions xifrades anteriors.

Estratègia:
- `tmp_path` per aïllar el fitxer de clau real.
- Monkeypatch dels wrappers `_try_keyring_get`/`_try_keyring_set` per simular
  estat del Keychain sense tocar el Keychain real.
"""

import pytest

from core.crypto import keys as crypto_keys


@pytest.fixture
def fake_keyring(monkeypatch):
    """Keychain en memòria per tests."""
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
    """Keyring que falla sempre (ex: Linux headless sense secretservice)."""
    monkeypatch.setattr(crypto_keys, "_try_keyring_get", lambda: None)
    monkeypatch.setattr(crypto_keys, "_try_keyring_set", lambda key: False)


@pytest.fixture(autouse=True)
def no_env_mek(monkeypatch):
    """Assegurar que NEXE_MASTER_KEY no contamina els tests."""
    monkeypatch.delenv(crypto_keys.ENV_VAR_NAME, raising=False)


def test_file_written_even_when_keychain_succeeds(tmp_path, fake_keyring):
    """BUG #19b: al generar una MEK nova, el file ha d'existir EN QUALSEVOL CAS.

    Estat actual (buggy): `if not _try_keyring_set(key): _try_file_set(...)`
    → si el keyring funciona, el file NO es crea. Això deixa el servidor
    depenent d'una única font (Keychain) que pot invalidar-se.
    """
    key_path = tmp_path / "master.key"
    assert not key_path.exists()
    assert fake_keyring["value"] is None

    key = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert len(key) == crypto_keys.KEY_SIZE
    assert key_path.exists(), "File backup NO escrit tot i Keychain OK — risc de pèrdua total"
    assert key_path.read_bytes() == key
    assert fake_keyring["value"] == key, "Keychain també ha de tenir la clau"


def test_file_read_first_before_keychain(tmp_path, fake_keyring):
    """El fitxer és la font primària. Si hi ha fitxer amb una clau vàlida,
    es llegeix d'allà sense consultar el keyring (que podria tenir una altra clau
    antiga o nova incompatible)."""
    key_path = tmp_path / "master.key"
    file_key = b"\x11" * crypto_keys.KEY_SIZE
    keyring_key = b"\x22" * crypto_keys.KEY_SIZE

    crypto_keys._try_file_set(file_key, path=key_path)
    fake_keyring["value"] = keyring_key

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == file_key, "Llegir del file primer: és la font de veritat permanent"


def test_no_regeneration_when_file_exists(tmp_path, fake_keyring):
    """Amb fitxer present i keyring buit, NO generar clau nova."""
    key_path = tmp_path / "master.key"
    original_key = b"\x33" * crypto_keys.KEY_SIZE
    crypto_keys._try_file_set(original_key, path=key_path)
    assert fake_keyring["value"] is None

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == original_key, "Mai regenerar si el file existeix"


def test_keychain_synced_to_file_on_read(tmp_path, fake_keyring):
    """Si només hi ha keychain (sense file), al llegir-la s'ha de sincronitzar al file.

    Cas real: usuari ve d'una versió anterior que només guardava al Keychain.
    Al primer startup amb el nou codi, cal replicar al file per resistir
    futurs resets del Keychain.
    """
    key_path = tmp_path / "master.key"
    keyring_key = b"\x44" * crypto_keys.KEY_SIZE
    fake_keyring["value"] = keyring_key
    assert not key_path.exists()

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == keyring_key
    assert key_path.exists(), "El fitxer no s'ha sincronitzat des del keyring"
    assert key_path.read_bytes() == keyring_key


def test_restart_roundtrip_same_mek_despite_keychain_reset(tmp_path, fake_keyring):
    """Escenari robot autònom: primer start (genera clau). Reset del Keychain.
    Segon start: ha de llegir del file, NO generar nova."""
    key_path = tmp_path / "master.key"

    first = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert key_path.exists()

    # Reset Keychain (simula upgrade OS, corruption, etc.)
    fake_keyring["value"] = None

    second = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert second == first, "Clau ha canviat entre restarts — sessions antigues perdudes"


def test_keyring_broken_falls_back_to_file_only(tmp_path, fake_keyring_broken):
    """Linux headless sense secretservice: keyring sempre falla. El servidor
    ha de funcionar només amb file."""
    key_path = tmp_path / "master.key"

    first = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert key_path.exists()
    assert len(first) == crypto_keys.KEY_SIZE

    # Segon start: NO regenerar
    second = crypto_keys.get_or_create_master_key(key_file_path=key_path)
    assert second == first


def test_file_corrupt_falls_through_to_keyring(tmp_path, fake_keyring):
    """Si el fitxer existeix però té mida incorrecta (corrupte/manipulat),
    el sistema ha de caure al keyring, no crashejar."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"corrupted-too-short")
    keyring_key = b"\x55" * crypto_keys.KEY_SIZE
    fake_keyring["value"] = keyring_key

    loaded = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert loaded == keyring_key, "Cal fallar enrere al keyring si file corrupte"


def test_generate_populates_both_sources(tmp_path, fake_keyring):
    """Al generar una MEK nova des de zero, AMBDUES fonts queden actualitzades."""
    key_path = tmp_path / "master.key"
    assert fake_keyring["value"] is None
    assert not key_path.exists()

    key = crypto_keys.get_or_create_master_key(key_file_path=key_path)

    assert fake_keyring["value"] == key
    assert key_path.read_bytes() == key


def test_file_set_failure_is_logged(tmp_path, monkeypatch, caplog):
    """Si el write del fitxer falla, es loggea com error i retorna False.
    Robustesa per sistemes amb permisos inesperats."""
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
    """Si Path.read_bytes() falla per causes inesperades, _try_file_get
    retorna None i el fallback continua."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(b"\x88" * crypto_keys.KEY_SIZE)

    def _raise(_self):
        raise OSError("simulated read failure")

    from pathlib import Path as _Path
    monkeypatch.setattr(_Path, "read_bytes", _raise)

    assert crypto_keys._try_file_get(key_path) is None


def test_keyring_read_failure_returns_none(monkeypatch):
    """Si el keyring.get_password crasheja, retornem None silenciosament."""
    def _import_error():
        raise RuntimeError("keyring unavailable")

    # Simulem excepció dins _try_keyring_get interceptant l'import
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
