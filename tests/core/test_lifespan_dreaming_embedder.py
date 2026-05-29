"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_lifespan_dreaming_embedder.py
Description: Regression tests — start_memory_service_v1 passes an embedder
             to DreamingCycle so _sync_vector_index actually runs in prod.

Before this fix DreamingCycle was constructed without embedder=, and
_sync_vector_index returned early every cycle — episodic entries
written to SQLite never reached Qdrant. See TODO item N1.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch

try:
    from core.lifespan_modules import start_memory_service_v1
except ImportError:
    pytest.skip("start_memory_service_v1 not available", allow_module_level=True)


def _make_app_with_memory_service():
    """Build a mock app with a MemoryService attached."""
    app = MagicMock()
    ms = MagicMock()
    ms._store = MagicMock()
    ms._vector_index = MagicMock()
    app.state.memory_service = ms
    return app, ms


def _make_server_state(project_root="/tmp"):
    server_state = MagicMock()
    server_state.project_root = project_root
    return server_state


class TestStartMemoryServiceV1PassesEmbedder:

    @pytest.mark.asyncio
    async def test_dreaming_cycle_gets_embedder_when_fastembed_available(self):
        """When fastembed is available, DreamingCycle receives an embedder."""
        app, ms = _make_app_with_memory_service()
        server_state = _make_server_state()

        fake_embedder = MagicMock(name="SimpleEmbedder")
        captured = {}

        def fake_get_memory_service():
            return ms

        def fake_get_embedder(model_name):
            return fake_embedder

        class FakeDreaming:
            def __init__(self, *args, **kwargs):
                captured["kwargs"] = kwargs

            async def run(self):
                return None

        with patch(
            "memory.memory.module.get_memory_service",
            side_effect=fake_get_memory_service,
        ), patch(
            "memory.memory.workers.dreaming_cycle.DreamingCycle",
            FakeDreaming,
        ), patch(
            "memory.embeddings.simple_embedder.get_embedder",
            side_effect=fake_get_embedder,
        ):
            await start_memory_service_v1(app, server_state)

        assert captured["kwargs"].get("embedder") is fake_embedder

    @pytest.mark.asyncio
    async def test_dreaming_cycle_still_starts_if_embedder_load_fails(self):
        """Embedder load failure is non-fatal — DreamingCycle still starts."""
        app, ms = _make_app_with_memory_service()
        server_state = _make_server_state()

        captured = {}

        def fake_get_memory_service():
            return ms

        def fake_get_embedder(model_name):
            raise RuntimeError("no model on disk")

        class FakeDreaming:
            def __init__(self, *args, **kwargs):
                captured["kwargs"] = kwargs

            async def run(self):
                return None

        with patch(
            "memory.memory.module.get_memory_service",
            side_effect=fake_get_memory_service,
        ), patch(
            "memory.memory.workers.dreaming_cycle.DreamingCycle",
            FakeDreaming,
        ), patch(
            "memory.embeddings.simple_embedder.get_embedder",
            side_effect=fake_get_embedder,
        ):
            await start_memory_service_v1(app, server_state)

        # DreamingCycle MUST NOT be constructed when
        # the embedder is unavailable. Previously it ran with embedder=None,
        # silently ingesting to SQLite but never to Qdrant — semantic search
        # returned 0 results. Now the cycle is skipped entirely; the user is
        # expected to download the embedder via the wizard (Step 3) and
        # restart_sidecar to pick it up. See commit c10c5b9.
        assert "kwargs" not in captured, (
            "DreamingCycle was instantiated despite embedder=None. F5.4 Bug "
            "D fix in core/lifespan_modules.py::start_memory_service_v1 "
            "must skip construction when the embedder load fails."
        )
