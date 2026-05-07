"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_session_manager_robustness.py
Description: Defensive tests for SessionManager._load_sessions (B4 session defence).
             Covers: non-existent path, empty, corrupt .enc, session.id mismatch,
             plain .json, mix of happy + bad cases.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from plugins.web_ui_module.core.session_manager import SessionManager, ChatSession


def _make_failing_crypto():
    """Crypto provider that always raises on decrypt."""
    mock = MagicMock()
    mock.decrypt.side_effect = ValueError("AAD mismatch (mock)")
    mock.encrypt.return_value = b""
    return mock


def _make_bad_id_crypto(good_payload: bytes):
    """Crypto provider that returns a payload with a session.id different from the filename."""
    mock = MagicMock()
    mock.decrypt.return_value = good_payload
    mock.encrypt.return_value = good_payload
    return mock


def _make_smart_crypto(good_stem: str, good_payload: bytes):
    """Crypto provider that returns good_payload for the good_stem file and raises for the rest."""
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
        """Non-existent path → does not raise; mkdir creates the directory."""
        storage = tmp_path / "nested" / "sessions"
        sm = SessionManager(storage_path=str(storage))
        assert storage.exists()
        assert sm.corrupted_sessions_count == 0

    def test_empty_storage_no_throw(self, tmp_path):
        """Empty directory → does not raise; 0 sessions loaded, 0 corrupted."""
        sm = SessionManager(storage_path=str(tmp_path))
        assert len(sm.list_sessions()) == 0
        assert sm.corrupted_sessions_count == 0

    def test_corrupted_enc_raises_counted(self, tmp_path):
        """Corrupt .enc (decrypt raises) → does not raise; corrupted_count += 1."""
        crypto = _make_failing_crypto()
        (tmp_path / "abc123.enc").write_bytes(b"garbage-data")
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        assert sm.corrupted_sessions_count == 1
        assert len(sm.list_sessions()) == 0

    def test_session_id_mismatch_counted(self, tmp_path):
        """.enc with session.id mismatch (simulated swap attack) → counted, not loaded."""
        bad_payload = json.dumps({
            "id": "WRONG-ID",
            "messages": [],
            "context_files": [],
        }).encode()
        crypto = _make_bad_id_crypto(bad_payload)
        # The file is named "real-file-id.enc" but the content says WRONG-ID
        (tmp_path / "real-file-id.enc").write_bytes(bad_payload)
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        assert sm.corrupted_sessions_count == 1
        assert len(sm.list_sessions()) == 0

    def test_plain_json_loaded_without_crypto(self, tmp_path):
        """Plain .json without crypto provider → loaded correctly."""
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
        """Mix: 1 valid .enc + 1 corrupt .enc → 1 loaded, 1 counted as corrupt."""
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
