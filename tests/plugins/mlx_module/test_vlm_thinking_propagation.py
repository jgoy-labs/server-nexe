"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_vlm_thinking_propagation.py
Description: Regression guards for the thinking_enabled propagation through
             the MLX VLM branch, fixed on 2026-05-13 after empirical
             verification that Qwen3.5-27B-4bit kept emitting <think> blocks
             on every chat turn even when the user toggled Raonament off in
             the UI. Root cause was a two-link break:

               1. MLXChatNode.execute() forwarded thinking_enabled to the
                  text branch (_generate_blocking) but not to the VLM branch
                  (_generate_vlm).
               2. _prepare_vlm_prompt called mlx_vlm.prompt_utils.apply_chat_template
                  without enable_thinking=, so the Qwen3/Qwen3.5 chat template
                  fell to its default branch and injected the <think> opener
                  into the prompt — forcing the model to think.

             Fix: thread thinking_enabled all the way down to the kwarg of
             apply_chat_template, with a TypeError fallback for processors
             that don't recognise enable_thinking.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.chat import MLXChatNode


# mlx_vlm is an optional native dep (Apple Silicon only). It is not installed
# in the CI test venv. We register a minimal stub for the duration of these
# tests so the import inside _prepare_vlm_prompt resolves; behaviour is
# always patched in each test, never trusting the real implementation.
@pytest.fixture(autouse=True)
def _stub_mlx_vlm():
    if "mlx_vlm" in sys.modules:
        yield
        return
    fake = MagicMock()
    fake.prompt_utils = MagicMock()
    fake.prompt_utils.apply_chat_template = MagicMock(return_value="prompt")
    sys.modules["mlx_vlm"] = fake
    sys.modules["mlx_vlm.prompt_utils"] = fake.prompt_utils
    try:
        yield
    finally:
        sys.modules.pop("mlx_vlm", None)
        sys.modules.pop("mlx_vlm.prompt_utils", None)


def _build_node():
    """Build a MLXChatNode with a fake config (no real model load)."""
    cfg = MagicMock()
    cfg.model_path = "/tmp/_fake_model_path"
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = cfg
    return node


class TestPrepareVlmPromptForwardsEnableThinking:
    """_prepare_vlm_prompt must forward enable_thinking= when thinking_enabled=False."""

    def test_thinking_off_passes_enable_thinking_false(self):
        node = _build_node()
        processor = MagicMock()
        with patch(
            "mlx_vlm.prompt_utils.apply_chat_template",
            return_value="prompt",
        ) as fake_act, patch(
            "builtins.open",
            side_effect=FileNotFoundError(),  # forces mdl_config={"model_type": ""} branch
        ):
            node._prepare_vlm_prompt(
                messages=[{"role": "user", "content": "hi"}],
                system="",
                processor=processor,
                has_image=False,
                thinking_enabled=False,
            )

        fake_act.assert_called_once()
        kwargs = fake_act.call_args.kwargs
        assert kwargs.get("enable_thinking") is False

    def test_thinking_on_does_not_pass_enable_thinking(self):
        """thinking_enabled=True → no kwarg (let model default decide)."""
        node = _build_node()
        processor = MagicMock()
        with patch(
            "mlx_vlm.prompt_utils.apply_chat_template",
            return_value="prompt",
        ) as fake_act, patch("builtins.open", side_effect=FileNotFoundError()):
            node._prepare_vlm_prompt(
                messages=[{"role": "user", "content": "hi"}],
                system="",
                processor=processor,
                has_image=False,
                thinking_enabled=True,
            )

        fake_act.assert_called_once()
        kwargs = fake_act.call_args.kwargs
        assert "enable_thinking" not in kwargs


class TestPrepareVlmPromptFallback:
    """Processors that raise TypeError on enable_thinking must fall through
    to the no-kwarg call so older / non-Qwen processors keep working."""

    def test_typeerror_falls_back_to_no_kwarg(self):
        node = _build_node()
        processor = MagicMock()

        call_log = []

        def fake_apply(**kwargs):
            call_log.append(kwargs)
            if "enable_thinking" in kwargs:
                raise TypeError(
                    "apply_chat_template() got an unexpected kwarg 'enable_thinking'"
                )
            return "prompt"

        with patch(
            "mlx_vlm.prompt_utils.apply_chat_template",
            side_effect=fake_apply,
        ), patch("builtins.open", side_effect=FileNotFoundError()):
            result = node._prepare_vlm_prompt(
                messages=[{"role": "user", "content": "hi"}],
                system="",
                processor=processor,
                has_image=False,
                thinking_enabled=False,
            )

        assert result == "prompt"
        assert len(call_log) == 2
        assert call_log[0].get("enable_thinking") is False
        assert "enable_thinking" not in call_log[1]


class TestGenerateVlmAcceptsThinkingEnabled:
    """_generate_vlm signature change must accept thinking_enabled and forward it."""

    def test_generate_vlm_signature_accepts_thinking_enabled(self):
        import inspect
        sig = inspect.signature(MLXChatNode._generate_vlm)
        params = sig.parameters
        assert "thinking_enabled" in params, (
            "Regression: _generate_vlm must accept thinking_enabled "
            "(see fix 2026-05-13)"
        )
        assert params["thinking_enabled"].default is True
