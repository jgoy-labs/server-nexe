"""
Tests per ChatSession.add_message amb image_b64 — Fix bug #19c.

Objectiu: les imatges adjuntades a un missatge han de persistir entre
sessions (save → reload). Abans del fix, add_message() descartava image_b64
i la imatge desapareixia al recarregar.
"""

import base64
import json
import os

import pytest

from plugins.web_ui_module.core.session_manager import ChatSession, SessionManager


SMALL_B64 = base64.b64encode(b"fake-jpg-bytes").decode("ascii")


class TestAddMessageWithImage:

    def test_add_message_accepts_image_b64_kwarg(self):
        s = ChatSession()
        s.add_message("user", "look at this", image_b64=SMALL_B64)
        history = s.get_history()
        assert len(history) == 1
        assert history[0]["image_b64"] == SMALL_B64

    def test_add_message_image_b64_optional_default_none(self):
        """No regressió: add_message sense image_b64 continua funcionant
        i no afegeix la clau al missatge."""
        s = ChatSession()
        s.add_message("user", "text only")
        history = s.get_history()
        assert "image_b64" not in history[0], (
            "Camp image_b64 NO ha d'aparèixer si no s'ha passat — "
            "backward compat de format disc"
        )

    def test_add_message_preserves_image_b64_in_to_dict(self):
        s = ChatSession(session_id="img-dict")
        s.add_message("user", "with image", image_b64=SMALL_B64)
        d = s.to_dict()
        assert d["messages"][0]["image_b64"] == SMALL_B64

    def test_from_dict_restores_image_b64(self):
        payload = {
            "id": "restore",
            "created_at": "2026-04-16T10:00:00+00:00",
            "last_activity": "2026-04-16T10:00:00+00:00",
            "messages": [{
                "role": "user",
                "content": "hello",
                "timestamp": "2026-04-16T10:00:00+00:00",
                "image_b64": SMALL_B64,
            }],
            "context_files": [],
            "attached_document": None,
            "thinking_enabled": False,
            "message_count": 1,
        }
        s = ChatSession.from_dict(payload)
        assert s.get_history()[0]["image_b64"] == SMALL_B64

    def test_add_message_stats_and_image_coexist(self):
        s = ChatSession()
        stats = {"tokens": 42, "latency_ms": 120}
        s.add_message("user", "look", image_b64=SMALL_B64, stats=stats)
        msg = s.get_history()[0]
        assert msg["image_b64"] == SMALL_B64
        assert msg["stats"] == stats


class TestImageSurvivesDiskRoundtrip:

    @pytest.fixture
    def crypto(self):
        from core.crypto.provider import CryptoProvider
        return CryptoProvider(master_key=os.urandom(32))

    def test_image_b64_survives_plain_json_roundtrip(self, tmp_path):
        sm1 = SessionManager(storage_path=str(tmp_path))
        s = sm1.create_session(session_id="plain-img")
        s.add_message("user", "pic", image_b64=SMALL_B64)
        sm1._save_session_to_disk(s)

        sm2 = SessionManager(storage_path=str(tmp_path))
        loaded = sm2.get_session("plain-img")
        assert loaded is not None
        history = loaded.get_history()
        assert history[0]["image_b64"] == SMALL_B64

    def test_image_b64_survives_encrypted_roundtrip(self, tmp_path, crypto):
        sm1 = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        s = sm1.create_session(session_id="enc-img")
        s.add_message("user", "secret pic", image_b64=SMALL_B64)
        sm1._save_session_to_disk(s)

        assert (tmp_path / "enc-img.enc").exists()

        sm2 = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        loaded = sm2.get_session("enc-img")
        assert loaded is not None
        history = loaded.get_history()
        assert history[0]["image_b64"] == SMALL_B64

    def test_image_b64_2mb_survives_roundtrip(self, tmp_path, crypto):
        """Imatge gran (~2MB base64) — no s'ha de truncar ni perdre."""
        big_bytes = os.urandom(1_500_000)  # ~2MB base64
        big_b64 = base64.b64encode(big_bytes).decode("ascii")

        sm1 = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        s = sm1.create_session(session_id="big-img")
        s.add_message("user", "big pic", image_b64=big_b64)
        sm1._save_session_to_disk(s)

        sm2 = SessionManager(storage_path=str(tmp_path), crypto_provider=crypto)
        loaded = sm2.get_session("big-img")
        assert loaded.get_history()[0]["image_b64"] == big_b64

    def test_text_only_message_has_no_image_key_on_disk(self, tmp_path):
        """Verificació backward compat: un missatge sense imatge NO afegeix
        el camp al JSON serialitzat — evita alterar fitxers existents."""
        sm = SessionManager(storage_path=str(tmp_path))
        s = sm.create_session(session_id="plain-no-img")
        s.add_message("user", "just text")
        sm._save_session_to_disk(s)

        raw = (tmp_path / "plain-no-img.json").read_text()
        data = json.loads(raw)
        assert "image_b64" not in data["messages"][0]
