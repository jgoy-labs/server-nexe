"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_lifespan_helpers.py
Description: Tests for the private helpers extracted from lifespan
             (refactor CCN 27→2, façana facade).
────────────────────────────────────
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lifespan import (
    _cancel_background_tasks,
    _reset_circuit_breakers,
    _shutdown,
    _startup,
    _startup_final_banner,
    _startup_init,
    _startup_phases_and_tokens,
    _startup_services,
    server_state,
)


# ── _reset_circuit_breakers ───────────────────────────────────────────────────

class TestResetCircuitBreakers:
    def test_succeeds_when_module_available(self, monkeypatch):
        called = []
        fake_mod = MagicMock()
        fake_mod.reset_all_circuit_breakers = lambda: called.append(True)
        monkeypatch.setitem(__import__("sys").modules, "core.resilience", fake_mod)
        _reset_circuit_breakers()
        assert len(called) == 1

    def test_noop_when_module_missing(self, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "core.resilience", None)
        _reset_circuit_breakers()  # no error


# ── _cancel_background_tasks ──────────────────────────────────────────────────

class TestCancelBackgroundTasks:
    @pytest.mark.asyncio
    async def test_cancels_pending_task(self, monkeypatch):
        task = MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        task.cancel.return_value = True

        async def _fake_await():
            raise asyncio.CancelledError()

        task.__await__ = lambda self: _fake_await().__await__()

        monkeypatch.setattr(server_state, "_cleanup_task", task, raising=False)
        monkeypatch.setattr(server_state, "_session_cleanup_task", None, raising=False)
        monkeypatch.setattr(server_state, "_prewarm_task", None, raising=False)

        await _cancel_background_tasks()
        task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_already_done_task(self, monkeypatch):
        task = MagicMock(spec=asyncio.Task)
        task.done.return_value = True

        monkeypatch.setattr(server_state, "_cleanup_task", task, raising=False)
        monkeypatch.setattr(server_state, "_session_cleanup_task", None, raising=False)
        monkeypatch.setattr(server_state, "_prewarm_task", None, raising=False)

        await _cancel_background_tasks()
        task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_none_tasks(self, monkeypatch):
        monkeypatch.setattr(server_state, "_cleanup_task", None, raising=False)
        monkeypatch.setattr(server_state, "_session_cleanup_task", None, raising=False)
        monkeypatch.setattr(server_state, "_prewarm_task", None, raising=False)

        await _cancel_background_tasks()  # no error


# ── _startup_final_banner ─────────────────────────────────────────────────────

class TestStartupFinalBanner:
    def test_runs_without_error(self, monkeypatch):
        monkeypatch.setattr(server_state, "config", {}, raising=False)
        monkeypatch.setattr(server_state, "crypto_provider", None, raising=False)
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        _startup_final_banner()  # no error

    def test_crypto_enabled_when_provider_set(self, monkeypatch, caplog):
        import logging
        monkeypatch.setattr(server_state, "config", {}, raising=False)
        monkeypatch.setattr(server_state, "crypto_provider", object(), raising=False)
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        with caplog.at_level(logging.INFO, logger="core.lifespan"):
            _startup_final_banner()
        assert any("ENABLED" in r.message for r in caplog.records)

    def test_crypto_disabled_when_no_provider(self, monkeypatch, caplog):
        import logging
        monkeypatch.setattr(server_state, "config", {}, raising=False)
        monkeypatch.setattr(server_state, "crypto_provider", None, raising=False)
        monkeypatch.delenv("NEXE_API_BASE_URL", raising=False)
        monkeypatch.delenv("NEXE_PRIMARY_API_KEY", raising=False)
        with caplog.at_level(logging.INFO, logger="core.lifespan"):
            _startup_final_banner()
        assert any("disabled" in r.message for r in caplog.records)
