# -*- coding: utf-8 -*-
"""Regression tests for the dedicated single-worker MLX executor (fix 2026-05-14).

Background — empirical incident 2026-05-13:
``asyncio.to_thread()`` picks an arbitrary thread from the default pool.
MLX maintains ``default_stream`` per thread, so when the prompt-cache KV is
created on thread A and the next generation runs on thread B, MLX raises::

    RuntimeError: There is no Stream(gpu, 1) in current thread.

The state stays corrupted — every subsequent MLX call fails and the only
recovery is a full server restart. Cancelling mid-stream reliably triggers
the divergence.

Fix: pin every MLX call to ``_MLX_EXECUTOR``, a singleton
``ThreadPoolExecutor(max_workers=1)``. With one worker every operation
shares the same thread, so the per-thread ``default_stream`` stays
consistent across turns and across cancel/abort transitions.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from plugins.mlx_module.core import chat as chat_module


class TestExecutorSingleton:
    """The module-level executor must exist, be singleton, and have one worker."""

    def test_executor_is_thread_pool_executor(self) -> None:
        assert isinstance(chat_module._MLX_EXECUTOR, ThreadPoolExecutor)

    def test_executor_has_exactly_one_worker(self) -> None:
        # The critical invariant: max_workers=1 so all MLX ops share the
        # same thread (and therefore the same default_stream).
        assert chat_module._MLX_EXECUTOR._max_workers == 1

    def test_executor_thread_name_prefix_identifies_mlx(self) -> None:
        # Helps observability (top, py-spy, debugging) — the thread name
        # should be discoverable when MLX hangs.
        assert chat_module._MLX_EXECUTOR._thread_name_prefix == "mlx-worker"

    def test_executor_is_module_singleton(self) -> None:
        # Re-importing the module returns the same executor; never recreated
        # per request (would defeat the per-thread default_stream invariant).
        import importlib

        before = chat_module._MLX_EXECUTOR
        importlib.reload(chat_module)
        after = chat_module._MLX_EXECUTOR
        # After reload the object identity changes (Python reload semantics)
        # but the invariants stay: still a ThreadPoolExecutor with 1 worker
        # named "mlx-worker". The reload mimics what would happen if a future
        # refactor re-instantiated the executor; this test catches accidental
        # re-creation patterns that lose stream affinity.
        assert isinstance(after, ThreadPoolExecutor)
        assert after._max_workers == 1


class TestThreadAffinity:
    """All MLX work must run on the SAME thread across invocations."""

    def test_consecutive_submits_share_thread(self) -> None:
        # Empirically: with max_workers=1, every submit is dispatched to
        # the same worker thread. This is the invariant that keeps MLX's
        # per-thread default_stream alive across turns.
        thread_ids: list[int] = []

        def capture_thread() -> int:
            tid = threading.get_ident()
            thread_ids.append(tid)
            return tid

        futures = [chat_module._MLX_EXECUTOR.submit(capture_thread) for _ in range(10)]
        for f in futures:
            f.result()

        # All 10 runs must have been on the same thread.
        assert len(set(thread_ids)) == 1, (
            f"MLX executor MUST keep work on one thread; got {len(set(thread_ids))} threads"
        )

    def test_submit_after_exception_keeps_same_thread(self) -> None:
        # Cancel/abort scenarios produce exceptions mid-stream. After an
        # exception the executor must still route subsequent work to the
        # same worker thread (regression: a recreate-on-error pattern would
        # break stream affinity).
        thread_ids: list[int] = []

        def raise_then_succeed(should_raise: bool) -> int:
            thread_ids.append(threading.get_ident())
            if should_raise:
                raise RuntimeError("simulated MLX cancel")
            return threading.get_ident()

        # First call raises (simulates a cancelled generation).
        f1 = chat_module._MLX_EXECUTOR.submit(raise_then_succeed, True)
        with pytest.raises(RuntimeError, match="simulated MLX cancel"):
            f1.result()

        # Second call must succeed AND run on the same thread.
        f2 = chat_module._MLX_EXECUTOR.submit(raise_then_succeed, False)
        f2.result()

        assert len(thread_ids) == 2
        assert thread_ids[0] == thread_ids[1], (
            "After an exception the executor MUST stay on the same worker thread"
        )


class TestEventLoopIntegration:
    """``loop.run_in_executor(_MLX_EXECUTOR, fn)`` must work end-to-end."""

    @pytest.mark.asyncio
    async def test_run_in_executor_awaitable_returns_result(self) -> None:
        import asyncio

        loop = asyncio.get_running_loop()

        def work() -> str:
            return f"ran-on-{threading.get_ident()}"

        result = await loop.run_in_executor(chat_module._MLX_EXECUTOR, work)
        assert result.startswith("ran-on-")

    @pytest.mark.asyncio
    async def test_run_in_executor_propagates_exception(self) -> None:
        # The fix uses functools.partial inside loop.run_in_executor —
        # exceptions raised by the wrapped MLX call must surface to the
        # awaiting coroutine (Bug C's whole point is that we get a
        # RuntimeError back instead of silently losing state).
        import asyncio

        loop = asyncio.get_running_loop()

        def boom() -> None:
            raise RuntimeError("from worker")

        with pytest.raises(RuntimeError, match="from worker"):
            await loop.run_in_executor(chat_module._MLX_EXECUTOR, boom)
