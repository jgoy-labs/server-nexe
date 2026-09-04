"""#965 — the turn budget and the compaction threshold must not collide.

Written after an adversarial review caught the bug these tests now pin: the
first version of #965 set context_budget.PROMPT_BUDGET_RATIO and
ChatSession.COMPACT_AT_RATIO to the same 0.7, in different files, each with a
comment explaining itself and neither mentioning the other. The history was then
allowed to grow to the entire prompt budget, so `available_chars` went negative
exactly when a conversation reached compaction size — on every engine, at every
window size — and RAG and attached documents were dropped with no log.

Every test here exercises the two pieces TOGETHER. The unit tests of each piece
were all green while this was broken, which is the whole point: nothing tested
the interaction.
"""
from __future__ import annotations

import pytest

from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE
from core.context_budget import (
    PROMPT_BUDGET_RATIO,
    compute_context_budget,
    resolve_max_context_chars,
)
from core.sessions import ChatSession

# Measured from personality/server.toml plus the language directive, the date
# line, the reminder and the RAG rule that _finalize_system_prompt appends.
REAL_SYSTEM_PROMPT_CHARS = 4700

# Every window an engine can report here: llama.cpp/Ollama ladder (2048..32768)
# and MLX's caps (16384..65536).
ENGINE_WINDOWS = [2048, 4096, 8192, 16384, 32768, 65536]

# Windows where "context survives a full conversation" is actually achievable.
# At 2048 the system prompt plus a history at the compaction threshold genuinely
# fill the window; at 4096 what runs out is the BUDGET, not the window — the gap
# between the two ratios ((0.7−0.45)·window·4 chars) only covers the ~4700-char
# system prompt from 8192 up (the gap at 4096 is 4096 chars). Both cases are
# filed as a finding. A floor that pretended otherwise (MIN_BUDGET_WINDOW_TOKENS)
# was tried and reverted: it fed llama.cpp prompts past its n_ctx, which it
# answers with a ValueError, not a truncation. Here we hold the invariant where
# it can hold, and hold "degrade, never crash" everywhere.
ROOMY_WINDOWS = [8192, 16384, 32768, 65536]


class _Engine:
    def __init__(self, window):
        self._window = window

    def get_context_window(self):
        return self._window


def _budget_at_history(window: int, history_chars: int, document_chars: int = 50_000) -> dict:
    return compute_context_budget(
        max_context_chars=resolve_max_context_chars(_Engine(window)),
        system_chars=REAL_SYSTEM_PROMPT_CHARS,
        history_chars=history_chars,
        message_chars=200,
        document_chars=document_chars,
    )


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
    monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
    monkeypatch.delenv("NEXE_HISTORY_CONTEXT_RATIO", raising=False)


class TestTheRatiosCannotCollide:

    def test_the_history_ratio_stays_below_the_prompt_ratio(self) -> None:
        assert ChatSession.COMPACT_AT_RATIO < PROMPT_BUDGET_RATIO, (
            "the history may never be allowed to fill the whole prompt budget"
        )

    def test_the_gap_pays_for_the_system_prompt_and_then_some(self) -> None:
        """Not just smaller — smaller by enough to cover what else must fit."""
        gap_chars = (PROMPT_BUDGET_RATIO - ChatSession.COMPACT_AT_RATIO) * 8192 * CHARS_PER_TOKEN_ESTIMATE
        assert gap_chars > REAL_SYSTEM_PROMPT_CHARS


class TestContextSurvivesAFullConversation:
    """The regression itself: a conversation grown to the point of compaction
    must still have room for retrieved context."""

    @pytest.mark.parametrize("window", ROOMY_WINDOWS)
    def test_room_is_left_at_the_compaction_threshold(self, window) -> None:
        session = ChatSession("t")
        history_chars = session.compaction_threshold_tokens(window) * CHARS_PER_TOKEN_ESTIMATE
        budget = _budget_at_history(window, history_chars)
        assert budget["available_chars"] > 0, (
            f"window {window}: a conversation at compaction size leaves "
            f"{budget['available_chars']} chars for RAG and documents — they get dropped silently"
        )

    @pytest.mark.parametrize("window", ROOMY_WINDOWS)
    def test_a_document_still_reaches_the_model_at_that_point(self, window) -> None:
        session = ChatSession("t")
        history_chars = session.compaction_threshold_tokens(window) * CHARS_PER_TOKEN_ESTIMATE
        budget = _budget_at_history(window, history_chars)
        assert budget["doc_kept_chars"] > 0, (
            f"window {window}: the attached document is dropped entirely once the "
            "conversation is long enough to compact"
        )


class TestThePromptNeverExceedsTheEngineWindow:
    """The hard constraint, everywhere: llama.cpp does not truncate an oversized
    prompt, it raises ('Requested tokens exceed context window') and the turn
    dies. Whatever the budget decides to keep, what actually gets assembled —
    system prompt + history + message + kept document — must fit the window.
    The reverted floor broke exactly this at 2048."""

    @pytest.mark.parametrize("window", ENGINE_WINDOWS)
    def test_a_fresh_conversation_with_a_document_fits(self, window) -> None:
        budget = _budget_at_history(window, history_chars=0)
        prompt_chars = REAL_SYSTEM_PROMPT_CHARS + 0 + 200 + budget["doc_kept_chars"]
        assert prompt_chars <= window * CHARS_PER_TOKEN_ESTIMATE, (
            f"window {window}: the assembled prompt ({prompt_chars} chars) exceeds what "
            "the engine holds — llama.cpp answers that with a ValueError, not a truncation"
        )

    @pytest.mark.parametrize(
        "window",
        [
            pytest.param(
                2048,
                # NOT strict: the overshoot is only ~100 tok (98) on a window of
                # 2048, and REAL_SYSTEM_PROMPT_CHARS is a hand-measured constant
                # with no test tying it to the live prompt — trimming ~400 chars
                # from server.toml would flip a strict xfail into an XPASS and
                # redden the suite with a message that explains nothing.
                marks=pytest.mark.xfail(
                    strict=False,
                    reason=(
                        "at 2048 the ARITHMETIC still overshoots by ~100 tok: the system "
                        "prompt (~1175 tok) plus a history at the 45% threshold (921 tok) "
                        "exceed the window with no document at all. That is now a "
                        "degradation and not a crash — #976 enforces prompt-fits-window "
                        "at assembly time, so the prompt that actually reaches the engine "
                        "is trimmed to the window. What this file measures is the plan, "
                        "not the assembled prompt; the assembled prompt is pinned by "
                        "tests/core/test_f976_prompt_fits_window.py. On main it was far "
                        "worse: the flat session cap allowed 3000 tok of history."
                    ),
                ),
            ),
            4096, 8192, 16384, 32768, 65536,
        ],
    )
    def test_a_conversation_at_compaction_size_fits(self, window) -> None:
        session = ChatSession("t")
        history_chars = session.compaction_threshold_tokens(window) * CHARS_PER_TOKEN_ESTIMATE
        budget = _budget_at_history(window, history_chars)
        prompt_chars = REAL_SYSTEM_PROMPT_CHARS + history_chars + 200 + budget["doc_kept_chars"]
        assert prompt_chars <= window * CHARS_PER_TOKEN_ESTIMATE, (
            f"window {window}: at compaction size the assembled prompt "
            f"({prompt_chars} chars) exceeds the engine window"
        )


class TestSmallWindowsDegradeInsteadOfCrashing:
    """8 GB laptops report a 2048-token window; the ~4700-char system prompt is
    most of it. The honest outcome is that the attached document is dropped (with
    a warning) and the chat keeps working — never that the budget pretends the
    window is bigger and the engine rejects the turn."""

    def test_at_2048_the_document_is_dropped_not_the_turn(self) -> None:
        budget = _budget_at_history(2048, history_chars=0)
        assert budget["doc_kept_chars"] == 0, (
            "at 2048 the system prompt leaves no real room; keeping a slice means "
            "overflowing the engine"
        )

    def test_at_4096_a_slice_of_the_document_still_fits(self) -> None:
        budget = _budget_at_history(4096, history_chars=0)
        assert budget["doc_kept_chars"] > 0

    @pytest.mark.parametrize("window", ROOMY_WINDOWS)
    def test_roomy_windows_keep_the_document_on_turn_one(self, window) -> None:
        budget = _budget_at_history(window, history_chars=0)
        assert budget["doc_kept_chars"] > 0, f"window {window}: document dropped on turn one"

    def test_bigger_engines_always_get_bigger_budgets(self) -> None:
        assert resolve_max_context_chars(_Engine(32768)) > resolve_max_context_chars(_Engine(8192))
        assert resolve_max_context_chars(_Engine(8192)) > resolve_max_context_chars(_Engine(2048))


class TestExhaustionIsNeverSilent:
    """The branch's thesis is that silent context loss is THE bug. The document
    drop already warned; the RAG drop on an exhausted budget did not — which is
    exactly how a negative available_chars stayed invisible through two review
    rounds."""

    def test_dropping_rag_on_an_exhausted_budget_warns(self, caplog) -> None:
        import logging

        from core.context_budget import _inject_context_into_messages

        budget = {"doc_truncated_pct": 0, "doc_kept_chars": 0, "history_reserve": 1000}
        with caplog.at_level(logging.WARNING, logger="core.context_budget"):
            msgs, _, injected = _inject_context_into_messages(
                [], "hola", "", "some retrieved context", budget,
                available_chars=-144, history_chars=9000,
            )
        assert injected is False
        assert msgs == [{"role": "user", "content": "hola"}]
        assert any("budget exhausted" in r.message for r in caplog.records), (
            "dropping retrieved context with no log is the silent loss #965 exists to kill"
        )

    def test_no_warning_when_there_was_nothing_to_drop(self, caplog) -> None:
        import logging

        from core.context_budget import _inject_context_into_messages

        budget = {"doc_truncated_pct": 0, "doc_kept_chars": 0, "history_reserve": 1000}
        with caplog.at_level(logging.WARNING, logger="core.context_budget"):
            _inject_context_into_messages(
                [], "hola", "", "", budget, available_chars=5000, history_chars=100,
            )
        assert not any("budget exhausted" in r.message for r in caplog.records), (
            "a plain turn with no retrieved context must not cry wolf"
        )


class TestTheRatioLeavesRoomForTheAnswer:
    """PROMPT_BUDGET_RATIO itself was pinned by nothing: mutating 0.7 to 0.9
    left every test green while the prompt ate the reply's token budget and the
    engine truncated the answer silently."""

    # Only from 8192 up: below that, prompt budget plus the default reply do not
    # fit even at 0.7 (2867 + 2048 > 4096) — that is the filed small-window
    # squeeze, not a ratio bug. The invariant is held where it must hold, and
    # 0.9 breaks it at 8192 (7373 + 2048 > 8192), which is the tooth.
    @pytest.mark.parametrize("window", [8192, 16384, 32768, 65536])
    def test_budget_plus_default_reply_fit_the_window(self, window) -> None:
        budget_tokens = resolve_max_context_chars(_Engine(window)) / CHARS_PER_TOKEN_ESTIMATE
        default_reply_tokens = 2048  # NEXE_MLX_MAX_TOKENS / num_predict defaults
        assert budget_tokens + default_reply_tokens <= window, (
            f"window {window}: a prompt at the full budget leaves less than the "
            "default reply budget — the answer gets truncated silently"
        )


class TestTheEnvExampleValuesAreActuallySafe:
    """.env.example is used by uncommenting lines ONE AT A TIME. A previous
    example value (NEXE_MAX_CONTEXT_CHARS=20000) was 'safer-looking' than the
    24000 it replaced and yet, alone at the promised 8192-token window, left
    available_chars at -144 — RAG and documents silently dropped, the exact
    regression this whole branch exists to kill. These tests read the REAL file,
    so the next 'safer' example has to get past them."""

    WINDOW = 8192  # the file says: "The examples below assume a window of 8192+ tokens"

    @staticmethod
    def _example_value(var: str) -> int:
        import re
        from pathlib import Path

        # Search upwards for the file instead of counting parents: this test
        # moved one level up with F-D block 4 (tests/plugins/web_ui_module/ ->
        # tests/core/) and parents[3] silently became worktrees/, one above the
        # repo. Same class of breakage as #988 — locating a repo file by depth
        # ties the test to where it happens to sit.
        root = next(
            (p for p in Path(__file__).resolve().parents if (p / ".env.example").is_file()),
            None,
        )
        assert root is not None, "could not find .env.example above this test"
        text = (root / ".env.example").read_text(encoding="utf-8")
        # [ \t] and not \s: \s crosses newlines and a lone '#' line above a
        # genuinely uncommented value made the regex match the WRONG line. The
        # optional '#' means the test keeps finding the value if someone
        # uncomments it for real.
        m = re.search(rf"^#?[ \t]*{var}=(\d+)", text, re.M)
        assert m, f"{var} must appear (commented or not) in .env.example"
        return int(m.group(1))

    def _budget_with(self, max_chars: int, history_chars: int) -> dict:
        return compute_context_budget(
            max_context_chars=max_chars,
            system_chars=REAL_SYSTEM_PROMPT_CHARS,
            history_chars=history_chars,
            message_chars=200,
            document_chars=50_000,
        )

    def test_the_budget_example_alone_leaves_room_for_context(self) -> None:
        max_chars = self._example_value("NEXE_MAX_CONTEXT_CHARS")
        threshold_chars = int(self.WINDOW * ChatSession.COMPACT_AT_RATIO) * CHARS_PER_TOKEN_ESTIMATE
        budget = self._budget_with(max_chars, history_chars=threshold_chars)
        assert budget["available_chars"] > 0, (
            f"NEXE_MAX_CONTEXT_CHARS={max_chars} alone (default 45% threshold) leaves "
            f"{budget['available_chars']} chars at the window the file promises"
        )

    def test_the_threshold_example_alone_leaves_room_for_context(self) -> None:
        threshold = self._example_value("NEXE_COMPACT_AT_TOKENS")
        default_budget = int(self.WINDOW * CHARS_PER_TOKEN_ESTIMATE * PROMPT_BUDGET_RATIO)
        budget = self._budget_with(default_budget, history_chars=threshold * CHARS_PER_TOKEN_ESTIMATE)
        assert budget["available_chars"] > 0

    @pytest.mark.parametrize("window", [8192, 16384, 32768, 65536])
    def test_both_examples_together_are_safe_at_any_window(self, window) -> None:
        """The file promises the PAIR is "safe together at any window" — a fixed
        threshold with a fixed budget decouples both from the engine, so this
        must hold on every rung, not just the one the examples were sized for."""
        max_chars = self._example_value("NEXE_MAX_CONTEXT_CHARS")
        threshold = self._example_value("NEXE_COMPACT_AT_TOKENS")
        history_chars = threshold * CHARS_PER_TOKEN_ESTIMATE
        budget = self._budget_with(max_chars, history_chars=history_chars)
        assert budget["available_chars"] > 0
        prompt_chars = REAL_SYSTEM_PROMPT_CHARS + history_chars + 200 + budget["doc_kept_chars"]
        assert prompt_chars <= window * CHARS_PER_TOKEN_ESTIMATE, (
            f"window {window}: the documented pair must assemble a prompt that fits"
        )


class TestBadOperatorInputCannotWedgeTheChat:

    @pytest.mark.parametrize("bogus", ["0", "-1"])
    def test_a_zero_compaction_threshold_is_refused(self, bogus, monkeypatch) -> None:
        """0 would mean compacting on every turn — a full LLM summarisation in
        the critical path, ~100 s each, forever."""
        monkeypatch.setenv("NEXE_COMPACT_AT_TOKENS", bogus)
        assert ChatSession("t").compaction_threshold_tokens(8192) > 0

    @pytest.mark.parametrize("bogus", ["0", "-1"])
    def test_a_zero_context_budget_is_refused(self, bogus, monkeypatch) -> None:
        """0 would zero out the whole budget: no RAG, no documents, ever."""
        monkeypatch.setenv("NEXE_MAX_CONTEXT_CHARS", bogus)
        assert resolve_max_context_chars(_Engine(8192)) > 0
