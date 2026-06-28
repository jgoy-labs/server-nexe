"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_b215_shutdown_order.py
Description: B215 — shutdown ordering. Background tasks (knowledge ingest)
             must be cancelled+joined BEFORE Qdrant and MemoryService are
             closed, so a fire-and-forget ingest can never upsert against a
             store that has already been torn down. Plus a hard join timeout
             so a wedged task cannot block shutdown forever.
────────────────────────────────────
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.lifespan as lifespan
from core.lifespan import _shutdown, server_state


def _make_app():
    app = MagicMock()
    return app


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    """Neutralise everything _shutdown touches except the bits under test."""
    monkeypatch.setattr(server_state, "project_root", None, raising=False)
    monkeypatch.setattr(server_state, "i18n", None, raising=False)
    monkeypatch.setattr(server_state, "ollama_process", None, raising=False)
    monkeypatch.setattr(server_state, "api_integrator", None, raising=False)
    monkeypatch.setattr(server_state, "module_manager", None, raising=False)
    monkeypatch.setattr(server_state, "_cleanup_task", None, raising=False)
    monkeypatch.setattr(server_state, "_session_cleanup_task", None, raising=False)
    monkeypatch.setattr(server_state, "_prewarm_task", None, raising=False)
    monkeypatch.setattr(server_state, "_knowledge_ingest_task", None, raising=False)
    monkeypatch.setattr(server_state, "_dreaming_task", None, raising=False)
    monkeypatch.setattr(server_state, "_dreaming_cycle", None, raising=False)
    # silence the renewer / ollama / pid helpers
    monkeypatch.setattr(lifespan, "stop_bootstrap_token_renewal", AsyncMock())
    monkeypatch.setattr(lifespan, "cleanup_ollama_shutdown", AsyncMock())
    monkeypatch.setattr(lifespan, "_stop_process", MagicMock())
    monkeypatch.setattr(lifespan, "_remove_pid_file", MagicMock())
    monkeypatch.setattr(lifespan, "_reset_circuit_breakers", MagicMock())
    yield


@pytest.mark.asyncio
async def test_background_tasks_cancelled_before_stores_closed(monkeypatch):
    """cancel() of background tasks must happen BEFORE Qdrant/MemoryService close."""
    calls: list[str] = []

    real_cancel = lifespan._cancel_background_tasks

    async def _spy_cancel():
        calls.append("cancel")
        await real_cancel()

    def _spy_qdrant():
        calls.append("qdrant")

    async def _spy_memory(app, state):
        calls.append("memory")

    monkeypatch.setattr(lifespan, "_cancel_background_tasks", _spy_cancel)
    monkeypatch.setattr(lifespan, "_shutdown_qdrant", _spy_qdrant)
    monkeypatch.setattr(lifespan, "_shutdown_memory_service", _spy_memory)

    await _shutdown(_make_app())

    assert "cancel" in calls and "qdrant" in calls and "memory" in calls
    assert calls.index("cancel") < calls.index("qdrant")
    assert calls.index("cancel") < calls.index("memory")


@pytest.mark.asyncio
async def test_shutdown_joins_ingest_task_with_timeout(monkeypatch):
    """A wedged ingest task (ignores cancel) must NOT block shutdown.

    The task swallows ``CancelledError`` and re-sleeps, so the *task* never
    completes. With a plain ``await _task`` (no timeout) the join would hang
    until something else cancels the awaiting coroutine. The hard
    ``asyncio.wait_for`` join timeout in ``_cancel_background_tasks`` bounds
    the wait so shutdown completes promptly regardless.

    We set a tiny join timeout via env and assert shutdown finishes fast.
    With the bug (no timeout) the join hangs → the outer guard fires only
    after a long delay → elapsed >> threshold → FAIL (RED).
    """
    import time as _time

    monkeypatch.setenv("NEXE_SHUTDOWN_JOIN_TIMEOUT", "0.2")

    started = asyncio.Event()
    cancel_seen = {"n": 0}

    async def _wedged():
        # Uncooperative for the FIRST cancel attempts (so the bounded join
        # must time out), but self-destructs after a short wall-clock budget
        # so it can never leak past the test loop.
        started.set()
        deadline = _time.monotonic() + 2.0
        while _time.monotonic() < deadline:
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                cancel_seen["n"] += 1  # ignores cancel while within budget
                continue
        return  # cooperative exit → task completes, no leak

    task = asyncio.create_task(_wedged())
    await started.wait()
    monkeypatch.setattr(server_state, "_knowledge_ingest_task", task, raising=False)
    monkeypatch.setattr(lifespan, "_shutdown_qdrant", MagicMock())
    monkeypatch.setattr(lifespan, "_shutdown_memory_service", AsyncMock())

    start = _time.monotonic()
    # Generous outer bound so the bug (hang) is distinguishable from the
    # fix (fast). With the join timeout the inner call returns in ~0.2s.
    await asyncio.wait_for(_shutdown(_make_app()), timeout=30)
    elapsed = _time.monotonic() - start

    # The fix bounds the join to 0.2s → fast (the wedged task ignores cancel
    # for ~2s, so without a join timeout the shutdown would block ~2s+). The
    # threshold sits between the join timeout (0.2s) and the wedge budget (2s).
    assert elapsed < 1.0, f"shutdown took {elapsed:.2f}s — join timeout missing?"
    assert cancel_seen["n"] >= 1  # cancellation was actually requested

    # ensure the wedged task is fully drained before the loop closes
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass


@pytest.mark.asyncio
async def test_dreaming_cycle_and_task_stopped_before_stores_closed(monkeypatch):
    """MC-119: the dreaming cycle/task must be stopped+cancelled inside
    _cancel_background_tasks — i.e. BEFORE Qdrant/MemoryService teardown — not
    only later inside _shutdown_memory_service (which runs AFTER _shutdown_qdrant).

    Mutation guard: remove '_dreaming_task' from the cancel loop (or the
    _dreaming_cycle.stop() call) in _cancel_background_tasks and this test goes
    RED — the cycle is not stopped / the task is not cancelled before the stores
    close. The pre-existing B215 test never exercised this path because the
    fixture left _dreaming_task/_dreaming_cycle as None.
    """
    order: list[str] = []

    cycle = MagicMock()
    cycle.stop = MagicMock(side_effect=lambda: order.append("dreaming_stop"))

    async def _never_ending():
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            order.append("dreaming_task_cancelled")
            raise

    task = asyncio.create_task(_never_ending())
    await asyncio.sleep(0)  # let the task actually start running

    monkeypatch.setattr(server_state, "_dreaming_cycle", cycle, raising=False)
    monkeypatch.setattr(server_state, "_dreaming_task", task, raising=False)

    def _spy_qdrant():
        order.append("qdrant_closed")

    async def _spy_memory(app, state):
        order.append("memory_closed")

    monkeypatch.setattr(lifespan, "_shutdown_qdrant", _spy_qdrant)
    monkeypatch.setattr(lifespan, "_shutdown_memory_service", _spy_memory)

    await _shutdown(_make_app())

    # The dreaming cycle was stopped AND the task was cancelled...
    assert "dreaming_stop" in order, "DreamingCycle.stop() was not called during shutdown"
    assert "dreaming_task_cancelled" in order, "the dreaming task was not cancelled"
    assert task.cancelled() or task.done()
    # ...both BEFORE the stores were torn down.
    assert order.index("dreaming_stop") < order.index("qdrant_closed")
    assert order.index("dreaming_task_cancelled") < order.index("memory_closed")


@pytest.mark.asyncio
async def test_data_dir_not_modified_after_shutdown_initiated(monkeypatch):
    """No ingest write may reach the store after _shutdown_qdrant has closed it."""
    store = {"closed": False, "writes_after_close": 0, "writes": 0}

    write_gate = asyncio.Event()

    async def _ingest_loop():
        # mimic auto_ingest_knowledge writing into the store repeatedly
        try:
            while True:
                store["writes"] += 1
                if store["closed"]:
                    store["writes_after_close"] += 1
                write_gate.set()
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise

    def _spy_qdrant():
        store["closed"] = True

    async def _slow_memory(app, state):
        # a real teardown step yields control; this gives the still-running
        # ingest loop scheduling windows AFTER qdrant closed. With the buggy
        # order (cancel last) the loop writes here → writes_after_close > 0.
        for _ in range(20):
            await asyncio.sleep(0.005)

    task = asyncio.create_task(_ingest_loop())
    await write_gate.wait()  # ensure it is actively writing
    monkeypatch.setattr(server_state, "_knowledge_ingest_task", task, raising=False)
    monkeypatch.setattr(lifespan, "_shutdown_qdrant", _spy_qdrant)
    monkeypatch.setattr(lifespan, "_shutdown_memory_service", _slow_memory)

    await _shutdown(_make_app())

    # The task was cancelled+joined before qdrant closed → zero writes after close.
    assert store["writes_after_close"] == 0
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
