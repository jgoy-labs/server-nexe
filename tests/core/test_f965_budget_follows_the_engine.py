"""#965 — the turn's context budget is sized from the live engine, not a flat number.

Before this, `_assemble_engine_messages` read
`int(os.environ.get("NEXE_MAX_CONTEXT_CHARS", "24000"))`: a 32768-token engine
and a 2048-token one were budgeted identically — far too little for the first,
far too much for the second (which then let the engine truncate the prompt with
no one the wiser).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE, DEFAULT_CONTEXT_WINDOW
from core.context_budget import (
    PROMPT_BUDGET_RATIO,
    resolve_max_context_chars,
)


def _engine(window):
    mod = MagicMock()
    mod.get_context_window.return_value = window
    return mod


class TestTheBudgetFollowsTheWindow:

    @pytest.mark.parametrize("window", [2048, 4096, 8192, 16384, 32768, 65536])
    def test_budget_scales_with_the_engine_window(self, window, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        expected = int(window * CHARS_PER_TOKEN_ESTIMATE * PROMPT_BUDGET_RATIO)
        assert resolve_max_context_chars(_engine(window)) == expected

    @pytest.mark.parametrize("window", [512, 2048, 4096])
    def test_tiny_windows_are_never_floored(self, window, monkeypatch) -> None:
        """Regression guard for the floor that was tried and reverted
        (MIN_BUDGET_WINDOW_TOKENS): inflating a tiny window's budget let a
        ~2900-token prompt through to a 2048-token llama.cpp, which does not
        truncate — it raises and the turn dies. The budget must never plan for
        more than the engine's real window."""
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        budget_tokens = resolve_max_context_chars(_engine(window)) / CHARS_PER_TOKEN_ESTIMATE
        assert budget_tokens <= window

    def test_a_bigger_engine_gets_a_bigger_budget(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        assert resolve_max_context_chars(_engine(32768)) > resolve_max_context_chars(_engine(8192))

    def test_a_small_engine_is_not_over_budgeted(self, monkeypatch) -> None:
        """The old flat 24000 chars was ~6000 tokens — three times what a
        2048-token engine can hold, so the prompt was silently truncated."""
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        assert resolve_max_context_chars(_engine(2048)) < 24000

    def test_the_prompt_never_claims_the_whole_window(self) -> None:
        """Room must be left for the answer and for the ~4 chars/token estimate
        being optimistic in Catalan and Spanish."""
        window = 32768
        budget_tokens = resolve_max_context_chars(_engine(window)) / CHARS_PER_TOKEN_ESTIMATE
        assert budget_tokens < window


class TestOverridesAndFallbacks:

    def test_the_env_override_still_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_MAX_CONTEXT_CHARS", "12345")
        assert resolve_max_context_chars(_engine(65536)) == 12345

    def test_a_bad_override_no_longer_takes_the_request_down(self, monkeypatch) -> None:
        """The old code did int(os.environ.get(...)) with no guard: a typo in
        NEXE_MAX_CONTEXT_CHARS raised ValueError mid-turn."""
        monkeypatch.setenv("NEXE_MAX_CONTEXT_CHARS", "not-a-number")
        assert resolve_max_context_chars(_engine(8192)) > 0

    def test_no_engine_falls_back_to_the_default_window(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        expected = int(DEFAULT_CONTEXT_WINDOW * CHARS_PER_TOKEN_ESTIMATE * PROMPT_BUDGET_RATIO)
        assert resolve_max_context_chars(None) == expected

    def test_an_engine_that_cannot_answer_falls_back(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        assert resolve_max_context_chars(_engine(None)) == resolve_max_context_chars(None)

    def test_an_engine_that_raises_does_not_break_the_turn(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        mod = MagicMock()
        mod.get_context_window.side_effect = RuntimeError("boom")
        assert resolve_max_context_chars(mod) == resolve_max_context_chars(None)

    @pytest.mark.parametrize("bogus", [0, -1, "8192", True])
    def test_an_unusable_window_falls_back(self, bogus, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        assert resolve_max_context_chars(_engine(bogus)) == resolve_max_context_chars(None)

    def test_an_engine_without_the_contract_falls_back(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
        assert resolve_max_context_chars(object()) == resolve_max_context_chars(None)


class TestItIsWiredIntoTheAssembler:
    """Testing the resolver alone would stay green while _assemble_engine_messages
    went back to reading a flat env default."""

    def test_the_assembler_asks_the_engine(self) -> None:
        import inspect

        from plugins.web_ui_module.api import routes_chat

        src = inspect.getsource(routes_chat._assemble_engine_messages)
        assert "resolve_max_context_chars(" in src, (
            "_assemble_engine_messages must size the budget from the engine (#965)"
        )
        assert '"24000"' not in src, "the flat 24000-char default must be gone"
