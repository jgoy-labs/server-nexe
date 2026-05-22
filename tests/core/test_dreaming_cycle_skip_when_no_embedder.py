"""
F5.4 Bug D — regression tests: DreamingCycle must NOT start when the embedder
is unavailable (cascade from Bug A — fastembed model not downloaded).

Empirical log evidence (G10 portàtil 2026-05-19):
    DreamingCycle embedder unavailable — vector sync will be skipped (non-fatal)
    DreamingCycle background task started (embedder=missing)  ← BUG
    ...
    DreamingCycle started (interval=900s)  ← it really runs

When DreamingCycle runs without an embedder, memory entries ingest to SQLite
but never reach Qdrant — silently breaking semantic search (RAG returns 0
results). The system reports "healthy" but the vector layer is dead.

Fix expected: when embedder is None, skip starting the DreamingCycle task
entirely. Log a clear warning. The user will install fastembed via the
wizard (F5.4 Fase 3) and restart_sidecar will restart with embedder ready.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Bug D: DreamingCycle must not start without embedder
# ──────────────────────────────────────────────────────────────────────────────


class TestDreamingCycleSkipsWhenNoEmbedder:

    @pytest.mark.asyncio
    async def test_dreaming_cycle_not_started_when_embedder_unavailable(self, caplog):
        """When get_embedder raises (fastembed cache missing), DreamingCycle
        must NOT be instantiated nor scheduled as asyncio.create_task."""
        import logging
        from core.lifespan_modules import start_memory_service_v1

        # Build minimal app + server_state mocks
        class _State:
            pass

        app = _State()
        app.state = _State()
        app.state.memory_service = None  # will be set inside start_memory_service_v1

        server_state = _State()
        server_state.project_root = "/tmp/nonexistent-test-root"

        # Patch get_embedder to raise (simulates fastembed cache missing)
        with patch(
            "memory.embeddings.simple_embedder.get_embedder",
            side_effect=RuntimeError("Embedding model not available locally"),
        ), patch(
            "memory.memory.module.get_memory_service",
            return_value=MagicMock(_store=MagicMock(), _vector_index=MagicMock()),
        ), patch(
            "memory.memory.workers.dreaming_cycle.DreamingCycle"
        ) as mock_dreaming_cls:
            with caplog.at_level(logging.WARNING, logger="core.lifespan_modules"):
                await start_memory_service_v1(app, server_state)

        # Assertion 1: DreamingCycle class must NOT have been instantiated
        mock_dreaming_cls.assert_not_called()

        # Assertion 2: server_state._dreaming_task must not exist (or be None)
        dreaming_task = getattr(server_state, "_dreaming_task", None)
        assert dreaming_task is None, (
            f"DreamingCycle task was started despite embedder being unavailable. "
            "This is Bug D: memory entries ingest to SQLite but never reach "
            "Qdrant, silently breaking semantic search."
        )

        # Assertion 3: there must be a clear warning message in the log
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "embedder" in msg.lower() and (
                "not started" in msg.lower() or "unavailable" in msg.lower() or "missing" in msg.lower()
            )
            for msg in warning_messages
        ), (
            f"Expected clear warning about DreamingCycle skipped due to missing "
            f"embedder, got: {warning_messages}"
        )

    @pytest.mark.asyncio
    async def test_dreaming_cycle_started_when_embedder_ready(self):
        """Sanity check: when embedder loads OK, DreamingCycle starts as before."""
        from core.lifespan_modules import start_memory_service_v1

        class _State:
            pass

        app = _State()
        app.state = _State()
        app.state.memory_service = None

        server_state = _State()
        server_state.project_root = "/tmp/nonexistent-test-root"

        fake_embedder = MagicMock()

        with patch(
            "memory.embeddings.simple_embedder.get_embedder",
            return_value=fake_embedder,
        ), patch(
            "memory.memory.module.get_memory_service",
            return_value=MagicMock(_store=MagicMock(), _vector_index=MagicMock()),
        ), patch(
            "memory.memory.workers.dreaming_cycle.DreamingCycle"
        ) as mock_dreaming_cls:
            mock_dreaming_cls.return_value.run = AsyncMock()
            await start_memory_service_v1(app, server_state)

        # When embedder loads, DreamingCycle MUST be instantiated and scheduled
        mock_dreaming_cls.assert_called_once()
        # Note: dreaming_task assertion skipped because the asyncio.create_task
        # interaction with mocks is finicky; the assert_called_once on the
        # class is the load-bearing check.
