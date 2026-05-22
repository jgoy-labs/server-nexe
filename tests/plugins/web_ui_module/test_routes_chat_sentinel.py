"""
────────────────────────────────────
Server Nexe — Anti-regression sentinels for plugins/web_ui_module/api/routes_chat.py

Bug A (2026-05-21 vespre tard, post-revert F5.5 UI duplicada):
  The /ui/chat endpoint is StreamingResponse(media_type="text/plain"),
  NOT text/event-stream. The frontend (plugins/web_ui_module/ui/app.js)
  detects end-of-stream via reader.read() returning {done: true} and has
  no SSE parser — yielding a literal 'data: [DONE]\\n\\n' leaks the string
  into the assistant's chat bubble verbatim. Introduced by commit e96bc28
  (2026-05-12), surfaced empirically by Jordi (2026-05-21) on DMG with
  gemma-4-31b-8bit.

  Fix: removed the yield 'data: [DONE]\\n\\n' at the end of
  response_generator(). This module owns the only client (/ui/chat) and
  has no contractual requirement to emit the SSE sentinel. The OpenAI-
  compatible endpoints (/v1/chat/completions for Ollama/MLX/llama.cpp)
  live under core/endpoints/chat_engines/ and are unaffected.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import inspect


class TestRoutesChatNoDoneSentinel:
    """Bug A regression sentinel — must not re-introduce 'data: [DONE]'.

    Rationale for static inspection: mocking response_generator end-to-end
    would require staging the full engine pipeline (session_manager,
    memory_helper, latex_sanitizer, three engine routers, RAG context).
    A grep-the-source sentinel is robust, refactor-friendly, and catches
    the literal regardless of how the function is internally restructured.
    """

    def test_module_source_does_not_contain_done_sentinel(self) -> None:
        from plugins.web_ui_module.api import routes_chat

        src = inspect.getsource(routes_chat)
        assert 'data: [DONE]' not in src, (
            "Bug A regression: routes_chat.py contains the literal "
            "'data: [DONE]'. The /ui/chat endpoint is text/plain and the "
            "frontend has no SSE parser — this sentinel must not be "
            "re-introduced. See commit history around 2026-05-21 for context."
        )

    def test_module_source_does_not_contain_yield_done(self) -> None:
        """Extra belt-and-braces: even if someone parameterises the string
        (e.g. via a constant), forbid the obvious 'yield ... DONE' pattern
        in this module specifically."""
        from plugins.web_ui_module.api import routes_chat

        src = inspect.getsource(routes_chat)
        # The '[DONE]' token in comments is fine; only forbid it as a
        # quoted string literal (single or double quotes).
        forbidden = ("'[DONE]'", '"[DONE]"')
        for needle in forbidden:
            assert needle not in src, (
                f"Bug A regression: routes_chat.py contains the literal "
                f"{needle!r}. The /ui/chat endpoint is text/plain and must "
                "not emit any [DONE] sentinel."
            )


class TestSystemPromptNaturalLanguageDate:
    """Bug B iter-2 regression sentinel — _build_system_prompt_with_time()
    must inject a natural-language date phrase in the user's language so
    small MLX models copy it verbatim (Qwen3-4B-4bit empirically returned
    date -1 with the iter-1 ``Now: Thursday 2026-05-21 ...`` technical
    header, interpreting it as metadata rather than a fact).

    Patches datetime.datetime at the module level so the function-local
    ``from datetime import datetime as _dt`` re-resolves to the mock.
    The try-block import of get_server_state is allowed to fail
    organically (the function falls back to the English Nexe boilerplate,
    which is fine for these substring assertions).
    """

    @staticmethod
    def _build_with_fixed_now(fixed_dt, lang_env=None, monkeypatch=None):
        from unittest.mock import patch, MagicMock
        import datetime as _datetime_mod
        from plugins.web_ui_module.api import routes_chat

        if monkeypatch is not None and lang_env is not None:
            monkeypatch.setenv("NEXE_LANG", lang_env)
        mock_cls = MagicMock()
        mock_cls.now.return_value.astimezone.return_value = fixed_dt
        with patch.object(_datetime_mod, "datetime", mock_cls):
            return routes_chat._build_system_prompt_with_time()

    def test_old_now_prefix_completely_removed(self) -> None:
        """The iter-1 'Now:' technical prefix must be absent from the prompt
        for any language — it confused small MLX models."""
        from datetime import datetime, timezone, timedelta
        fixed = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone(timedelta(hours=2), name="CEST"))
        prompt, _ = self._build_with_fixed_now(fixed)
        assert "Now:" not in prompt, (
            f"Bug B iter-2 regression: iter-1 'Now:' prefix still present. "
            f"Got: {prompt!r}"
        )

    def test_catalan_phrase_contains_localized_weekday_and_month(self, monkeypatch) -> None:
        from datetime import datetime, timezone, timedelta
        fixed = datetime(
            2026, 5, 21, 21, 52, 22,
            tzinfo=timezone(timedelta(hours=2), name="CEST"),
        )
        prompt, _ = self._build_with_fixed_now(fixed, "ca", monkeypatch)
        for needle in ("dijous", "21 de maig de 2026", "a les 21:52:22"):
            assert needle in prompt, (
                f"Bug B iter-2 regression (ca): missing {needle!r} in {prompt!r}"
            )

    def test_spanish_phrase_contains_localized_weekday_and_month(self, monkeypatch) -> None:
        from datetime import datetime, timezone, timedelta
        fixed = datetime(
            2026, 5, 21, 21, 52, 22,
            tzinfo=timezone(timedelta(hours=2), name="CEST"),
        )
        prompt, _ = self._build_with_fixed_now(fixed, "es", monkeypatch)
        for needle in ("jueves", "21 de mayo de 2026", "a las 21:52:22"):
            assert needle in prompt, (
                f"Bug B iter-2 regression (es): missing {needle!r} in {prompt!r}"
            )

    def test_english_phrase_contains_localized_weekday_and_month(self, monkeypatch) -> None:
        from datetime import datetime, timezone, timedelta
        fixed = datetime(
            2026, 5, 21, 21, 52, 22,
            tzinfo=timezone(timedelta(hours=2), name="CEST"),
        )
        prompt, _ = self._build_with_fixed_now(fixed, "en", monkeypatch)
        for needle in ("Today is Thursday", "May 21, 2026", "at 21:52:22"):
            assert needle in prompt, (
                f"Bug B iter-2 regression (en): missing {needle!r} in {prompt!r}"
            )

    def test_bcp47_regional_variant_normalised(self, monkeypatch) -> None:
        """``NEXE_LANG=ca-ES`` must resolve to Catalan (not the English
        fallback). Mirrors the .split("-")[0].lower() normalisation done
        elsewhere in the chat pipeline (RAG labels, image blocks)."""
        from datetime import datetime, timezone
        fixed = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
        prompt, _ = self._build_with_fixed_now(fixed, "ca-ES", monkeypatch)
        assert "dijous" in prompt, (
            f"Bug B iter-2: BCP-47 variant ca-ES must normalise to ca; "
            f"got: {prompt!r}"
        )

    def test_unknown_lang_falls_back_to_english(self, monkeypatch) -> None:
        from datetime import datetime, timezone
        fixed = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
        prompt, _ = self._build_with_fixed_now(fixed, "fr", monkeypatch)
        assert "Today is" in prompt, (
            f"Bug B iter-2: unknown lang 'fr' should fall back to English; "
            f"got: {prompt!r}"
        )

    def test_weekday_correct_across_full_week(self, monkeypatch) -> None:
        """Sweep Mon→Sun in English to catch any accidental off-by-one
        in ``_WEEKDAYS_BY_LANG`` indexing. Forces ``NEXE_LANG=en`` because
        the default fallback inside the function is ``ca``."""
        from datetime import datetime, timezone
        cases = [
            (datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc), "Monday"),
            (datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc), "Tuesday"),
            (datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc), "Wednesday"),
            (datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc), "Thursday"),
            (datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc), "Friday"),
            (datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc), "Saturday"),
            (datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc), "Sunday"),
        ]
        for fixed_dt, expected_day in cases:
            prompt, _ = self._build_with_fixed_now(fixed_dt, "en", monkeypatch)
            assert f"Today is {expected_day}" in prompt, (
                f"Bug B iter-2: expected 'Today is {expected_day}' for "
                f"{fixed_dt.date()}; got: {prompt!r}"
            )
