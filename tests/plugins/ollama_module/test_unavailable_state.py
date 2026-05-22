"""
F5.4 Bug E — regression tests: OllamaModule must report state="unavailable"
when Ollama daemon is not reachable (not installed, or installed but not
running and not auto-startable).

Empirical log evidence (G10 portàtil 2026-05-19):
    Ollama: Not installed. Install manually from https://ollama.com/download
    plugins.ollama_module.core.client - Ollama not installed — skipping auto-start
    plugins.ollama_module.module - OllamaModule initialized - base_url=http://localhost:11434
    core.lifespan_modules - INFO -   ollama_module initialized successfully  ← FALSE POSITIVE

Then later, any chat to Ollama models fails with ConnectError — which was
the bug behind F5.3 post-wizard chat failure (llama3.2:3b ConnectError).

Fix expected:
  - initialize() returns True (keep at registry — user may install Ollama later)
  - _state = "unavailable" when check_connection() returns False
  - _initialized = False (so /status and routes_chat can distinguish)
  - health_check() reports HealthStatus.UNKNOWN with not_configured message
  - When Ollama IS reachable, behavior unchanged (state="ready").
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def fresh_module():
    from plugins.ollama_module.module import OllamaModule
    return OllamaModule()


# ──────────────────────────────────────────────────────────────────────────────
# Bug E: Ollama unreachable → state=unavailable, kept at registry
# ──────────────────────────────────────────────────────────────────────────────


class TestOllamaModuleUnavailableState:

    @pytest.mark.asyncio
    async def test_initialize_when_ollama_unreachable_returns_true_with_unavailable_state(
        self, fresh_module
    ):
        """Ollama not running and not auto-startable → initialize returns True
        (so plugin stays at registry; user may install Ollama later and
        restart_sidecar) but _state == 'unavailable' so consumers know not
        to route chat to Ollama."""
        # Mock ensure_ollama_running to be a no-op (Ollama not installed → no auto-start)
        # Mock check_connection to return False (daemon not reachable)
        with patch.object(
            fresh_module.client, "ensure_ollama_running",
            new=AsyncMock(return_value=None),
        ), patch.object(
            fresh_module.client, "check_connection",
            new=AsyncMock(return_value=False),
        ):
            result = await fresh_module.initialize(context={})

        assert result is True, (
            "initialize() must return True when Ollama unreachable — plugin "
            "stays at registry for restart_sidecar to retry after user "
            "installs Ollama. False would trigger plugin_modules.pop."
        )
        state = getattr(fresh_module, "_state", None)
        assert state == "unavailable", (
            f"Expected _state == 'unavailable', got: {state!r}. The previous "
            "false-positive 'OllamaModule initialized' caused chat to Ollama "
            "models to fail with ConnectError post-wizard."
        )
        assert fresh_module._initialized is False, (
            "_initialized must be False when Ollama unreachable so /status "
            "and routes_chat can distinguish unavailable plugins from ready."
        )

    @pytest.mark.asyncio
    async def test_initialize_when_ollama_reachable_marks_ready(self, fresh_module):
        """Ollama reachable → _state == 'ready', _initialized True (legacy)."""
        with patch.object(
            fresh_module.client, "ensure_ollama_running",
            new=AsyncMock(return_value=None),
        ), patch.object(
            fresh_module.client, "check_connection",
            new=AsyncMock(return_value=True),
        ):
            result = await fresh_module.initialize(context={})

        assert result is True
        state = getattr(fresh_module, "_state", None)
        assert state == "ready", (
            f"Expected _state == 'ready' when Ollama reachable, got: {state!r}"
        )
        assert fresh_module._initialized is True

    @pytest.mark.asyncio
    async def test_health_check_unavailable_reports_not_configured(self, fresh_module):
        """health_check() must report UNKNOWN with actionable message when
        Ollama is unavailable."""
        from core.loader.protocol import HealthStatus

        with patch.object(
            fresh_module.client, "ensure_ollama_running",
            new=AsyncMock(return_value=None),
        ), patch.object(
            fresh_module.client, "check_connection",
            new=AsyncMock(return_value=False),
        ):
            await fresh_module.initialize(context={})
            health = await fresh_module.health_check()

        assert health.status != HealthStatus.HEALTHY
        assert health.status == HealthStatus.UNKNOWN, (
            f"Expected UNKNOWN when unavailable, got: {health.status}"
        )
        # Message must mention the actionable cause
        msg = (health.message or "").lower()
        assert "ollama not installed" in msg or "not reachable" in msg or \
               "unavailable" in msg or "not_configured" in msg, (
            f"Expected health message to mention Ollama unavailable, "
            f"got: {health.message!r}"
        )
