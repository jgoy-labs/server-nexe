"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_b076_mlx_vlm_top_p.py
Description: Arrival proof for the opt-in `top_p` (nucleus sampling) parameter
             on the MLX VLM branch. We just wired `top_p` as a mirror of
             `temperature` into both VLM terminal sampling points:

               - _run_vlm_streaming → mlx_vlm.stream_generate(**sampling_kwargs)
               - _run_vlm_oneshot   → mlx_vlm.generate(**sampling_kwargs)

             Both build `sampling_kwargs` and pass temperature/top_p ONLY when
             not None, so unset values (and older mlx_vlm) preserve prior
             behaviour.

             These tests do NOT assert on generated text — with temperature>0
             MLX output is non-deterministic and no engine has a reliable seed
             on Metal. Instead a SPY captures the kwargs that reach the terminal
             mlx_vlm call and asserts the EXACT propagated value (0.5 / 0.3).
             That makes them red-on-mutation by construction: if the code ever
             reverted to a hardcoded sampling param, dropped top_p, or ignored
             the caller's value, the exact-value assert would fail. The
             None/None case pins the "empty sampling_kwargs" contract so the
             pre-existing behaviour stays preserved.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


# mlx_vlm is an optional native dep (Apple Silicon only). On Apple Silicon it
# is installed; in a CI venv without it we register a minimal stub so the
# `from mlx_vlm import ...` inside the terminal helpers resolves. Behaviour is
# always patched per test via the SPY, never trusting the real implementation.
@pytest.fixture(autouse=True)
def _stub_mlx_vlm():
    if "mlx_vlm" in sys.modules:
        yield
        return
    fake = MagicMock()
    sys.modules["mlx_vlm"] = fake
    try:
        yield
    finally:
        sys.modules.pop("mlx_vlm", None)


def _build_node():
    """Build an MLXChatNode bypassing __init__ (no real model load).

    config.max_tokens is the only attribute the terminal helpers read
    (`max_tokens or self.config.max_tokens`); we pin it to a small int so the
    fallback branch is harmless.
    """
    from plugins.mlx_module.core.chat import MLXChatNode

    node = MLXChatNode.__new__(MLXChatNode)
    node.config = MagicMock(max_tokens=32)
    return node


class _Chunk:
    """Minimal stream chunk: only `.text` is read by _run_vlm_streaming."""

    def __init__(self, text):
        self.text = text


class _OneResult:
    """Minimal oneshot result: `.text` is read by _run_vlm_oneshot."""

    def __init__(self, text):
        self.text = text


# A plain prompt that does NOT end in "<think>" so the synthetic-think prefix
# branch (_prompt_has_open_think_prefix) stays off and does not perturb output.
_PROMPT = "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n"


class TestRunVlmOneshotTopPArrival:
    """top_p must reach the terminal mlx_vlm.generate call as kwargs."""

    def test_temperature_and_top_p_propagated_exactly(self):
        node = _build_node()
        spy = MagicMock(return_value=_OneResult("ok"))

        with patch("mlx_vlm.generate", spy):
            text, _obj = node._run_vlm_oneshot(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=_PROMPT,
                tmp_path=None,
                max_tokens=16,
                temperature=0.5,
                top_p=0.3,
            )

        assert text == "ok"
        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        # Exact values — a hardcode (e.g. 0.9) or a dropped param fails here.
        assert kwargs["temperature"] == 0.5
        assert kwargs["top_p"] == 0.3

    def test_none_means_empty_sampling_kwargs(self):
        """top_p=None and temperature=None → neither key reaches the call,
        so the engine/library default applies (prior behaviour preserved)."""
        node = _build_node()
        spy = MagicMock(return_value=_OneResult("ok"))

        with patch("mlx_vlm.generate", spy):
            node._run_vlm_oneshot(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=_PROMPT,
                tmp_path=None,
                max_tokens=16,
                temperature=None,
                top_p=None,
            )

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs

    def test_top_p_alone_without_temperature(self):
        """Opt-in is independent: top_p set, temperature unset → only top_p
        propagates (mirror semantics, not coupled)."""
        node = _build_node()
        spy = MagicMock(return_value=_OneResult("ok"))

        with patch("mlx_vlm.generate", spy):
            node._run_vlm_oneshot(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=_PROMPT,
                tmp_path=None,
                max_tokens=16,
                temperature=None,
                top_p=0.42,
            )

        kwargs = spy.call_args.kwargs
        assert kwargs["top_p"] == 0.42
        assert "temperature" not in kwargs


class TestRunVlmStreamingTopPArrival:
    """top_p must reach the terminal mlx_vlm.stream_generate call as kwargs."""

    def test_temperature_and_top_p_propagated_exactly(self):
        node = _build_node()
        captured = []

        def fake_stream(*args, **kwargs):
            captured.append(kwargs)
            return [_Chunk("a"), _Chunk("b")]

        sink = []
        with patch("mlx_vlm.stream_generate", side_effect=fake_stream):
            full_text, _last = node._run_vlm_streaming(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=_PROMPT,
                tmp_path=None,
                max_tokens=16,
                stream_callback=sink.append,
                cancel_event=None,
                prompt_cache_state=None,
                temperature=0.5,
                top_p=0.3,
            )

        assert full_text == "ab"
        assert len(captured) == 1
        kwargs = captured[0]
        # Exact values — a hardcode (e.g. 0.9) or a dropped param fails here.
        assert kwargs["temperature"] == 0.5
        assert kwargs["top_p"] == 0.3

    def test_none_means_empty_sampling_kwargs(self):
        """temperature=None and top_p=None → the stream call receives neither
        sampling key (prior behaviour preserved)."""
        node = _build_node()
        captured = []

        def fake_stream(*args, **kwargs):
            captured.append(kwargs)
            return [_Chunk("a")]

        with patch("mlx_vlm.stream_generate", side_effect=fake_stream):
            node._run_vlm_streaming(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=_PROMPT,
                tmp_path=None,
                max_tokens=16,
                stream_callback=[].append,
                cancel_event=None,
                prompt_cache_state=None,
                temperature=None,
                top_p=None,
            )

        assert len(captured) == 1
        kwargs = captured[0]
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs

    def test_top_p_alone_without_temperature(self):
        """Opt-in is independent on the streaming path too."""
        node = _build_node()
        captured = []

        def fake_stream(*args, **kwargs):
            captured.append(kwargs)
            return [_Chunk("x")]

        with patch("mlx_vlm.stream_generate", side_effect=fake_stream):
            node._run_vlm_streaming(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=_PROMPT,
                tmp_path=None,
                max_tokens=16,
                stream_callback=[].append,
                cancel_event=None,
                prompt_cache_state=None,
                temperature=None,
                top_p=0.42,
            )

        kwargs = captured[0]
        assert kwargs["top_p"] == 0.42
        assert "temperature" not in kwargs
