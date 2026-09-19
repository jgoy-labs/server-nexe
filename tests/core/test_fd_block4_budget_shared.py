"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Description: Gate for F-D block 4 — both doors budget a turn with one arithmetic.

    Before this block, /v1/chat/completions had no turn budget at all: it
    capped only the retrieved context, at a flat 30% of the window, and never
    reserved anything for the history — so an oversized history shipped to the
    engine untouched while the retrieved context took the blame. /ui/chat used
    compute_context_budget from inside the web UI plugin, where the core could
    not reach it.

    Two things are pinned here:
      (1) parity of the ARITHMETIC — the same window yields the same budget
          through either door, and /v1's trim really is the shared function and
          not a lookalike. The two doors do NOT budget identically: /v1 passes
          history_ratio=0 (no attached documents to guard against) and drops
          the context when the budget is spent, where /ui/chat keeps its floor
          and truncates;
      (2) #977 — NEXE_HISTORY_CONTEXT_RATIO, the third ratio of the same
          arithmetic, now has the guard its siblings have.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from core.context_budget import (
    PROMPT_BUDGET_RATIO,
    compute_context_budget,
    resolve_history_ratio,
    resolve_max_context_chars,
)
from core.endpoints.chat import _inject_rag_context_into_messages, _trim_rag_context
from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE


def _engine(window):
    mod = MagicMock()
    mod.get_context_window.return_value = window
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("NEXE_MAX_CONTEXT_CHARS", raising=False)
    monkeypatch.delenv("NEXE_HISTORY_CONTEXT_RATIO", raising=False)
    # The tests below that drive the real endpoint need the same isolation the
    # sibling F-C tests already set up: a model name left in the environment by
    # an earlier test makes engine resolution answer 404, and the rate limiter
    # is process-global. Isolated this file passed; the full suite did not.
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    monkeypatch.delenv("NEXE_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
    from core.dependencies import limiter as _limiter

    _was_enabled = _limiter.enabled
    _limiter.enabled = False
    yield
    _limiter.enabled = _was_enabled


class TestBothDoorsShareTheBudgetArithmetic:

    @pytest.mark.parametrize("window", [2048, 4096, 8192, 32768])
    def test_same_window_same_budget(self, window) -> None:
        """The UI asks the engine; /v1 hands in the window it already resolved.
        Both must land on the same number — one formula, entered twice."""
        assert resolve_max_context_chars(_engine(window)) == resolve_max_context_chars(
            window_tokens=window
        )

    def test_the_operator_override_still_wins_on_both(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_MAX_CONTEXT_CHARS", "12345")
        assert resolve_max_context_chars(_engine(32768)) == 12345
        assert resolve_max_context_chars(window_tokens=32768) == 12345

    def test_v1_trims_rag_to_exactly_the_shared_budget(self) -> None:
        """/v1's trim is the shared arithmetic, not a second one that happens
        to look similar: the cut lands on compute_context_budget's own number."""
        window = 8192
        system, history, message = "S" * 4000, "H" * 3000, "M" * 200
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": history},
            {"role": "user", "content": message},
        ]
        expected = compute_context_budget(
            max_context_chars=resolve_max_context_chars(window_tokens=window),
            system_chars=len(system),
            history_chars=len(history),
            message_chars=len(message),
            document_chars=0,
            history_ratio=0.0,
            response_buffer=500,
        )["available_chars"]

        trimmed = _trim_rag_context("R" * 100_000, messages, window)
        assert len(trimmed) == expected

    # A marker that appears in no prose the assembler adds. The previous
    # version counted "R" and the counts came out one high, because the
    # Catalan notice contains SEGURETAT — so every expected value was welded
    # to a word, and rewording it turned all seven red. The test asserts the
    # marker's absence first, so the day someone writes it into the wrapper
    # this fails loudly instead of drifting.
    MARK = "\u03a9"

    def _assembled(self, window, history, message, lang="ca"):
        """Drive the real entry point and return (retrieved chars, prompt chars).

        The door's own adapters are where production starts, and they are one
        step ABOVE _inject_rag_context_into_messages — the difference is the
        security rule, which is exactly what used to be left out of the budget.
        The earlier version of this test stopped at the injector and therefore
        could not see the bug this class exists to pin.

        C4.2: `_build_rag_and_system_prompt` was decomposed into the three
        steps it folded plus `budget`. Driving the adapter table is the same
        entry point, one abstraction up — and `_fetch_rag_context` is still the
        seam the fake retrieval is injected at, because the `recall` step calls
        it through the module.
        """
        import asyncio
        from unittest.mock import MagicMock, patch

        import core.endpoints.chat as chat_mod
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message
        from core.endpoints.chat_sanitization import _UNTRUSTED_INTRO, rag_security_rule
        from core.endpoints.chat_rag import _RAG_CONTEXT_LABELS

        for text in (_UNTRUSTED_INTRO[lang], rag_security_rule(lang),
                     _RAG_CONTEXT_LABELS[lang]["intro"]):
            assert self.MARK not in text, "the marker leaked into the assembler's own prose"

        # Split into turns of at most MAX_CHAT_INPUT_LENGTH: a single 20000-char
        # message is not a thing this endpoint accepts (Message.content caps at
        # 8000), and building one made the test fail on validation rather than
        # on the budget. Driving the real entry point surfaced that; the
        # synthetic dict lists the earlier version used never would have.
        from core.endpoints.chat_sanitization import MAX_CHAT_INPUT_LENGTH

        msgs = []
        _left = history
        while _left > 0:
            _chunk = min(_left, MAX_CHAT_INPUT_LENGTH)
            msgs.append(Message(role="user", content="H" * _chunk))
            _left -= _chunk
        msgs.append(Message(role="user", content="M" * message))
        body = ChatCompletionRequest(messages=msgs, use_rag=True)
        state = MagicMock()
        state.config = {"personality": {"prompt": {f"{lang}_full": "S" * 4700}}}

        # `**_kw`: stands in for `_fetch_rag_context`; see the note in
        # tests/fixos/test_B263.py — a double must not pin a signature it
        # does not own.
        async def _found(_body, _state, _lang, **_kw):
            return self.MARK * 200_000, [("nexe_documentation", 0.9)]

        async def _run():
            from fastapi import BackgroundTasks

            from core.turn.adapters_api import api_adapters
            from core.turn.context import TurnContext

            ctx = TurnContext(
                turn_id="t", entry="api", body=body, app_state=state,
                lang=lang, context_window=window,
            )
            ctx.message = body.messages[-1].content
            table = api_adapters(BackgroundTasks())
            with patch.object(chat_mod, "_fetch_rag_context", _found):
                for step in ("recall", "clock", "system_prompt", "budget"):
                    await table[step](ctx)
            return ctx.prompt

        assembled = asyncio.run(_run())
        return (sum(m["content"].count(self.MARK) for m in assembled),
                sum(len(m["content"]) for m in assembled))

    @pytest.mark.parametrize("window,history,message", [
        (2048, 0, 50), (4096, 0, 50), (8192, 0, 50),
        (8192, 2000, 200), (8192, 0, 8000), (32768, 0, 50), (32768, 20000, 200),
    ])
    def test_the_assembled_prompt_stays_inside_the_budget(self, window, history, message) -> None:
        """The invariant, asserted where it can actually be broken.

        Not a table of expected counts. Hardcoded counts pinned
        ``max(4000, window x 0.3 x 4)`` — a constant this work never touched —
        in five of seven rows, so they stayed green with the turn budget
        deleted outright, and every one of them was welded to a word in the
        Catalan notice. What the budget promises is a relationship, so that is
        what is checked.

        ``WRAPPER_SLACK`` is the one documented exception: the budget bounds
        the retrieved PAYLOAD, and the delimiters plus the assistant ack turn
        that carry it are not counted (#999). It is deliberately tight — a
        regression that stops honouring the budget blows straight past it.
        """
        WRAPPER_SLACK = 600
        retrieved, prompt = self._assembled(window, history, message)
        budget = resolve_max_context_chars(window_tokens=window)
        assert prompt <= budget + WRAPPER_SLACK, (
            f"window={window} history={history} message={message}: assembled prompt "
            f"{prompt} chars against a {budget}-char budget ({retrieved} retrieved)"
        )

    @pytest.mark.parametrize("window", [2048, 4096, 8192, 32768])
    def test_the_retrieved_context_never_beats_the_shared_ceiling(self, window) -> None:
        """The 30% ceiling of _sanitize_rag_context was never removed by this
        block and still binds first on both routes. Said in a commit message
        that it HAD been removed once; asserting it here instead."""
        from core.endpoints.chat_sanitization import (
            CHARS_PER_TOKEN_ESTIMATE, MAX_CONTEXT_RATIO, MAX_RAG_CONTEXT_LENGTH,
        )

        ceiling = max(MAX_RAG_CONTEXT_LENGTH,
                      int(window * MAX_CONTEXT_RATIO * CHARS_PER_TOKEN_ESTIMATE))
        retrieved, _ = self._assembled(window, 0, 50)
        assert retrieved <= ceiling, f"window={window}: {retrieved} > ceiling {ceiling}"

    def test_a_bigger_window_never_retrieves_less(self) -> None:
        """Monotonicity: the whole point of sizing from the live engine."""
        counts = [self._assembled(w, 0, 50)[0] for w in (2048, 4096, 8192, 32768)]
        assert counts == sorted(counts), f"not monotonic across windows: {counts}"

    def test_a_window_too_small_drops_the_context_instead_of_overrunning(self) -> None:
        """The degradation ADR-006 asks for: on an engine whose window the
        system prompt nearly fills, the turn goes out without retrieved
        context rather than with context and over budget."""
        retrieved, prompt = self._assembled(2048, 0, 50)
        budget = resolve_max_context_chars(window_tokens=2048)
        assert retrieved == 0
        assert prompt <= budget

    def test_a_turn_that_does_not_fit_drops_its_context(self) -> None:
        """The other side of the same coin, and the point of the block: when
        the history alone overruns the budget, the context goes rather than
        riding on top of a prompt that already does not fit."""
        messages = [
            {"role": "system", "content": "S" * 4700},
            {"role": "user", "content": "H" * 40_000},
            {"role": "user", "content": "i ara?"},
        ]
        before = len(messages)
        _inject_rag_context_into_messages(messages, "R" * 5000, "ca", 8192)
        assert len(messages) == before

    def test_v1_drops_the_context_and_says_so_when_the_budget_is_gone(self, caplog) -> None:
        """#965's lesson: silent context loss is the bug. The old code cut to a
        magic 1000 chars here and logged a line about tokens; now the context
        is dropped and the reason is named, same as the UI route does."""
        messages = [
            {"role": "system", "content": "S" * 4000},
            {"role": "user", "content": "H" * 60_000},
            {"role": "user", "content": "i ara?"},
        ]
        with caplog.at_level(logging.WARNING, logger="core.endpoints.chat"):
            trimmed = _trim_rag_context("R" * 5000, messages, 8192)
        assert trimmed == ""
        assert any("budget exhausted" in r.message for r in caplog.records)

    def test_an_exhausted_budget_injects_no_empty_context_block(self) -> None:
        """The trim can now come back empty, which it never could before. The
        caller must then inject nothing at all — an empty turn pair would tell
        the model "use this retrieved information:" and show it nothing, and
        cost a prefix-cache miss to do it."""
        from core.endpoints.chat import _inject_rag_context_into_messages

        messages = [
            {"role": "system", "content": "S" * 4000},
            {"role": "user", "content": "H" * 60_000},
            {"role": "user", "content": "i ara?"},
        ]
        before = len(messages)
        _inject_rag_context_into_messages(messages, "R" * 5000, "ca", 8192)
        assert len(messages) == before, "no turn pair may be injected with nothing to put in it"

    def test_a_bigger_window_leaves_more_room_on_v1(self) -> None:
        messages = [
            {"role": "system", "content": "S" * 4000},
            {"role": "user", "content": "hola"},
        ]
        assert len(_trim_rag_context("R" * 200_000, messages, 4096)) < len(
            _trim_rag_context("R" * 200_000, messages, 8192)
        )


class TestTheRagStatusTellsTheTruth:
    """`X-Nexe-RAG-Status` / `nexe_rag_status` says whether the model was GIVEN
    retrieved context, not whether retrieval found any.

    The two only came apart with F-D block 4: before it, the trim always kept
    at least a slice, so "retrieved something" implied "injected something".
    Now a turn whose budget is spent drops the context entirely, and a server
    that still answers "active" is telling the client the model saw sources it
    never saw.
    """

    def _post(self, client, messages):
        return client.post(
            "/chat/completions",
            json={"messages": messages, "engine": "ollama", "stream": False, "use_rag": True},
            headers={"X-Api-Key": "test-fc-key", "Content-Type": "application/json"},
        )

    def _app(self):
        from tests.core.endpoints.test_fc_thread_mirror import _make_app
        from core.sessions import SessionManager
        import tempfile

        return _make_app(SessionManager(storage_path=tempfile.mkdtemp(), crypto_provider=None))

    def test_status_is_inactive_when_the_context_was_dropped(self, monkeypatch) -> None:
        from fastapi.testclient import TestClient
        from tests.core.endpoints.test_fc_thread_mirror import _OllamaCapture

        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-fc-key")
        monkeypatch.setenv("NEXE_ADMIN_API_KEY", "test-fc-key")

        async def _found_plenty(body, app_state, server_lang, **_kw):
            return "R" * 5000, [("nexe_documentation", 0.9)]

        monkeypatch.setattr("core.endpoints.chat._fetch_rag_context", _found_plenty)
        client = TestClient(self._app(), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok")):
            r = self._post(client, [
                {"role": "user", "content": "H" * 8000},
                {"role": "user", "content": "H" * 8000},
                {"role": "user", "content": "H" * 8000},
                {"role": "user", "content": "i ara?"},
            ])
        assert r.status_code == 200
        assert r.json().get("nexe_rag_status") == "inactive", (
            "retrieval found 5000 chars and the budget dropped every one of them; "
            "reporting 'active' claims the model saw sources it never saw"
        )

    def test_the_streaming_path_reports_it_too(self, monkeypatch) -> None:
        """Streaming carries the same answer in a header instead of the body.

        Four reviews of this work all drove `stream: False`, and every client
        that matters (LangChain, Open WebUI, aider, Continue) defaults to
        streaming — so the path nobody checked is the one nearly everybody
        uses.
        """
        from fastapi.testclient import TestClient
        from tests.core.endpoints.test_fc_thread_mirror import _OllamaCapture

        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-fc-key")
        monkeypatch.setenv("NEXE_ADMIN_API_KEY", "test-fc-key")

        async def _found_plenty(body, app_state, server_lang, **_kw):
            return "R" * 5000, [("nexe_documentation", 0.9)]

        monkeypatch.setattr("core.endpoints.chat._fetch_rag_context", _found_plenty)
        client = TestClient(self._app(), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok")):
            r = client.post(
                "/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "H" * 8000},
                        {"role": "user", "content": "H" * 8000},
                        {"role": "user", "content": "H" * 8000},
                        {"role": "user", "content": "i ara?"},
                    ],
                    "engine": "ollama", "stream": True, "use_rag": True,
                },
                headers={"X-Api-Key": "test-fc-key", "Content-Type": "application/json"},
            )
        assert r.status_code == 200
        assert r.headers.get("x-nexe-rag-status") == "inactive"

    def test_status_is_active_when_the_context_really_went_in(self, monkeypatch) -> None:
        from fastapi.testclient import TestClient
        from tests.core.endpoints.test_fc_thread_mirror import _OllamaCapture

        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-fc-key")
        monkeypatch.setenv("NEXE_ADMIN_API_KEY", "test-fc-key")

        async def _found_a_little(body, app_state, server_lang, **_kw):
            return "un fet recuperat", [("nexe_documentation", 0.9)]

        monkeypatch.setattr("core.endpoints.chat._fetch_rag_context", _found_a_little)
        client = TestClient(self._app(), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok")):
            r = self._post(client, [{"role": "user", "content": "hola"}])
        assert r.status_code == 200
        assert r.json().get("nexe_rag_status") == "active"


class TestHistoryRatioGuard:
    """#977 — the third ratio of the same arithmetic.

    It was read with a bare float() in a try/except ValueError, which caught
    "abc" and nothing else. nan and inf parse fine, and compute_context_budget's
    clamp (max(0.0, min(0.9, r))) then turns nan into 0.9 — the most aggressive
    setting there is. At the default 8192 window, 0.9 leaves available_chars
    negative with an EMPTY conversation: every turn silently loses its retrieved
    context and attached document.
    """

    def test_the_default_is_thirty_percent(self) -> None:
        assert resolve_history_ratio() == 0.30

    @pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "molt", "", "-0.5", "0", "1.5"])
    def test_a_value_that_is_not_a_usable_ratio_falls_back(self, raw, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_HISTORY_CONTEXT_RATIO", raw)
        assert resolve_history_ratio() == 0.30

    def test_nan_no_longer_becomes_the_most_aggressive_setting(self, monkeypatch) -> None:
        """The concrete regression: nan used to reach the clamp and come out
        as 0.9, starving the turn on the default window."""
        monkeypatch.setenv("NEXE_HISTORY_CONTEXT_RATIO", "nan")
        budget = compute_context_budget(
            max_context_chars=int(8192 * CHARS_PER_TOKEN_ESTIMATE * PROMPT_BUDGET_RATIO),
            system_chars=4700,
            history_chars=0,
            message_chars=200,
            document_chars=0,
            history_ratio=resolve_history_ratio(),
            response_buffer=500,
        )
        assert budget["available_chars"] > 0, (
            "an empty conversation must still have room for retrieved context"
        )

    # 1.0 is deliberately NOT here: _ratio_env accepts it, compute_context_budget
    # then clamps it to 0.9, and at an 8192 window 0.9 leaves available_chars
    # negative with an empty conversation — the very symptom #977 reports. The
    # usable range is narrower than the guard's (0, 1]; filed, not widened here,
    # because _ratio_env is shared with NEXE_MAX_CONTEXT_RATIO.
    @pytest.mark.parametrize("raw,expected", [("0.5", 0.5), ("0.25", 0.25), ("0.6", 0.6)])
    def test_a_valid_ratio_is_honoured(self, raw, expected, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_HISTORY_CONTEXT_RATIO", raw)
        assert resolve_history_ratio() == expected

    def test_a_rejected_value_leaves_a_trace(self, caplog, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_HISTORY_CONTEXT_RATIO", "nan")
        with caplog.at_level(logging.WARNING, logger="core.endpoints.chat_sanitization"):
            resolve_history_ratio()
        assert any("NEXE_HISTORY_CONTEXT_RATIO" in r.message for r in caplog.records)
