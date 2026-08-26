"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_vlm_context_budget.py
Description: Regression guards for #845 on the VLM branch — the prompt-level
             context ceiling reached the text path (47efa879) and stopped
             there, so the branch that every default-model conversation
             actually takes had no ceiling at all.

             Why that matters more than it sounds: chat.py routes to mlx_vlm
             by MODEL, not by whether the message carries an image
             (_detect_vlm_capability reads config.json). The shipped default
             (Qwen3.5) declares vision_config and has vision weights, so it
             answers True — meaning every conversation, image or not, took
             the unbounded branch.

             The trap this pins down, found before writing the fix: the VLM
             branch holds a `processor`, not a tokenizer, and
             Qwen3VLProcessor has NO .encode() — it exposes .tokenizer.
             Handing the processor straight to truncate_messages_to_budget
             raises AttributeError on every VLM turn, which is to say on
             every turn. TestBudgetUsesTheProcessorTokenizer is the guard.

             Known and deliberately not fixed: with an image attached the
             estimate undercounts, because image tokens never pass through
             the text tokenizer. chat.py already states this ("with images
             the count is approximate"); the ceiling is a safety net against
             unbounded growth, not an exact accountant.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.chat import MLXChatNode
from plugins.mlx_module.core.generate_helpers import (
    sanitize_messages_for_alternation,
)


SYSTEM = "You are Nexe."


@pytest.fixture(autouse=True)
def _stub_mlx_vlm():
    """mlx_vlm is Apple-Silicon-only and absent from the CI venv."""
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


def _build_node(max_kv_size, max_tokens=0):
    cfg = MagicMock()
    cfg.model_path = "/tmp/_fake_model_path"  # nosemgrep: hardcode.absolute_path
    cfg.max_kv_size = max_kv_size
    cfg.max_tokens = max_tokens
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = cfg
    return node


def _processor_with_tokenizer():
    """A VLM processor as transformers really builds them: no .encode of its
    own, a .tokenizer that has one. One token per character keeps the
    arithmetic of each test obvious.
    """
    processor = MagicMock()
    del processor.encode  # MagicMock invents attributes; a real one has none
    processor.tokenizer = MagicMock()
    processor.tokenizer.encode = MagicMock(side_effect=lambda s: list(str(s)))
    return processor


def _vlm_messages(node, messages, system, processor=None, max_tokens=None):
    """The message list the VLM branch hands to apply_chat_template."""
    with patch(
        "mlx_vlm.prompt_utils.apply_chat_template", return_value="prompt"
    ) as fake_act, patch("builtins.open", side_effect=FileNotFoundError()):
        node._prepare_vlm_prompt(
            messages=messages,
            system=system,
            processor=processor if processor is not None else _processor_with_tokenizer(),
            has_image=False,
            thinking_enabled=True,
            max_tokens=max_tokens,
        )
    return fake_act.call_args.kwargs["prompt"]


def _history(n, size=40):
    """n alternating turns, `size` characters each (= `size` tokens here)."""
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"{i:02d}" + "x" * (size - 2),
        }
        for i in range(n)
    ]


class TestVlmHonoursTheContextBudget:
    def test_a_long_history_is_truncated(self):
        """The defect: without a ceiling the whole history went to the model."""
        node = _build_node(max_kv_size=600)  # 600 - 0 reply - 256 margin = 344
        got = _vlm_messages(node, _history(20), SYSTEM, max_tokens=0)
        assert len(got) - 1 < 20, "the VLM branch kept the whole history"

    def test_a_generous_budget_drops_nothing(self):
        """Control: the ceiling must not touch a conversation that fits."""
        node = _build_node(max_kv_size=100_000)
        history = _history(6)
        got = _vlm_messages(node, history, SYSTEM, max_tokens=0)
        assert got[1:] == sanitize_messages_for_alternation(history)

    def test_the_most_recent_turn_survives_alone(self):
        """Never emit an empty prompt, however small the budget."""
        node = _build_node(max_kv_size=1)
        history = _history(8)
        got = _vlm_messages(node, history, SYSTEM, max_tokens=0)
        assert len(got) >= 2
        assert got[-1] == history[-1]

    def test_no_budget_configured_means_no_truncation(self):
        """max_kv_size None disables the ceiling, as on the text path."""
        node = _build_node(max_kv_size=None)
        history = _history(40)
        got = _vlm_messages(node, history, SYSTEM, max_tokens=0)
        assert got[1:] == sanitize_messages_for_alternation(history)

    def test_the_reply_is_reserved_out_of_the_budget(self):
        """A larger max_tokens leaves less room for history, as on text."""
        history = _history(20)
        roomy = _vlm_messages(_build_node(max_kv_size=1200), history, SYSTEM, max_tokens=0)
        tight = _vlm_messages(_build_node(max_kv_size=1200), history, SYSTEM, max_tokens=600)
        assert len(tight) < len(roomy)


class TestBudgetUsesTheProcessorTokenizer:
    """The trap: a VLM processor has no .encode() — it has .tokenizer."""

    def test_a_processor_without_encode_still_works(self):
        node = _build_node(max_kv_size=600)
        processor = _processor_with_tokenizer()
        assert not hasattr(processor, "encode")
        got = _vlm_messages(node, _history(20), SYSTEM, processor=processor, max_tokens=0)
        assert len(got) - 1 < 20
        assert processor.tokenizer.encode.called

    def test_a_processor_with_neither_says_so_instead_of_crashing(self, caplog):
        """No way to measure the prompt is a reason to warn, not to die —
        and not to pass in silence either (#950's lesson)."""
        node = _build_node(max_kv_size=600)
        processor = MagicMock()
        del processor.encode
        del processor.tokenizer
        history = _history(20)
        with caplog.at_level("WARNING"):
            got = _vlm_messages(node, history, SYSTEM, processor=processor, max_tokens=0)
        assert got[1:] == sanitize_messages_for_alternation(history)
        assert any("budget" in r.message.lower() or "tokenizer" in r.message.lower()
                   for r in caplog.records), "silent fallback"


class TestOrderIsSanitizeThenTruncate:
    """generate_helpers.py:231 states why: alternation must hold for the
    messages actually KEPT. Truncating first can strand a merged pair."""

    def test_merging_happens_before_the_budget_is_measured(self):
        node = _build_node(max_kv_size=100_000)
        anomalous = [
            {"role": "user", "content": "aaa"},
            {"role": "user", "content": "bbb"},
            {"role": "assistant", "content": "ccc"},
        ]
        got = _vlm_messages(node, anomalous, SYSTEM, max_tokens=0)
        users = [m for m in got if m["role"] == "user"]
        assert len(users) == 1
        assert "aaa" in users[0]["content"] and "bbb" in users[0]["content"]

    def test_what_survives_truncation_still_alternates(self):
        node = _build_node(max_kv_size=600)
        anomalous = [
            {"role": "user", "content": "q" * 40},
            {"role": "user", "content": "r" * 40},
            {"role": "assistant", "content": "s" * 40},
        ] + _history(16)
        got = _vlm_messages(node, anomalous, SYSTEM, max_tokens=0)
        roles = [m["role"] for m in got]
        assert all(a != b for a, b in zip(roles, roles[1:])), roles
