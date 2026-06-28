# -*- coding: utf-8 -*-
"""Regression tests for the MLX cancellation flag (fix 2026-05-14).

Empirical incident 2026-05-13: when the UI clicked Stop, the HTTP client
disconnected (AbortController) but the MLX worker thread kept generating
until ``max_tokens`` (~100s). Single-worker executor (fix #10) meant every
subsequent request waited behind the cancelled one — server effectively
hung from the user's perspective.

Fix #11: propagate a ``threading.Event``-like cancel signal through
``inputs["cancel_event"]`` → ``execute()`` → ``_generate_vlm/_blocking``
→ streaming loops (``_run_vlm_streaming`` and ``run_streaming_generation``).
Each loop checks ``cancel_event.is_set()`` between chunks and breaks early.
"""
import threading
from unittest.mock import MagicMock

import pytest

from plugins.mlx_module.core.chat import MLXChatNode
from plugins.mlx_module.core.config import MLXConfig
from plugins.mlx_module.core.generate_helpers import run_streaming_generation


def _make_config() -> MLXConfig:
    return MLXConfig(model_path="/tmp/fake-model")  # nosemgrep: hardcode.absolute_path


class TestStreamingGenerationCancellation:
    """The text-branch streaming loop must honour cancel_event."""

    def test_cancel_event_set_breaks_loop_immediately(self) -> None:
        # mlx-lm only exists on Apple Silicon (requirements-macos.txt); patch() forces the import.
        pytest.importorskip("mlx_lm", reason="mlx-lm Apple-Silicon-only, absent al CI Linux")
        # Build a generator that would yield 100 fake tokens; the loop must
        # exit at the first iteration where cancel_event is already set.
        cancel_event = threading.Event()
        cancel_event.set()  # pre-set: every iteration sees it True

        emitted: list[str] = []

        def fake_callback(t: str) -> None:
            emitted.append(t)

        # Build minimum mocks so run_streaming_generation reaches the loop.
        tokenizer = MagicMock()
        tokenizer.decode = lambda tids, **kw: "x"

        # Mock stream_generate to yield many responses
        fake_responses = [
            MagicMock(text="tok", token=42, finish_reason=None, prompt_tokens=1, generation_tokens=1)
            for _ in range(100)
        ]
        for r in fake_responses:
            r.text = "x"
            r.token = 42

        from unittest.mock import patch

        cache_manager = MagicMock()
        cache_manager.insert_cache = MagicMock()

        with patch(
            "mlx_lm.stream_generate",
            return_value=iter(fake_responses),
        ):
            text, _last, _gen_tokens = run_streaming_generation(
                model=MagicMock(),
                tokenizer=tokenizer,
                tokens_to_process=MagicMock(),
                max_tokens=1000,
                sampler=MagicMock(),
                cached_kv=MagicMock(),
                stream_callback=fake_callback,
                cache_manager=cache_manager,
                model_key="k",
                cache_lookup_tokens=[1, 2, 3],
                cancel_event=cancel_event,
            )

        # Pre-set cancel_event still lets the first iteration run (prefill +
        # first token, where the helper itself does the bookkeeping), but
        # the rest-of-stream for-loop must break before consuming all 100
        # mocked responses. Empirical: ≤ 5 tokens emitted vs. 100 without
        # the cancel guard.
        assert len(emitted) < 100, (
            f"cancel_event set MUST break the streaming loop; got {len(emitted)} tokens emitted"
        )

    def test_cancel_event_none_runs_to_completion(self) -> None:
        pytest.importorskip("mlx_lm", reason="mlx-lm Apple-Silicon-only, absent al CI Linux")
        # Back-compat: existing callers that don't pass cancel_event must
        # see the full loop (no early break).
        emitted: list[str] = []
        fake_responses = [MagicMock(text=f"tok{i}", token=i) for i in range(5)]
        for r in fake_responses:
            r.text = "x"

        from unittest.mock import patch

        cache_manager = MagicMock()
        cache_manager.insert_cache = MagicMock()

        with patch(
            "mlx_lm.stream_generate",
            return_value=iter(fake_responses),
        ):
            run_streaming_generation(
                model=MagicMock(),
                tokenizer=MagicMock(),
                tokens_to_process=MagicMock(),
                max_tokens=1000,
                sampler=MagicMock(),
                cached_kv=MagicMock(),
                stream_callback=lambda t: emitted.append(t),
                cache_manager=cache_manager,
                model_key="k",
                cache_lookup_tokens=[1],
                cancel_event=None,
            )

        # All 5 fake tokens emitted — proves None behaves like the
        # pre-fix #11 codepath.
        assert len(emitted) == 5


class TestExecuteForwardsCancelEvent:
    """``execute()`` must forward inputs['cancel_event'] to the worker."""

    @pytest.mark.asyncio
    async def test_cancel_event_in_inputs_reaches_partial(self) -> None:
        # Verify the cancel_event lands in the functools.partial bound to
        # the MLX worker (last positional arg of _generate_vlm/_blocking).
        from unittest.mock import patch

        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        cancel_event = threading.Event()
        captured: dict = {}

        async def fake_runner():
            return {
                "text": "ok", "tokens": 1, "prompt_tokens": 1,
                "tokens_per_second": 10.0, "prefix_reused": False,
                "cached_tokens": 0, "actual_prefill_tokens": 1,
                "prompt_tps": 10.0, "peak_memory_mb": 0,
                "identity_hash": "h",
            }

        def fake_run_in_executor(exe, fn):
            captured["fn"] = fn
            return fake_runner()

        fake_loop = MagicMock()
        fake_loop.run_in_executor = fake_run_in_executor

        with patch("plugins.mlx_module.core.chat.asyncio.get_running_loop", return_value=fake_loop), \
             patch("plugins.mlx_module.core.chat._detect_vlm_capability", return_value=False):
            await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "hi"}],
                "cancel_event": cancel_event,
            })

        # functools.partial keeps the bound args in .args — cancel_event
        # is the last one we appended in chat.py.
        partial = captured["fn"]
        assert partial.args[-1] is cancel_event, (
            "cancel_event MUST be bound into the MLX worker invocation"
        )

    @pytest.mark.asyncio
    async def test_missing_cancel_event_defaults_to_none(self) -> None:
        # Back-compat: callers without cancel_event must still work — the
        # worker receives None which the helpers treat as "no cancellation".
        from unittest.mock import patch

        config = _make_config()
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        MLXChatNode._config = config

        captured: dict = {}

        async def fake_runner():
            return {
                "text": "ok", "tokens": 1, "prompt_tokens": 1,
                "tokens_per_second": 10.0, "prefix_reused": False,
                "cached_tokens": 0, "actual_prefill_tokens": 1,
                "prompt_tps": 10.0, "peak_memory_mb": 0,
                "identity_hash": "h",
            }

        def fake_run_in_executor(exe, fn):
            captured["fn"] = fn
            return fake_runner()

        fake_loop = MagicMock()
        fake_loop.run_in_executor = fake_run_in_executor

        with patch("plugins.mlx_module.core.chat.asyncio.get_running_loop", return_value=fake_loop), \
             patch("plugins.mlx_module.core.chat._detect_vlm_capability", return_value=False):
            await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "hi"}],
            })

        partial = captured["fn"]
        assert partial.args[-1] is None, (
            "Missing cancel_event MUST default to None for back-compat"
        )
