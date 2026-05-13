# -*- coding: utf-8 -*-
"""Regression tests for the Qwen3.5 thinking-force directive (fix 2026-05-13).

Scope (per Jordi's explicit instruction):
- MLX engine only.
- Qwen3.5 family only (``model_type`` startswith ``qwen3_5``).
- gpt-oss / gemma-4 / other Qwen versions MUST NOT be touched.

Background: see ``plugins/mlx_module/core/chat.py::_qwen35_needs_thinking_directive``
for the empirical root cause.
"""
from plugins.mlx_module.core.chat import (
    QWEN35_THINKING_DIRECTIVE,
    _inject_thinking_directive_into_messages,
    _qwen35_needs_thinking_directive,
)


class TestNeedsDirective:
    """Detector matrix — when does the directive apply?"""

    def test_qwen35_with_thinking_on_returns_true(self) -> None:
        assert _qwen35_needs_thinking_directive("qwen3_5", True) is True

    def test_qwen35_vl_moe_with_thinking_on_returns_true(self) -> None:
        # Future variants under the qwen3_5 umbrella also qualify.
        assert _qwen35_needs_thinking_directive("qwen3_5_vl_moe", True) is True

    def test_qwen35_with_thinking_off_returns_false(self) -> None:
        # Toggle OFF must always disable the directive, regardless of model.
        assert _qwen35_needs_thinking_directive("qwen3_5", False) is False

    def test_gpt_oss_with_thinking_on_returns_false(self) -> None:
        # gpt-oss uses <|channel|>analysis<|message|> natively, no directive needed.
        assert _qwen35_needs_thinking_directive("gpt_oss", True) is False

    def test_gemma4_with_thinking_on_returns_false(self) -> None:
        # Gemma-4 has no usable thinking pipeline on MLX in this codebase.
        assert _qwen35_needs_thinking_directive("gemma4", True) is False

    def test_qwen2_with_thinking_on_returns_false(self) -> None:
        # Older Qwen versions are NOT in scope — explicit guard.
        assert _qwen35_needs_thinking_directive("qwen2", True) is False

    def test_qwen3_base_with_thinking_on_returns_false(self) -> None:
        # qwen3 (without _5 suffix) is NOT in scope — explicit guard.
        assert _qwen35_needs_thinking_directive("qwen3", True) is False

    def test_empty_model_type_returns_false(self) -> None:
        # Unknown / unreadable config.json → never inject.
        assert _qwen35_needs_thinking_directive("", True) is False


class TestInjectDirective:
    """Behaviour of the message-list rewriter."""

    def test_appends_to_existing_system_message(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        out = _inject_thinking_directive_into_messages(
            messages, QWEN35_THINKING_DIRECTIVE
        )
        assert out[0]["role"] == "system"
        assert out[0]["content"].startswith("You are helpful.")
        assert QWEN35_THINKING_DIRECTIVE in out[0]["content"]
        # Subsequent messages must not be touched.
        assert out[1] == {"role": "user", "content": "Hi"}

    def test_prepends_new_system_when_missing(self) -> None:
        messages = [{"role": "user", "content": "Hi"}]
        out = _inject_thinking_directive_into_messages(
            messages, QWEN35_THINKING_DIRECTIVE
        )
        assert out[0] == {"role": "system", "content": QWEN35_THINKING_DIRECTIVE}
        assert out[1] == {"role": "user", "content": "Hi"}

    def test_does_not_mutate_input_list(self) -> None:
        messages = [
            {"role": "system", "content": "Original"},
            {"role": "user", "content": "Hi"},
        ]
        original_first = messages[0]
        _inject_thinking_directive_into_messages(messages, QWEN35_THINKING_DIRECTIVE)
        # Original dict in caller's list must remain pristine.
        assert original_first["content"] == "Original"
        assert messages[0] is original_first

    def test_empty_directive_returns_input_unchanged(self) -> None:
        # Defensive guard: empty directive → no-op (used when detector returns False
        # in callers that pre-compute the string).
        messages = [{"role": "user", "content": "Hi"}]
        out = _inject_thinking_directive_into_messages(messages, "")
        assert out == messages

    def test_empty_system_content_replaced_not_appended(self) -> None:
        # Edge case: system role with blank content. Don't leave a stray
        # double-newline at the start of the directive.
        messages = [
            {"role": "system", "content": "   "},
            {"role": "user", "content": "Hi"},
        ]
        out = _inject_thinking_directive_into_messages(
            messages, QWEN35_THINKING_DIRECTIVE
        )
        assert out[0]["content"] == QWEN35_THINKING_DIRECTIVE

    def test_non_string_system_content_coerced(self) -> None:
        # Defensive: some pipelines pass non-string content (e.g. list of parts).
        # The helper must not crash; coerced via str().
        messages = [
            {"role": "system", "content": None},
            {"role": "user", "content": "Hi"},
        ]
        out = _inject_thinking_directive_into_messages(
            messages, QWEN35_THINKING_DIRECTIVE
        )
        assert out[0]["content"] == QWEN35_THINKING_DIRECTIVE


class TestDirectiveText:
    """The directive string itself must remain stable and actionable."""

    def test_directive_mentions_think_tags(self) -> None:
        assert "<think>" in QWEN35_THINKING_DIRECTIVE
        assert "</think>" in QWEN35_THINKING_DIRECTIVE

    def test_directive_is_imperative(self) -> None:
        # "MUST" is the strong-language marker the model is trained to obey.
        assert "MUST" in QWEN35_THINKING_DIRECTIVE
