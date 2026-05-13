"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_session_manager_production_safety.py
Description: Regression guards for the production-mode safety contract added
             on 2026-05-13 after 80 plaintext .json sessions silently appeared
             on a production server because SessionManager was constructed
             with crypto_provider=None.

  Contract (two complementary guards):

  1. SessionManager._save_session_to_disk MUST refuse to write a plaintext
     .json file when self._crypto is None AND NEXE_ENV=production. Behaviour
     in development/test is unchanged (.json fallback kept).

  2. WebUIModule.initialize MUST raise when get_server_state().crypto_provider
     returns None AND NEXE_ENV=production, before constructing the
     SessionManager. This stops the plugin from coming up in a state that
     would silently leak chat content to disk.

  Together they make the failure mode loud-and-early instead of silent-and-
  late, and they keep the existing dev/test ergonomics.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio

import pytest

from plugins.web_ui_module.core.session_manager import SessionManager, ChatSession
from plugins.web_ui_module.module import WebUIModule


class TestSaveSessionProductionRefusesPlaintext:
    """SessionManager._save_session_to_disk in production without crypto."""

    def test_production_no_crypto_refuses_to_write_plain_json(
        self, monkeypatch, tmp_path, caplog
    ):
        """In production, no crypto + save → no .json on disk + critical log."""
        monkeypatch.setenv("NEXE_ENV", "production")
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=None)
        session = ChatSession("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

        with caplog.at_level("CRITICAL"):
            sm._save_session_to_disk(session)

        # The exception is caught by the outer try/except and logged as
        # ERROR; what we assert is the empirical contract: no plaintext
        # session file on disk + a critical-level marker in the log.
        assert list(tmp_path.glob("*.json")) == []
        assert list(tmp_path.glob("*.enc")) == []
        assert any(
            "Refusing to write plaintext .json session" in r.getMessage()
            for r in caplog.records
        )

    def test_development_no_crypto_still_writes_plain_json(
        self, monkeypatch, tmp_path
    ):
        """In dev, the .json fallback is preserved (back-compat with tests)."""
        monkeypatch.setenv("NEXE_ENV", "development")
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=None)
        session = ChatSession("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        sm._save_session_to_disk(session)

        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        assert json_files[0].name == f"{session.id}.json"

    def test_unset_env_treated_as_production(self, monkeypatch, tmp_path):
        """No NEXE_ENV exported → defaults to production (safer default)."""
        monkeypatch.delenv("NEXE_ENV", raising=False)
        sm = SessionManager(storage_path=str(tmp_path), crypto_provider=None)
        session = ChatSession("cccccccc-cccc-cccc-cccc-cccccccccccc")

        sm._save_session_to_disk(session)

        assert list(tmp_path.glob("*.json")) == []


class TestWebUIModuleProductionRequiresCrypto:
    """WebUIModule.initialize must fail loud in production without crypto."""

    def test_production_without_crypto_aborts_init(self, monkeypatch, caplog):
        """get_server_state().crypto_provider=None + NEXE_ENV=production →
        initialize() returns False AND session_manager stays None AND a
        critical error is logged. lifespan_modules will then drop this
        plugin from app.state.modules — UI breaks visibly instead of
        silently writing plaintext sessions to disk."""
        monkeypatch.setenv("NEXE_ENV", "production")

        class _StubState:
            crypto_provider = None

        monkeypatch.setattr(
            "core.lifespan.get_server_state", lambda: _StubState()
        )

        mod = WebUIModule()
        with caplog.at_level("ERROR"):
            ok = asyncio.run(mod.initialize({"config": {}}))

        assert ok is False
        assert mod.session_manager is None
        assert any(
            "crypto_provider is None in production" in r.getMessage()
            for r in caplog.records
        )

    def test_development_without_crypto_initializes_with_warning(self, monkeypatch):
        """In dev, missing crypto is tolerated (back-compat)."""
        monkeypatch.setenv("NEXE_ENV", "development")

        class _StubState:
            crypto_provider = None

        monkeypatch.setattr(
            "core.lifespan.get_server_state", lambda: _StubState()
        )

        mod = WebUIModule()
        ok = asyncio.run(mod.initialize({"config": {}}))
        assert ok is True
        assert mod.session_manager is not None
        assert mod.session_manager._crypto is None
