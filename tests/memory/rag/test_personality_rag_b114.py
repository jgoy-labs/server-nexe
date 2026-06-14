"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/rag/test_personality_rag_b114.py
Description: B114 — the legacy RAG module fallback (PersonalityRAG) is a
            structurally-empty dead loop. Its empty result must be AUDIBLE
            (WARNING), not a silent INFO line, so the dead path is observable.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import logging

import pytest

from core.endpoints import chat_rag


class _FakeRagModule:
    """Minimal stand-in for the legacy `rag` module exposing async `search`."""

    def __init__(self, results):
        self._results = results

    async def search(self, request, source=None):
        return self._results


class _FakeAppState:
    def __init__(self, rag_module):
        self.modules = {"rag": rag_module}


@pytest.mark.asyncio
async def test_rag_module_fallback_logs_warning_on_empty_results(caplog):
    """Empty fallback search must emit a WARNING (B114 audible dead-loop).

    Red before fix: the code logs at INFO level → no WARNING record.
    Green after fix: the code logs at WARNING level → record present.
    """
    app_state = _FakeAppState(_FakeRagModule([]))

    with caplog.at_level(logging.WARNING, logger="core.endpoints.chat_rag"):
        result = await chat_rag._rag_module_fallback(app_state, "qualsevol cosa")

    assert result == ""
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("no results" in r.getMessage().lower() for r in warnings), (
        "an empty legacy RAG fallback must log a WARNING, not a silent INFO "
        "(B114: the dead loop has to be observable)"
    )
