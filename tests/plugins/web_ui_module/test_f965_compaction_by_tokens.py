"""#965 — compaction is decided by size against the engine's real window.

The bug, in one line: `needs_compaction()` was an OR whose second branch —
`len(self.messages) >= COMPACT_EVERY`, ten messages, five turns — won every
single time, because ten short messages are ~50 chars and the size branch
compared against 12000. So a conversation of one-liners was summarised every
five turns on a machine whose model could hold 32768 tokens.

The size branch had no tests at all before this file: `MAX_CONTEXT_CHARS` and
`_estimate_context_chars` appeared nowhere under tests/.
"""
from __future__ import annotations

import pytest

from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE, DEFAULT_CONTEXT_WINDOW
from core.sessions import ChatSession


def _session_of(n_messages: int, chars_each: int = 8) -> ChatSession:
    s = ChatSession("t")
    for i in range(n_messages):
        s.add_message("user" if i % 2 == 0 else "assistant", "x" * chars_each)
    return s


def _session_costing(tokens: int) -> ChatSession:
    """A history of at least `tokens` estimated tokens, spread over enough
    messages that there is something to compact."""
    per_message = max(1, (tokens * CHARS_PER_TOKEN_ESTIMATE) // 10)
    return _session_of(10, chars_each=per_message)


class TestTheBugItself:

    @pytest.mark.parametrize("window", [4096, 8192, 32768, 65536])
    def test_five_turns_of_small_talk_never_compact(self, window, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        assert _session_of(10).needs_compaction(window) is False

    def test_it_is_not_the_message_count_any_more(self, monkeypatch) -> None:
        """Same message count, different sizes: only weight decides."""
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        light = _session_of(10, chars_each=8)
        heavy = _session_of(10, chars_each=20000)
        assert light.needs_compaction(8192) is False
        assert heavy.needs_compaction(8192) is True


class TestTheSameHistoryDecidesDifferentlyPerEngine:
    """The whole point: the window is the engine's, so the answer follows it."""

    def test_a_history_that_fits_a_big_model_but_not_a_small_one(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        s = _session_costing(10000)
        assert s.needs_compaction(4096) is True, "10k tokens do not fit a 4096 window"
        assert s.needs_compaction(32768) is False, "10k tokens fit a 32768 window comfortably"

    def test_a_bigger_window_never_compacts_sooner(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        s = _session_costing(6000)
        assert s.needs_compaction(4096) is True
        assert s.needs_compaction(65536) is False


class TestTheCryWolfGuard:
    """`compact_session` summarises `get_messages_to_compact()`, which is empty
    at or below COMPACT_KEEP. Answering True there would emit [WILL_COMPACT:1]
    on every turn and show "I am summarising the conversation" before a
    compaction that never happens."""

    def test_one_huge_message_does_not_claim_it_will_compact(self) -> None:
        s = ChatSession("doc")
        s.add_message("user", "x" * 500_000)
        assert s.needs_compaction(8192) is False

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
    def test_nothing_to_compact_means_no_warning(self, n) -> None:
        s = _session_of(n, chars_each=100_000)
        assert s.get_messages_to_compact() == []
        assert s.needs_compaction(8192) is False, (
            f"{n} messages: over the size threshold but nothing to compact — "
            "saying True here is crying wolf"
        )

    def test_one_message_past_the_keep_line_does_warn(self) -> None:
        s = _session_of(ChatSession.COMPACT_KEEP + 2, chars_each=100_000)
        assert s.get_messages_to_compact() != []
        assert s.needs_compaction(8192) is True


class TestTheThresholdAndItsOverride:

    def test_threshold_is_a_fraction_of_the_window(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        s = ChatSession("t")
        assert s.compaction_threshold_tokens(32768) == int(32768 * ChatSession.COMPACT_AT_RATIO)

    def test_the_threshold_leaves_room_for_the_answer(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        assert ChatSession("t").compaction_threshold_tokens(8192) < 8192

    def test_no_window_uses_the_documented_default(self, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        s = ChatSession("t")
        expected = int(DEFAULT_CONTEXT_WINDOW * ChatSession.COMPACT_AT_RATIO)
        assert s.compaction_threshold_tokens(None) == expected
        assert s.compaction_threshold_tokens(0) == expected

    def test_the_env_override_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_COMPACT_AT_TOKENS", "1000")
        assert ChatSession("t").compaction_threshold_tokens(65536) == 1000

    def test_a_bad_override_does_not_break_the_turn(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_COMPACT_AT_TOKENS", "not-a-number")
        assert ChatSession("t").compaction_threshold_tokens(8192) > 0


class TestTheHardGuardSurvives:

    def test_a_very_long_tail_of_tiny_messages_still_compacts(self, monkeypatch) -> None:
        """Each message costs almost nothing, so the size branch never fires —
        but 200 of them is still a history worth summarising."""
        monkeypatch.delenv("NEXE_COMPACT_AT_TOKENS", raising=False)
        s = _session_of(ChatSession.COMPACT_EVERY, chars_each=4)
        assert s._estimate_context_tokens() < s.compaction_threshold_tokens(32768)
        assert s.needs_compaction(32768) is True

    def test_the_guard_is_no_longer_five_turns(self) -> None:
        assert ChatSession.COMPACT_EVERY > 100, (
            "COMPACT_EVERY is a hard guard now; back near 10 and it is the trigger again"
        )
