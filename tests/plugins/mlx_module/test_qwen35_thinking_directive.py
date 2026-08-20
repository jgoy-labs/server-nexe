# -*- coding: utf-8 -*-
"""Regression tests for the Qwen3.5 thinking-force directive (fix 2026-05-13).

Scope (per Jordi's explicit instruction):
- MLX engine only.
- Qwen3.5 family only (``model_type`` startswith ``qwen3_5``).
- gpt-oss / gemma-4 / other Qwen versions MUST NOT be touched.

Background: see ``plugins/mlx_module/core/qwen35_directive.py``
for the empirical root cause.
"""
from plugins.mlx_module.core.qwen35_directive import (
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

    def test_prepends_to_existing_system_message(self) -> None:
        # Empirical 2026-05-13: directive MUST be prepended (top of system
        # message), not appended. With the Nexe system prompt at ~4000 chars,
        # appending at the end caused Qwen3.5 to ignore the instruction.
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        out = _inject_thinking_directive_into_messages(
            messages, QWEN35_THINKING_DIRECTIVE
        )
        assert out[0]["role"] == "system"
        assert out[0]["content"].startswith(QWEN35_THINKING_DIRECTIVE)
        assert out[0]["content"].endswith("You are helpful.")
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

    def test_directive_wrapped_in_critical_tags(self) -> None:
        # Tag fences raise the salience of the directive when prepended to
        # a long system prompt — empirically required for Qwen3.5 to obey.
        assert "[CRITICAL INSTRUCTION]" in QWEN35_THINKING_DIRECTIVE
        assert "[/CRITICAL INSTRUCTION]" in QWEN35_THINKING_DIRECTIVE


class TestModuleStaysALeaf:
    """The reason this module exists: it must not import its consumers.

    ``qwen35_directive`` was split out of ``chat.py`` on 2026-08-20 to break
    the ``chat -> generate_helpers -> chat`` import cycle. Both consumers
    import it; if it ever imports either of them back, the cycle returns and
    ``generate_helpers`` needs its function-body import again.
    """

    def test_module_imports_neither_consumer(self) -> None:
        import ast
        from pathlib import Path

        from plugins.mlx_module.core import qwen35_directive

        # Located through the imported module, not a path relative to the
        # working directory, so the test survives being run from anywhere.
        source = Path(qwen35_directive.__file__).read_text(encoding="utf-8")
        # Every import in the module, at any depth — a deferred import inside
        # a function body closes the cycle just as well as a top-level one.
        imported: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)

        assert imported, "expected at least the typing import"
        for module in imported:
            leaf = module.rsplit(".", 1)[-1]
            assert leaf not in {"chat", "generate_helpers"}, (
                f"qwen35_directive imports {module!r} — this restores the "
                "import cycle it was created to remove"
            )

    def test_consumers_re_export_the_symbols(self) -> None:
        # chat.py keeps them importable under its own namespace: anything
        # that used to do `from ...core.chat import QWEN35_THINKING_DIRECTIVE`
        # still works after the move.
        from plugins.mlx_module.core import chat

        assert chat.QWEN35_THINKING_DIRECTIVE is QWEN35_THINKING_DIRECTIVE
        assert chat._qwen35_needs_thinking_directive is _qwen35_needs_thinking_directive
        assert (
            chat._inject_thinking_directive_into_messages
            is _inject_thinking_directive_into_messages
        )
