# -*- coding: utf-8 -*-
"""Qwen3.5 thinking-force directive — pure, stateless helpers.

These three symbols were factored out of ``core/chat.py`` on 2026-08-20.
They carry no MLX dependency and no module state, and both consumers need
them: ``chat.py`` (the VLM template path) and ``generate_helpers.py`` (the
text path). While they lived in ``chat.py``, ``generate_helpers`` had to
import them back from inside a function body, which closed an import cycle
``chat -> generate_helpers -> chat``. Living here, they are a leaf both
modules import normally and the cycle no longer exists.

The bodies are unchanged from ``chat.py``: this is the fix for the
empirical incident of 2026-05-13 (Qwen3.5 on MLX silently skipping its
reasoning in multi-turn conversations), and the rationale is documented in
the docstrings below.

Keep this module a leaf: importing ``chat`` or ``generate_helpers`` from
here would restore the cycle. ``tests/plugins/mlx_module/
test_qwen35_thinking_directive.py`` asserts that it does not.
"""
from typing import Any, Dict, List


QWEN35_THINKING_DIRECTIVE = (
    "[CRITICAL INSTRUCTION]\n"
    "You MUST reason step-by-step inside <think>...</think> tags before "
    "answering. Always think first, even for simple greetings. This is a "
    "strict, non-negotiable requirement that overrides every other rule "
    "in this system prompt.\n"
    "[/CRITICAL INSTRUCTION]"
)


def _qwen35_needs_thinking_directive(model_type: str, thinking_enabled: bool) -> bool:
    """Decide if the Qwen3.5 thinking-force directive must be injected.

    Empirical incident 2026-05-13: with Raonament=ON the Qwen3.5 family on
    MLX silently skips reasoning in multi-turn conversations. Root cause is
    *not* the chat template (which already pre-opens ``<think>`` by default)
    but the model itself: when the prior assistant turns in the history
    contain no ``<think>...</think>`` blocks, Qwen3.5 mimics that pattern
    and emits ``</think>`` right after the prompt opener, producing a direct
    answer with no visible reasoning box on the client.

    The fix is scoped to ``model_type startswith 'qwen3_5'`` only, per
    Jordi's explicit instruction:

    - gpt-oss: uses native ``<|channel|>analysis<|message|>`` reasoning,
      already works on MLX.
    - gemma-4: no thinking support in the family.
    - other Qwen (qwen2, qwen3 base): not currently bundled; explicit guard
      against false positives.

    Returns True iff (a) the toggle is ON, (b) the model is Qwen3.5.
    """
    if not thinking_enabled:
        return False
    return model_type.startswith("qwen3_5")


def _inject_thinking_directive_into_messages(
    messages: List[Dict[str, Any]], directive: str
) -> List[Dict[str, Any]]:
    """Return a copy of ``messages`` with ``directive`` reinforcing thinking.

    The directive is **prepended** to the system message content (not
    appended) so it stays visible at the top of long system prompts —
    empirically the Nexe system prompt is ~4000 chars, and appending the
    directive at the end caused the model to ignore it (lost in context).
    If no system message exists, a new one is inserted at index 0.

    The original list is not mutated.
    """
    if not directive:
        return messages
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        existing = str(first.get("content") or "").strip()
        first["content"] = f"{directive}\n\n{existing}" if existing else directive
        return [first, *messages[1:]]
    return [{"role": "system", "content": directive}, *messages]
