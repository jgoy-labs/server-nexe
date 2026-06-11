"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_log_redact_pii.py
Description: MC-109/110/111 — user content (chat messages, memory facts,
    recall queries) must never reach INFO logs in plain. The sidecar log is
    plaintext on disk next to the encrypted stores (RT-05 confirmed live).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import logging

import pytest

from core.log_redact import redact_user_content


SECRET = "em dic Jordi i la meva al·lèrgia és la penicil·lina"


class TestRedactUserContent:
    def test_content_is_redacted_by_default(self, monkeypatch):
        monkeypatch.delenv("NEXE_LOG_SENSITIVE", raising=False)
        out = redact_user_content(SECRET)
        assert SECRET not in out
        assert "Jordi" not in out
        assert "len=" in out and "sha=" in out

    def test_fingerprint_is_stable_for_correlation(self, monkeypatch):
        monkeypatch.delenv("NEXE_LOG_SENSITIVE", raising=False)
        assert redact_user_content(SECRET) == redact_user_content(SECRET)
        assert redact_user_content(SECRET) != redact_user_content(SECRET + "x")

    def test_optin_env_var_returns_plain(self, monkeypatch):
        monkeypatch.setenv("NEXE_LOG_SENSITIVE", "1")
        assert redact_user_content(SECRET) == SECRET

    def test_empty_content(self, monkeypatch):
        monkeypatch.delenv("NEXE_LOG_SENSITIVE", raising=False)
        assert redact_user_content("") == "<empty>"
        assert redact_user_content(None) == "<empty>"


class TestInfoLogsCarryNoUserContent:
    """The actual log sites: INFO records must not contain the user's words."""

    @pytest.mark.asyncio
    async def test_rag_search_log_is_redacted(self, caplog, monkeypatch):
        monkeypatch.delenv("NEXE_LOG_SENSITIVE", raising=False)
        from core.endpoints.chat import _fetch_rag_context

        class _Msg:
            role = "user"
            content = SECRET

        class _Body:
            use_rag = True
            messages = [_Msg()]

        with caplog.at_level(logging.INFO, logger="core.endpoints.chat"):
            # app_state buit → build_rag_context retornarà sense resultats,
            # però la línia de log s'emet ABANS de la cerca.
            try:
                await _fetch_rag_context(_Body(), object(), "ca")
            except Exception:
                pass
        rag_lines = [r.getMessage() for r in caplog.records if "RAG Search" in r.getMessage()]
        assert rag_lines, "expected the RAG Search INFO line"
        assert all(SECRET not in line and "Jordi" not in line for line in rag_lines)

    @pytest.mark.asyncio
    async def test_mem_save_nonstreaming_log_is_redacted(self, caplog, monkeypatch):
        monkeypatch.delenv("NEXE_LOG_SENSITIVE", raising=False)
        from unittest.mock import AsyncMock, MagicMock
        from plugins.web_ui_module.api.routes_chat import _save_mem_saves_nonstreaming

        session = MagicMock()
        session.id = "s1"
        session.messages = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        mh = MagicMock()
        mh.save_to_memory = AsyncMock(return_value={"document_id": "doc-1"})

        with caplog.at_level(logging.INFO, logger="plugins.web_ui_module.api.routes_chat"):
            await _save_mem_saves_nonstreaming([SECRET], session, mh)

        info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("MEM_SAVE" in line for line in info_lines)
        assert all(SECRET not in line for line in info_lines)
