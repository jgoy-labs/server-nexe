"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_session_manager_atomic_write_mc081.py
Description: MC-081 — _save_session_to_disk ha d'escriure de forma ATÒMICA
             (tmp al mateix dir + os.replace). Un crash / disc ple a mig write
             NO ha de truncar el fitxer de sessió existent. La ruta .enc és el
             pitjor cas: el ciphertext és autenticat, així que perdre un sol byte
             fa que TOTA la conversa sigui irrecuperable (InvalidTag → corrupta).
             RED abans del fix (l'original es destrueix); GREEN després (atòmic:
             l'original queda intacte o s'actualitza sencer).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pathlib

import pytest

from plugins.web_ui_module.core.session_manager import SessionManager


@pytest.fixture
def crypto():
    from core.crypto.provider import CryptoProvider
    return CryptoProvider(master_key=os.urandom(32))


def _truncating_write_bytes(self, data):
    """Simula un crash a mig write: trunca el target, n'escriu la meitat i peta."""
    with open(self, "wb") as f:
        f.write(data[: max(1, len(data) // 2)])
    raise OSError("simulated disk full mid-write")


class TestSaveSessionAtomicMC081:
    """Un write fallit no pot deixar la sessió truncada/perduda."""

    def test_failed_enc_write_does_not_destroy_session(self, tmp_path, crypto, monkeypatch):
        sm1 = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        s = sm1.create_session(session_id="atomic-enc")
        s.add_message("user", "first message — must survive")
        sm1._save_session_to_disk(s)
        assert (tmp_path / "atomic-enc.enc").exists()

        # The next write truncates the file and blows up (crash mid-write).
        monkeypatch.setattr(pathlib.Path, "write_bytes", _truncating_write_bytes)
        s.add_message("assistant", "second message")
        sm1._save_session_to_disk(s)  # OLD: destrueix l'original; NEW: atòmic, intacte
        monkeypatch.undo()

        sm2 = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        loaded = sm2.get_session("atomic-enc")
        assert loaded is not None, (
            "la sessió ha de sobreviure a un write fallit (escriptura atòmica)"
        )
        assert sm2._corrupted_sessions_count == 0, (
            "cap sessió corrupta després d'un write fallit"
        )
        contents = [m.get("content") for m in loaded.get_history()]
        assert "first message — must survive" in contents, "no s'ha de perdre la conversa"

    def test_successful_save_leaves_no_tmp_files(self, tmp_path, crypto):
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        s = sm.create_session(session_id="atomic-clean")
        s.add_message("user", "hello")
        sm._save_session_to_disk(s)
        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == ["atomic-clean.enc"], (
            f"després d'un save correcte només hi ha d'haver el .enc, cap tmp orfe: {names}"
        )
