"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Description: Gate for #976 — the assembled prompt fits the engine's window, at
    both doors.

    llama.cpp does not truncate an oversized prompt: it raises ("Requested
    tokens exceed context window", llama_cpp/llama.py) and the turn dies. MLX
    truncates inside its own plugin (truncate_messages_to_budget) and Ollama
    truncates server-side, so llama.cpp was the only engine with no enforcement
    anywhere — and the budget upstream cannot stand in for one.

    The sibling #965 gate asserts the ARITHMETIC: what compute_context_budget
    PLANS to keep. This asserts what comes OUT of the assembler, and at /v1 what
    the engine actually RECEIVES over the endpoint. The two can disagree, which
    is the whole reason this file exists: the budget knows nothing about the
    history the caller prepends afterwards, the on-demand clock line, or the
    untrusted-context wrapper that carries the retrieved text.

    Its own words, from the case this replaces (test_f965_budget_and_compaction
    _agree.py, the 2048 xfail): "No budget arithmetic fixes this — the real fix
    is enforcing prompt-fits-window at assembly time."

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.context_budget import PROMPT_FIT_MARGIN_TOKENS, fit_prompt_to_window
from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE

# Windows a real machine reports: 2048 is the 8 GB laptop the finding is about.
ENGINE_WINDOWS = [2048, 4096, 8192, 32768]


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    """The isolation its sibling F-C/F-D gates already needed.

    Isolated, this file passed; inside the full suite the two endpoint tests
    failed. Both causes are process-global and set by other files: a model name
    or engine left in the environment makes engine resolution answer 404, and
    the rate limiter on /chat/completions ("20/minute") has already been spent
    by the time this file runs.
    """
    for var in ("NEXE_MAX_CONTEXT_CHARS", "NEXE_HISTORY_CONTEXT_RATIO",
                "NEXE_MODEL_ENGINE", "NEXE_OLLAMA_MODEL", "NEXE_DEFAULT_MODEL"):
        monkeypatch.delenv(var, raising=False)

    from core.dependencies import limiter as _limiter

    _was_enabled = _limiter.enabled
    _limiter.enabled = False
    yield
    _limiter.enabled = _was_enabled


def _turns(*sizes):
    return [{"role": "user", "content": "H" * n} for n in sizes]


class TestTheSharedFunction:
    """The contract, copied from the MLX helper it mirrors."""

    def test_it_never_returns_zero_turns(self) -> None:
        kept, trimmed = fit_prompt_to_window("S" * 4700, _turns(60_000), 2048)
        assert len(kept) == 1
        assert trimmed

    def test_it_drops_the_oldest_and_keeps_the_newest(self) -> None:
        messages = [
            {"role": "user", "content": "OLD" * 2000},
            {"role": "assistant", "content": "MID" * 2000},
            {"role": "user", "content": "newest"},
        ]
        kept, trimmed = fit_prompt_to_window("S" * 100, messages, 2048)
        assert trimmed
        assert kept[-1]["content"] == "newest"
        assert len(kept) < len(messages)

    def test_a_message_is_never_cut_out_of_the_middle(self) -> None:
        """Whole turns go, oldest first: a kept turn is byte-identical to the
        one that came in. Cutting one in half breaks role alternation and the
        chat template."""
        messages = _turns(20_000, 20_000) + [{"role": "user", "content": "curt"}]
        kept, _ = fit_prompt_to_window("S" * 100, messages, 8192)
        for msg in kept:
            assert msg in messages

    def test_the_newest_turn_is_trimmed_rather_than_dropped(self) -> None:
        """A document pasted into the message itself. Dropping it would send no
        user turn at all; keeping it whole is the dead turn #976 is about."""
        kept, trimmed = fit_prompt_to_window("S" * 100, _turns(200_000), 4096)
        assert trimmed
        assert len(kept) == 1
        assert 0 < len(kept[0]["content"]) < 200_000

    def test_a_trimmed_user_turn_keeps_the_question_at_the_end(self) -> None:
        """The shape this path actually sees: a long text pasted with the
        question UNDERNEATH it. Keeping the first N chars throws the question
        away and the model answers nothing in particular — in silence."""
        text = "D" * 100_000 + "\n\nqui és el beneficiari?"
        kept, trimmed = fit_prompt_to_window("", [{"role": "user", "content": text}], 4096)
        assert trimmed
        assert "qui és el beneficiari?" in kept[0]["content"], (
            "the question was cut off the end of the turn being answered"
        )
        assert kept[0]["content"].startswith("DDD"), "the head of the text is gone too"

    def test_a_trimmed_assistant_turn_keeps_its_end(self) -> None:
        """Continue mode (FD-S6): the generation has to resume from where it
        stopped, so for an assistant turn it is the END that matters."""
        text = "A" * 100_000 + "PUNT-DE-representació"
        kept, _ = fit_prompt_to_window("", [{"role": "assistant", "content": text}], 4096)
        assert kept[0]["content"].endswith("PUNT-DE-representació")

    def test_a_prompt_that_already_fits_is_returned_untouched(self) -> None:
        messages = _turns(50, 50) + [{"role": "user", "content": "hola"}]
        kept, trimmed = fit_prompt_to_window("S" * 100, messages, 8192)
        assert kept == messages
        assert not trimmed

    def test_it_never_touches_what_it_was_given(self) -> None:
        """The turns it is handed come from the stored conversation. Trimming
        them in place would delete the user's history from disk to make one
        prompt fit — a permanent loss for a per-turn problem."""
        original = [
            {"role": "user", "content": "H" * 50_000},
            {"role": "user", "content": "X" * 30_000},
        ]
        snapshot = [dict(m) for m in original]
        kept, _ = fit_prompt_to_window("S" * 4700, original, 2048)
        assert original == snapshot, "the input turns were mutated"
        # Only the turn whose CONTENT changed has to be a copy. Passing an
        # untouched turn straight through is fine and is what the no-trim path
        # does; what would edit the conversation is writing the shortened text
        # into the dict that came in.
        assert all(k is not o for k in kept for o in original if k["content"] != o["content"]), (
            "the shortened text was written into the stored turn"
        )

    def test_an_oversized_reply_reserve_cannot_empty_the_prompt(self) -> None:
        """A /v1 client asking for max_tokens=8192 on a 2048-token engine is a
        client mistake, not a reason to ship an empty prompt."""
        messages = _turns(100) + [{"role": "user", "content": "hola"}]
        kept, _ = fit_prompt_to_window("S" * 100, messages, 2048, reply_budget_tokens=32_000)
        assert kept

    def test_the_system_prompt_alone_filling_the_window_is_said_out_loud(self, caplog) -> None:
        """No floor is invented here — the one that was tried
        (MIN_BUDGET_WINDOW_TOKENS) turned a degradation into a crash. The turn
        goes out unfitted and the log says why."""
        import logging

        with caplog.at_level(logging.ERROR, logger="core.context_budget"):
            kept, _ = fit_prompt_to_window("S" * 40_000, _turns(100, 100), 2048)
        assert len(kept) == 1
        assert any("leaves no room" in r.message for r in caplog.records)


def _assembled_ui(window: int, history_chars: int, system_chars: int = 4700):
    """Drive the UI assembler for real and return (system, messages).

    Not `inspect.getsource`: the two existing "it is wired in" tests for the
    sibling #965 assert that a substring appears in the function's source, which
    stays green if the call is there and wrong, and goes red if someone renames
    a variable. This calls the assembler and measures what it returns.
    """
    from core.turn.assemble import PromptParts
    from plugins.web_ui_module.api import routes_chat

    engine = MagicMock()
    engine.get_context_window.return_value = window
    session = MagicMock()
    session.messages = []

    system_prompt = "S" * system_chars
    # C4.2: the prompt's parts are `PromptParts` now — this used to be a second
    # `TurnContext` inside routes_chat, shadowing the turn's real envelope.
    turn = PromptParts(
        context_messages=[{"role": "user", "content": "H" * history_chars}] if history_chars else [],
        document_context="",
        rag_context="",
        rag_count=0,
        rag_items=[],
    )
    messages, _doc_pct = routes_chat._assemble_engine_messages(
        turn, system_prompt, "ca", "i ara?", session, False, engine,
    )
    return system_prompt, messages


class TestTheUiDoor:

    @pytest.mark.parametrize("window", ENGINE_WINDOWS)
    @pytest.mark.parametrize("history_chars", [0, 20_000, 200_000])
    def test_what_the_assembler_returns_fits_the_window(self, window, history_chars) -> None:
        system, messages = _assembled_ui(window, history_chars)
        prompt_chars = len(system) + sum(len(m["content"]) for m in messages)
        assert prompt_chars <= window * CHARS_PER_TOKEN_ESTIMATE, (
            f"window={window} history={history_chars}: the assembled prompt "
            f"({prompt_chars} chars) exceeds what the engine holds — llama.cpp "
            "answers that with a ValueError, not a truncation"
        )

    def test_the_user_turn_survives_a_history_that_does_not_fit(self) -> None:
        """Degrading means the conversation keeps working: the turn being
        answered is the last thing to go, never the first."""
        _system, messages = _assembled_ui(2048, history_chars=200_000)
        assert messages, "the prompt must never come back empty"
        assert messages[-1]["role"] == "user"
        assert "i ara?" in messages[-1]["content"]

    def test_a_conversation_at_compaction_size_fits(self) -> None:
        """The case the #965 gate could only mark xfail, now on the path that
        can actually enforce it. `compaction_threshold_tokens` is what the
        session allows the history to grow to before compacting."""
        from core.sessions.session_manager import ChatSession

        window = 2048
        history_chars = ChatSession("t").compaction_threshold_tokens(window) * CHARS_PER_TOKEN_ESTIMATE
        system, messages = _assembled_ui(window, history_chars)
        prompt_chars = len(system) + sum(len(m["content"]) for m in messages)
        assert prompt_chars <= window * CHARS_PER_TOKEN_ESTIMATE


class TestTheApiDoor:
    """Measured on what the engine RECEIVES, through the endpoint — the only
    place where a guard that is written but never called shows up as red."""

    def _app(self, window: int):
        import tempfile

        from core.sessions import SessionManager
        from tests.core.endpoints.test_fc_thread_mirror import _make_app

        app = _make_app(SessionManager(storage_path=tempfile.mkdtemp(), crypto_provider=None))
        app.state.modules["ollama_module"].get_context_window.return_value = window
        return app

    def _capture(self):
        from tests.core.endpoints.test_fc_thread_mirror import _OllamaCapture

        class _Recorder(_OllamaCapture):
            sent: list = []

            async def post(self, url, json=None, **kw):
                if json and "messages" in json:
                    _Recorder.sent = json["messages"]
                return await super().post(url, json=json, **kw)

        _Recorder.sent = []
        return _Recorder(reply="ok")

    @pytest.mark.parametrize("window", [2048, 8192])
    def test_what_reaches_the_engine_fits_the_window(self, window, monkeypatch) -> None:
        from fastapi.testclient import TestClient

        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-f976-key")
        monkeypatch.setenv("NEXE_ADMIN_API_KEY", "test-f976-key")

        async def _no_rag(body, app_state, server_lang):
            return "", []

        monkeypatch.setattr("core.endpoints.chat._fetch_rag_context", _no_rag)

        recorder = self._capture()
        client = TestClient(self._app(window), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=recorder):
            resp = client.post(
                "/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "H" * 8000} for _ in range(6)]
                    + [{"role": "user", "content": "i ara?"}],
                    "engine": "ollama",
                    "stream": False,
                },
                headers={"X-Api-Key": "test-f976-key", "Content-Type": "application/json"},
            )

        assert resp.status_code == 200
        sent = type(recorder).sent
        assert sent, "the engine was never called — this gate would pass on nothing"
        prompt_chars = sum(len(m.get("content") or "") for m in sent)
        assert prompt_chars <= window * CHARS_PER_TOKEN_ESTIMATE, (
            f"window={window}: /v1 sent the engine {prompt_chars} chars"
        )
        assert sent[-1]["role"] == "user" and "i ara?" in sent[-1]["content"]


class TestBothDoorsUseTheSameFunction:
    """Not "the shared function agrees with itself" — the first version of this
    class called fit_prompt_to_window twice with identical arguments and
    compared the two results, which is true of any pure function and says
    nothing about either door. These drive the two REAL call sites."""

    SYSTEM = "S" * 4700
    MESSAGE = "i ara?"
    # The UI hands the guard the same 500-char reply reserve it gives the turn
    # budget; /v1 hands it the client's max_tokens. Same number here, so any
    # difference in what they keep is a difference in the doors, not in the ask.
    REPLY_TOKENS = 500 // CHARS_PER_TOKEN_ESTIMATE

    def _both(self, window, history_chars):
        from core.endpoints.chat import _fit_v1_messages_to_window

        # Built exactly as _assembled_ui builds it: no empty turn when there is
        # no history, or the two doors are being fed different conversations.
        history = [{"role": "user", "content": "H" * history_chars}] if history_chars else []
        ui_system, ui_kept = _assembled_ui(window, history_chars, len(self.SYSTEM))

        v1_in = (
            [{"role": "system", "content": ui_system}]
            + [dict(m) for m in history]
            + [{"role": "user", "content": self.MESSAGE}]
        )
        v1_kept = _fit_v1_messages_to_window(
            v1_in, window, SimpleNamespace(max_tokens=self.REPLY_TOKENS)
        )
        return ui_kept, [m for m in v1_kept if m["role"] != "system"]

    @pytest.mark.parametrize("window", ENGINE_WINDOWS)
    @pytest.mark.parametrize("history_chars", [0, 20_000, 200_000])
    def test_the_two_doors_keep_the_same_turns(self, window, history_chars) -> None:
        ui_kept, v1_kept = self._both(window, history_chars)
        assert [len(m["content"]) for m in ui_kept] == [len(m["content"]) for m in v1_kept], (
            f"window={window} history={history_chars}: the same conversation "
            "survives differently depending on which door it came through"
        )

    def test_the_margin_scales_with_the_window(self) -> None:
        """A flat 256 tokens is 12% of a 2048-token window and 0.8% of a 32768
        one, while the error it covers — 4 chars/token undercounting Catalan and
        Spanish — is a percentage. Both apply; the bigger one wins."""
        from core.context_budget import PROMPT_FIT_MARGIN_RATIO

        for window in (2048, 8192, 32768):
            kept = fit_prompt_to_window("", _turns(1_000_000), window)[0][0]["content"]
            slack_tokens = window - len(kept) / CHARS_PER_TOKEN_ESTIMATE
            assert slack_tokens >= window * PROMPT_FIT_MARGIN_RATIO - 1, (
                f"window={window}: the guard left {slack_tokens:.0f} tokens of slack, "
                "not enough to absorb an estimate known to undercount"
            )
            assert slack_tokens >= PROMPT_FIT_MARGIN_TOKENS - 1, (
                f"window={window}: the flat floor from the MLX helper is not honoured"
            )
