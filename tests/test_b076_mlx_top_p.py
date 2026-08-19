# -*- coding: utf-8 -*-
"""
────────────────────────────────────
Server Nexe
Location: tests/test_b076_mlx_top_p.py
Description: B076 — ARRIVAL proof for the opt-in `top_p` sampling parameter on
             the MLX text path. `top_p` is an opt-in mirror of `temperature`:
             the request value wins when set, else the engine config default
             (≈0.9) is used. These tests do NOT assert on generated text
             (temperature>0 → non-deterministic, no reliable MLX seed). Instead
             a spy on the TERMINAL sampling call (`mlx_lm.sample_utils.make_sampler`)
             captures the exact `top_p` kwarg propagated by
             `MLXChatNode._generate_blocking_inner`.

             RED-ON-MUTATION by construction: each test asserts the EXACT value
             reaching `make_sampler`. If the code reverted to a hardcoded 0.9,
             dropped `top_p`, or stopped honouring `top_p is not None`, the
             equality assert fails.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("mlx_lm", reason="mlx-lm is Apple-Silicon only")

# Module under test (string path reused by the lazy patches below).
_MOD = "plugins.mlx_module.core.chat"


def _make_node(*, top_p_default: float = 0.9, temperature: float = 0.7):
    """Build a bare MLXChatNode without running __init__.

    Only the config attributes touched by `_generate_blocking_inner` are
    populated. `top_p_default` is the engine-config fallback used when the
    per-request `top_p` is None.
    """
    from plugins.mlx_module.core.chat import MLXChatNode

    node = MLXChatNode.__new__(MLXChatNode)
    node.config = MagicMock(
        temperature=temperature,
        top_p=top_p_default,
        max_tokens=32,
        max_session_caches=2,
        max_kv_size=4096,
        model_path="/tmp/fake",
    )
    return node


def _run_inner(node, *, top_p):
    """Invoke `_generate_blocking_inner` with all collaborators mocked and a
    spy installed on the terminal `make_sampler`. Returns the captured spy so
    callers can assert on the kwargs it received.

    `make_sampler` and `get_prompt_cache_manager` are LOCAL imports inside
    `_generate_blocking_inner` (`from mlx_lm.sample_utils import make_sampler`,
    `from .prompt_cache_manager import get_prompt_cache_manager`), so they are
    patched at their SOURCE modules, not on the chat module. The remaining
    helpers are module-level imports in chat.py and are patched there.
    """
    sampler_spy = MagicMock(return_value=MagicMock(name="sampler"))

    # Avoid touching the real filesystem for config.json (model_type read).
    # OSError → the code falls back to model_type="" which is fine here.
    with ExitStack() as stack:
        stack.enter_context(
            patch("mlx_lm.sample_utils.make_sampler", sampler_spy)
        )
        stack.enter_context(
            patch(
                "plugins.mlx_module.core.prompt_cache_manager.get_prompt_cache_manager",
                return_value=MagicMock(name="cache_manager"),
            )
        )
        # _get_model is a bound method on the instance.
        stack.enter_context(
            patch.object(
                node, "_get_model",
                return_value=(MagicMock(name="model"), MagicMock(name="tokenizer")),
            )
        )
        # Module-level helpers imported into chat.py namespace.
        stack.enter_context(
            patch(f"{_MOD}.compute_system_hash", return_value="0" * 64)
        )
        stack.enter_context(
            patch(
                f"{_MOD}.prepare_tokens",
                return_value=([1, 2, 3], [1, 2, 3], [], []),
            )
        )
        stack.enter_context(
            patch(f"{_MOD}.lookup_prefix_cache", return_value=(None, 0, False))
        )
        stack.enter_context(
            patch(f"{_MOD}.determine_tokens_to_process", return_value=([], 0))
        )
        stack.enter_context(
            patch(
                f"{_MOD}.run_streaming_generation",
                return_value=("hi", MagicMock(name="last_response"), 0),
            )
        )
        stack.enter_context(patch(f"{_MOD}.save_cache_post_generation"))
        # extract_metrics is the final return; give it a benign dict so the
        # method returns cleanly without exercising real metric extraction.
        stack.enter_context(
            patch(f"{_MOD}.extract_metrics", return_value={"text": "hi"})
        )
        # Force the config.json read to fail → model_type="" branch, no real IO.
        stack.enter_context(patch(f"{_MOD}.open", side_effect=OSError, create=True))

        node._generate_blocking_inner(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            messages_for_cache=[{"role": "user", "content": "hi"}],
            stream_callback=None,
            session_id="default",
            max_tokens=None,
            temperature=0.7,
            thinking_enabled=True,
            cancel_event=None,
            top_p=top_p,
        )

    return sampler_spy


class TestMLXTopPArrival:
    """The per-request top_p reaches the terminal make_sampler call verbatim."""

    @pytest.mark.parametrize("requested", [0.42, 0.3])
    def test_request_top_p_reaches_make_sampler(self, requested):
        node = _make_node(top_p_default=0.9)
        spy = _run_inner(node, top_p=requested)

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        # EXACT value — a revert to hardcoded 0.9 or dropping top_p fails here.
        assert kwargs["top_p"] == requested
        # Sanity: temperature also flows through (mirror partner), not asserted
        # for determinism but proves the same call carries both.
        assert kwargs["temp"] == 0.7

    def test_request_top_p_overrides_config_default(self):
        """Even when the config default differs, the REQUEST value wins."""
        node = _make_node(top_p_default=0.95)
        spy = _run_inner(node, top_p=0.3)

        assert spy.call_args.kwargs["top_p"] == 0.3  # request, not 0.95


class TestMLXTopPDefault:
    """top_p=None → engine config default is used (opt-in semantics)."""

    def test_none_falls_back_to_config_default(self):
        node = _make_node(top_p_default=0.9)
        spy = _run_inner(node, top_p=None)

        spy.assert_called_once()
        # None must resolve to self.config.top_p (0.9), NOT the user value.
        assert spy.call_args.kwargs["top_p"] == 0.9

    def test_none_uses_whatever_config_default_is(self):
        """The fallback is the config value, not a literal 0.9 in the test:
        if the engine default were 0.8, None must yield 0.8."""
        node = _make_node(top_p_default=0.8)
        spy = _run_inner(node, top_p=None)

        assert spy.call_args.kwargs["top_p"] == 0.8
