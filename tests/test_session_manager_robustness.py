"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_session_manager_robustness.py
Description: Tests defensius per SessionManager._load_sessions (defensa B4 sessions).
             Cobreix: path inexistent, buit, .enc corrupte, session.id mismatch,
             .json plain, mix de casos happy + roïns.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from plugins.web_ui_module.core.session_manager import SessionManager, ChatSession


def _make_failing_crypto():
    """Crypto provider que sempre llança a decrypt."""
    mock = MagicMock()
    mock.decrypt.side_effect = ValueError("AAD mismatch (mock)")
    mock.encrypt.return_value = b""
    return mock


def _make_bad_id_crypto(good_payload: bytes):
    """Crypto provider que retorna payload amb session.id diferent del nom del fitxer."""
    mock = MagicMock()
    mock.decrypt.return_value = good_payload
    mock.encrypt.return_value = good_payload
    return mock


def _make_smart_crypto(good_stem: str, good_payload: bytes):
    """Crypto provider que retorna good_payload per al fitxer good_stem i llança per a la resta."""
    mock = MagicMock()

    def decrypt(data, aad=None):
        if data == good_payload:
            return good_payload
        raise ValueError("corrupted")

    mock.decrypt.side_effect = decrypt
    mock.encrypt.return_value = good_payload
    return mock


class TestSessionManagerRobustness:

    def test_storage_path_inexistent_no_throw(self, tmp_path):
        """Path inexistent → no llança; mkdir crea el directori."""
        storage = tmp_path / "nested" / "sessions"
        sm = SessionManager(storage_path=str(storage))
        assert storage.exists()
        assert sm.corrupted_sessions_count == 0

    def test_empty_storage_no_throw(self, tmp_path):
        """Directori buit → no llança; 0 sessions carregades, 0 corrupted."""
        sm = SessionManager(storage_path=str(tmp_path))
        assert len(sm.list_sessions()) == 0
        assert sm.corrupted_sessions_count == 0

    def test_corrupted_enc_raises_counted(self, tmp_path):
        """.enc corrupte (decrypt llança) → no llança; corrupted_count += 1."""
        crypto = _make_failing_crypto()
        (tmp_path / "abc123.enc").write_bytes(b"garbage-data")
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        assert sm.corrupted_sessions_count == 1
        assert len(sm.list_sessions()) == 0

    def test_session_id_mismatch_counted(self, tmp_path):
        """.enc amb session.id mismatch (swap attack simulat) → counted, no carregat."""
        bad_payload = json.dumps({
            "id": "WRONG-ID",
            "messages": [],
            "context_files": [],
        }).encode()
        crypto = _make_bad_id_crypto(bad_payload)
        # El fitxer es diu "real-file-id.enc" però el contingut diu WRONG-ID
        (tmp_path / "real-file-id.enc").write_bytes(bad_payload)
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        assert sm.corrupted_sessions_count == 1
        assert len(sm.list_sessions()) == 0

    def test_plain_json_loaded_without_crypto(self, tmp_path):
        """.json plain sense crypto provider → es carrega correctament."""
        session = ChatSession(session_id="plain-session")
        session.add_message("user", "test message")
        (tmp_path / "plain-session.json").write_text(
            json.dumps(session.to_dict()), encoding="utf-8"
        )
        sm = SessionManager(storage_path=str(tmp_path))
        sessions = sm.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "plain-session"
        assert sm.corrupted_sessions_count == 0

    def test_mix_happy_and_corrupted(self, tmp_path):
        """Mix: 1 .enc vàlid + 1 .enc corrupte → 1 carregat, 1 comptat com a corrupte."""
        good_id = "good-enc-session"
        good_data = {"id": good_id, "messages": [], "context_files": []}
        good_payload = json.dumps(good_data).encode()

        crypto = _make_smart_crypto(good_id, good_payload)

        (tmp_path / f"{good_id}.enc").write_bytes(good_payload)
        (tmp_path / "bad-enc-session.enc").write_bytes(b"not-the-good-payload")

        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        assert sm.corrupted_sessions_count == 1
        loaded = sm.list_sessions()
        assert len(loaded) == 1
        assert loaded[0]["id"] == good_id
