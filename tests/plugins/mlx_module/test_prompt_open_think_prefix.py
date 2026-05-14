"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_prompt_open_think_prefix.py
Description: Regression guards for _prompt_has_open_think_prefix and the
             synthetic <think> prefix re-emission in _run_vlm_streaming /
             _run_vlm_oneshot. Added 2026-05-13 after empirical evidence
             that Qwen3.5-27B-4bit (VLM branch on MLX) dumped the full
             reasoning into the visible body of the response because the
             chat template pre-opens <think> in the prompt and the
             model's own stream therefore omits the opening tag, so
             routes_chat._process_content_think_tags never enters
             thinking mode.

Contract:

  * _prompt_has_open_think_prefix → True iff the (stripped) prompt
    ends in <think>. Family-agnostic: catches Qwen3, Qwen3.5, Gemma-4
    and any future chat-template that follows the same pattern,
    without an allowlist.

  * gpt-oss prompts use <|channel|>analysis<|message|> emitted BY THE
    MODEL, so the prompt does NOT end in <think> → helper returns
    False → existing pipeline unchanged.

  * VLM streaming/oneshot helpers must prepend "<think>\\n" exactly
    once when the helper returns True.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.chat import (
    MLXChatNode,
    _prompt_has_open_think_prefix,
)


@pytest.fixture(autouse=True)
def _stub_mlx_vlm():
    """mlx_vlm is an optional native dep — stub it for the tests below
    that exercise the VLM streaming path."""
    if "mlx_vlm" in sys.modules:
        yield
        return
    fake = MagicMock()
    fake.stream_generate = MagicMock()
    fake.generate = MagicMock()
    sys.modules["mlx_vlm"] = fake
    try:
        yield
    finally:
        sys.modules.pop("mlx_vlm", None)


# ── Detector ──────────────────────────────────────────────────────────────


class TestDetector:
    def test_qwen_thinking_on_tail_detected(self):
        """The exact Qwen3/Qwen3.5 chat-template tail with thinking on."""
        prompt = "...<|im_start|>assistant\n<think>\n"
        assert _prompt_has_open_think_prefix(prompt) is True

    def test_qwen_thinking_off_tail_not_detected(self):
        """Thinking off produces <think>\\n\\n</think>\\n\\n — ends in </think>."""
        prompt = "...<|im_start|>assistant\n<think>\n\n</think>\n\n"
        assert _prompt_has_open_think_prefix(prompt) is False

    def test_gpt_oss_channel_tail_not_detected(self):
        """gpt-oss uses <|channel|>analysis<|message|> emitted by the model,
        the prompt itself does NOT end in <think>."""
        prompt = "...<|start|>assistant<|channel|>analysis<|message|>"
        assert _prompt_has_open_think_prefix(prompt) is False

    def test_plain_chat_prompt_not_detected(self):
        prompt = "User: Hi\nAssistant:"
        assert _prompt_has_open_think_prefix(prompt) is False

    def test_empty_or_none_safe(self):
        assert _prompt_has_open_think_prefix("") is False
        assert _prompt_has_open_think_prefix(None) is False  # type: ignore[arg-type]

    def test_trailing_whitespace_tolerated(self):
        """The detector strips trailing whitespace before the suffix check."""
        assert _prompt_has_open_think_prefix("foo\n<think>\n  \n") is True
        assert _prompt_has_open_think_prefix("foo\n<think>") is True


# ── VLM helpers re-emit synthetic <think> opener ──────────────────────────


def _build_node():
    cfg = MagicMock()
    cfg.model_path = "/tmp/_fake"  # nosemgrep: hardcode.absolute_path
    cfg.max_tokens = 64
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = cfg
    return node


class TestVlmStreamingPrependsThinkPrefix:
    """_run_vlm_streaming must emit a synthetic <think>\\n as the first
    chunk when the chat-template injected an open <think> into the prompt."""

    def _run_with_chunks(self, prompt, deltas):
        node = _build_node()
        calls = []
        chunks = [MagicMock(text=d) for d in deltas]
        with patch("mlx_vlm.stream_generate", return_value=iter(chunks)):
            node._run_vlm_streaming(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt=prompt,
                tmp_path=None,
                max_tokens=10,
                stream_callback=calls.append,
            )
        return calls

    def test_open_think_prompt_prepends_synthetic_opener(self):
        calls = self._run_with_chunks(
            prompt="foo<|im_start|>assistant\n<think>\n",
            deltas=["raonament...", "</think>\n", "resposta neta"],
        )
        assert calls[0] == "<think>\n"
        assert calls[1:] == ["raonament...", "</think>\n", "resposta neta"]

    def test_closed_thinking_prompt_does_not_prepend(self):
        calls = self._run_with_chunks(
            prompt="foo<|im_start|>assistant\n<think>\n\n</think>\n\n",
            deltas=["resposta directa"],
        )
        assert calls == ["resposta directa"]

    def test_gpt_oss_style_prompt_does_not_prepend(self):
        calls = self._run_with_chunks(
            prompt="foo<|start|>assistant<|channel|>analysis<|message|>",
            deltas=["analysis tokens"],
        )
        assert calls == ["analysis tokens"]

    def test_empty_first_delta_does_not_consume_the_prefix(self):
        """If the very first chunk has empty text, the prefix is emitted
        with the first NON-empty delta (not silently dropped)."""
        calls = self._run_with_chunks(
            prompt="foo<think>\n",
            deltas=["", "real first chunk"],
        )
        assert calls[0] == "<think>\n"
        assert calls[1] == "real first chunk"


class TestVlmOneshotPrependsThinkPrefix:
    """_run_vlm_oneshot must prepend <think>\\n to the returned text when
    the prompt injected an open <think>."""

    def test_open_think_prompt_prepends(self):
        node = _build_node()
        fake_result = MagicMock(text="raonament...</think>\nresposta")
        with patch("mlx_vlm.generate", return_value=fake_result):
            text, _ = node._run_vlm_oneshot(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt="foo<think>\n",
                tmp_path=None,
                max_tokens=10,
            )
        assert text.startswith("<think>\n")
        assert text == "<think>\nraonament...</think>\nresposta"

    def test_closed_thinking_prompt_does_not_prepend(self):
        node = _build_node()
        fake_result = MagicMock(text="resposta directa")
        with patch("mlx_vlm.generate", return_value=fake_result):
            text, _ = node._run_vlm_oneshot(
                model=MagicMock(),
                processor=MagicMock(),
                formatted_prompt="foo<think>\n\n</think>\n\n",
                tmp_path=None,
                max_tokens=10,
            )
        assert text == "resposta directa"
