"""F2.A10: tests for auto_ingest_knowledge background execution.

Validates that auto-ingest runs as a background task (non-blocking) and that
the lifespan can complete startup before ingest finishes.

El knowledge ingest blocant 22s era la causa del Tauri webview
quedant-se "loading" — el splash timeout (30s) saltava abans que uvicorn
acceptés connexions perquè el lifespan esperava l'ingest.
"""
import asyncio
from unittest.mock import patch

import pytest

from core.lifespan import ServerState, _wrap_knowledge_ingest


@pytest.mark.asyncio
async def test_wrap_marks_complete_on_success():
    """Wrapper sets knowledge_ingest_complete=True when ingest succeeds."""
    state = ServerState()
    state.knowledge_ingest_complete = False

    async def fake_ingest(_state):
        return None

    with patch("core.lifespan.auto_ingest_knowledge", side_effect=fake_ingest):
        await _wrap_knowledge_ingest(state)

    assert state.knowledge_ingest_complete is True


@pytest.mark.asyncio
async def test_wrap_does_not_crash_sidecar_on_exception():
    """Wrapper catches Exception, logs warning, keeps flag False, no raise."""
    state = ServerState()
    state.knowledge_ingest_complete = False

    async def failing_ingest(_state):
        raise RuntimeError("simulated ingest failure")

    with patch("core.lifespan.auto_ingest_knowledge", side_effect=failing_ingest):
        await _wrap_knowledge_ingest(state)  # must NOT raise

    assert state.knowledge_ingest_complete is False


@pytest.mark.asyncio
async def test_wrap_propagates_cancellation():
    """Wrapper re-raises CancelledError so the task is cleanly cancelled at shutdown."""
    state = ServerState()
    state.knowledge_ingest_complete = False

    async def slow_ingest(_state):
        await asyncio.sleep(60)

    with patch("core.lifespan.auto_ingest_knowledge", side_effect=slow_ingest):
        task = asyncio.create_task(_wrap_knowledge_ingest(state))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert state.knowledge_ingest_complete is False


@pytest.mark.asyncio
async def test_background_task_does_not_block():
    """A slow ingest as background task does NOT block the caller.

    This is the core invariant of F2.A10: scheduling the wrapper via
    asyncio.create_task returns immediately even if the inner ingest
    would take minutes. The lifespan can finish startup right after.
    """
    state = ServerState()

    async def slow_ingest(_state):
        await asyncio.sleep(60)

    with patch("core.lifespan.auto_ingest_knowledge", side_effect=slow_ingest):
        task = asyncio.create_task(_wrap_knowledge_ingest(state))
        await asyncio.sleep(0.01)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_server_state_has_new_fields():
    """ServerState exposes the new F2.A10 fields with safe defaults."""
    state = ServerState()
    assert state._knowledge_ingest_task is None
    assert state.knowledge_ingest_complete is False
