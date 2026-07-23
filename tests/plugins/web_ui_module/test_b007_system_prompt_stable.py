"""B007 — the system prompt must be stable within a day (prefix-cache poison).

The date phrase used to carry ``%H:%M:%S``: the system prompt (head of every
tokenized prompt) changed every second, so ``identity_hash`` and the token
prefix never matched — MLX trie/VLM state at ``cached=0`` forever, llama.cpp's
ModelPool reloading the GGUF every turn, Ollama's internal prefix cache dead.
Measured live (8 GB M1, 2026-07-23): prefill grew linearly 22s → 51s.

These tests pin the fix at DAY granularity and the on-demand clock
(``_time_context_line``), and guard against anyone reintroducing a
time-of-day inside the hashed/cacheable part.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from core.utils import compute_system_hash
from plugins.web_ui_module.api.routes_chat import (
    _build_system_prompt_with_time,
    _format_now_natural,
    _time_context_line,
)

# A timezone-aware anchor, mid-afternoon so +1h stays inside the same day.
T0 = datetime(2026, 7, 23, 13, 2, 1, tzinfo=timezone.utc)

# Any hh:mm-looking pattern (13:02, 9:41…). The date phrase must never match.
_TIME_OF_DAY_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


class TestDayGranularity:
    """T1 — the phrase is identical across seconds and hours of the same day."""

    @pytest.mark.parametrize("lang", ["ca", "es", "en"])
    def test_same_day_same_phrase(self, lang):
        p0 = _format_now_natural(T0, lang)
        p1 = _format_now_natural(T0 + timedelta(seconds=1), lang)
        p2 = _format_now_natural(T0 + timedelta(hours=3), lang)
        assert p0 == p1 == p2, (
            "the date phrase changed within the same day — the prefix cache "
            "can never hit again (B007)"
        )

    @pytest.mark.parametrize("lang", ["ca", "es", "en"])
    def test_no_time_of_day_in_phrase(self, lang):
        """Anti-regression guard: reintroducing hh:mm anywhere fails here."""
        phrase = _format_now_natural(T0, lang)
        assert not _TIME_OF_DAY_RE.search(phrase), (
            f"time-of-day leaked into the date phrase ({phrase!r}) — this is "
            "the exact B007 poison; the clock must go via _time_context_line"
        )

    def test_full_system_prompt_stable_and_clock_free(self):
        """The whole built system prompt: stable across seconds, no hh:mm."""
        s0, _ = _build_system_prompt_with_time("hola, com va?", _now=T0)
        s1, _ = _build_system_prompt_with_time(
            "hola, com va?", _now=T0 + timedelta(seconds=1)
        )
        assert s0 == s1
        assert compute_system_hash(s0) == compute_system_hash(s1)
        assert not _TIME_OF_DAY_RE.search(s0)


class TestLegitimateInvalidation:
    """T2/T3/T8 — the hash must STILL change for the legitimate reasons."""

    def test_day_rollover_changes_the_prompt(self):
        """T2 — one invalidation per day is the intended behaviour, not a bug."""
        s0, _ = _build_system_prompt_with_time("hola", _now=T0)
        s1, _ = _build_system_prompt_with_time("hola", _now=T0 + timedelta(days=1))
        assert s0 != s1
        assert compute_system_hash(s0) != compute_system_hash(s1)

    def test_language_change_is_a_legitimate_invalidation(self):
        """T8 — a different detected language really changes the prefix."""
        s_ca, lang_ca = _build_system_prompt_with_time(
            "hola, explica'm què pots fer per ajudar-me", _now=T0
        )
        s_en, lang_en = _build_system_prompt_with_time(
            "hello, please explain what you can do for me", _now=T0
        )
        if lang_ca == lang_en:  # lingua unavailable → both fall back
            pytest.skip("language detection unavailable in this environment")
        assert compute_system_hash(s_ca) != compute_system_hash(s_en)

    def test_identity_change_still_invalidates(self):
        """T3 — hashing stayed on the FULL system: editing it → new hash."""
        s0, _ = _build_system_prompt_with_time("hola", _now=T0)
        assert compute_system_hash(s0) != compute_system_hash(s0 + " [edited]")


class TestOnDemandClock:
    """D-A — the hour is read from the system only when the user asks it."""

    @pytest.mark.parametrize(
        ("lang", "message"),
        [
            ("ca", "quina hora és?"),
            ("ca", "Quina hora tenim ara mateix"),
            ("es", "¿qué hora es?"),
            ("es", "que hora es"),
            ("en", "what time is it?"),
            ("en", "What's the time now"),
        ],
    )
    def test_time_question_gets_the_clock(self, lang, message):
        line = _time_context_line(message, lang, _now=T0)
        assert "13:02" in line, f"no clock injected for {message!r}"

    @pytest.mark.parametrize(
        "message",
        [
            "hola, com va?",
            "explica'm la teoria de la relativitat",
            "what can you do?",
            "",
        ],
    )
    def test_normal_message_gets_no_clock(self, message):
        assert _time_context_line(message, "ca", _now=T0) == ""

    def test_unknown_language_falls_back_to_english(self):
        line = _time_context_line("what time is it?", "de", _now=T0)
        assert "13:02" in line and "Current system time" in line

    def test_clock_never_touches_the_system_prompt(self):
        """Even when the user asks the time, the SYSTEM prompt stays clean:
        the clock travels in the user turn (routes injection), never here."""
        s, _ = _build_system_prompt_with_time("quina hora és?", _now=T0)
        assert not _TIME_OF_DAY_RE.search(s)


class TestVlmKeyStability:
    """T6 — the VLM cache manager returns the SAME state for a stable key."""

    def test_same_system_same_state_object(self):
        from plugins.mlx_module.core.vlm_cache_manager import VLMPromptCacheManager

        mgr = VLMPromptCacheManager(max_sessions=1)
        if not mgr.available:
            pytest.skip("mlx_vlm PromptCacheState unavailable")
        s0, _ = _build_system_prompt_with_time("hola", _now=T0)
        s1, _ = _build_system_prompt_with_time(
            "hola", _now=T0 + timedelta(seconds=1)
        )
        key0 = f"/models/x:{compute_system_hash(s0)}:default"
        key1 = f"/models/x:{compute_system_hash(s1)}:default"
        assert key0 == key1, "key changed across seconds — B007 regressed"
        assert mgr.get_or_create(key0) is mgr.get_or_create(key1), (
            "a stable key must return the same PromptCacheState (no eviction)"
        )
