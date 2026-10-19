"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_1153_reset_model_on_the_worker.py
Description: #1153 — `reset_model` frees what MLX holds on the MLX worker.

`_MLX_EXECUTOR` is the one thread every MLX operation runs on: a stream belongs
to the thread that first used it. `reset_model` cleared the prompt caches and the
allocator's cache on the thread that called it. Its only caller is the module's
shutdown, so nothing broke, but it contradicted the rule (and #1137 had to move
the same clear to the worker for a hot swap).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core import chat as chat_mod
from plugins.mlx_module.core.chat import _MLX_EXECUTOR, MLXChatNode


@pytest.fixture(autouse=True)
def _clean_state():
    MLXChatNode._model = MLXChatNode._tokenizer = MLXChatNode._config = None
    yield
    MLXChatNode._model = MLXChatNode._tokenizer = MLXChatNode._config = None


def _spy():
    """Where the two things `reset_model` frees through MLX actually ran."""
    seen: dict[str, str] = {}

    def caches():
        seen["caches"] = threading.current_thread().name

    mx = MagicMock()
    mx.clear_cache.side_effect = lambda: seen.__setitem__("allocator", threading.current_thread().name)
    return seen, caches, mx


def test_the_caches_and_the_allocator_are_freed_on_the_mlx_worker():
    MLXChatNode._model = MagicMock()
    seen, caches, mx = _spy()
    with patch.object(chat_mod, "_free_prompt_caches", caches), \
            patch.dict(sys.modules, {"mlx": MagicMock(core=mx), "mlx.core": mx}):
        MLXChatNode.reset_model()
    assert seen["caches"].startswith("mlx-worker"), seen
    assert seen["allocator"].startswith("mlx-worker"), seen
    assert MLXChatNode._model is None, "the references still go at once, in the caller"


def test_it_is_done_when_reset_model_returns():
    """Waited for: the module's shutdown does not report a reset that has not happened."""
    done = []
    with patch.object(chat_mod, "_free_prompt_caches", lambda: done.append(1)), \
            patch.dict(sys.modules, {"mlx": MagicMock(), "mlx.core": MagicMock()}):
        MLXChatNode.reset_model()
    assert done == [1]


def test_called_from_the_worker_itself_it_does_not_wait_on_itself():
    done = []
    with patch.object(chat_mod, "_free_prompt_caches", lambda: done.append(1)), \
            patch.dict(sys.modules, {"mlx": MagicMock(), "mlx.core": MagicMock()}):
        _MLX_EXECUTOR.submit(MLXChatNode.reset_model).result(timeout=5)
    assert done == [1]


def test_a_busy_worker_does_not_hold_the_caller_for_ever(caplog):
    """A generation in flight is ahead in the queue: the caller waits a bounded
    time, says so, and the memory is freed once the worker gets to it."""
    release, started, done = threading.Event(), threading.Event(), threading.Event()

    def busy():
        started.set()
        release.wait(5)

    blocker = _MLX_EXECUTOR.submit(busy)
    assert started.wait(5)
    with patch.object(chat_mod, "_RESET_WAIT_S", 0.05), \
            patch.object(chat_mod, "_free_prompt_caches", lambda: done.set()), \
            patch.dict(sys.modules, {"mlx": MagicMock(), "mlx.core": MagicMock()}), \
            caplog.at_level("WARNING"):
        try:
            MLXChatNode.reset_model()
            assert not done.is_set(), "queued behind the generation, not run on the caller's thread"
            assert any("worker is busy" in r.getMessage() for r in caplog.records)
        finally:
            release.set()
            blocker.result(timeout=5)
        assert done.wait(5), "and it runs when the worker is free"


def test_the_lock_is_not_held_while_waiting_for_the_worker():
    """A generation on the worker needs `MLXChatNode._lock`: waiting for the worker
    with the lock held would deadlock the two."""
    held_during_wait = []

    def caches():
        # The free runs on the worker; a reentrant acquire on the CALLER's own
        # thread would always succeed, so only the worker's answer counts.
        got = MLXChatNode._lock.acquire(blocking=False)
        held_during_wait.append((threading.current_thread().name.startswith("mlx-worker"), got))
        if got:
            MLXChatNode._lock.release()

    def take_the_lock_on_the_worker():
        # What the generation does on the worker, right ahead of the free.
        with MLXChatNode._lock:
            pass

    with patch.object(chat_mod, "_free_prompt_caches", caches), \
            patch.dict(sys.modules, {"mlx": MagicMock(), "mlx.core": MagicMock()}):
        _MLX_EXECUTOR.submit(take_the_lock_on_the_worker)
        MLXChatNode.reset_model()
    assert held_during_wait == [(True, True)], "the worker could take the lock: the caller was not holding it"


def test_the_wait_is_bounded_but_long_enough_for_an_idle_worker():
    assert 1.0 <= chat_mod._RESET_WAIT_S <= 60.0


def test_an_executor_that_is_already_shut_down_does_not_break_the_reset(caplog):
    """At exit the atexit hook shuts the worker down and cancels what is queued:
    a reset after that finds nothing to submit to, and must not raise."""
    MLXChatNode._model = MagicMock()
    dead = MagicMock()
    dead.submit.side_effect = RuntimeError("cannot schedule new futures after shutdown")
    with patch.object(chat_mod, "_MLX_EXECUTOR", dead), caplog.at_level("INFO"):
        MLXChatNode.reset_model()
    assert MLXChatNode._model is None
    assert any("worker is gone" in r.getMessage() for r in caplog.records)


def test_a_free_cancelled_at_exit_does_not_break_the_reset(caplog):
    from concurrent.futures import Future

    cancelled = Future()
    cancelled.cancel()
    executor = MagicMock()
    executor.submit.return_value = cancelled
    with patch.object(chat_mod, "_MLX_EXECUTOR", executor), caplog.at_level("INFO"):
        MLXChatNode.reset_model()
    assert any("worker is gone" in r.getMessage() for r in caplog.records)


async def test_the_module_shutdown_resets_off_the_event_loop():
    from plugins.mlx_module.module import MLXModule

    loop_thread = threading.current_thread().name
    ran_on = []
    module = MLXModule.__new__(MLXModule)
    module._node = MagicMock()
    module._node.reset_model.side_effect = lambda: ran_on.append(threading.current_thread().name)
    module._initialized = True
    await module.shutdown()
    assert ran_on and ran_on[0] != loop_thread, (ran_on, loop_thread)
    assert module._initialized is False
