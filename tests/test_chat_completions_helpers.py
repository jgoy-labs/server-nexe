"""Tests for the helper functions extracted from chat_completions."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import StreamingResponse

from core.endpoints.chat import (
    _dispatch_to_engine,
    _inject_response_headers,
    _record_engine_metrics,
    _validate_chat_request,
)
from core.endpoints.chat_schemas import ChatCompletionRequest, Message


async def _v1_prompt(body, app_state, lang="en", window=None):
    """What `/v1` assembles for the model, driven through its REAL adapters.

    C4.2: `_build_rag_and_system_prompt` no longer exists — the three steps it
    folded (`recall`, `clock`, `system_prompt`) run for themselves and `budget`
    puts the payload together. So this asks the door's own adapter table, which
    is the behaviour these tests were always about; patching or importing the
    old function would pin a shape instead.

    Returns (messages, injected_context) — the same pair the old helper did.
    """
    from fastapi import BackgroundTasks

    from core.turn.adapters_api import api_adapters
    from core.turn.context import TurnContext

    ctx = TurnContext(
        turn_id="t", entry="api", body=body, app_state=app_state,
        lang=lang, context_window=window,
    )
    ctx.message = next(
        (m.content for m in reversed(body.messages) if m.role == "user"), None
    ) or ""
    table = api_adapters(BackgroundTasks())
    for step in ("recall", "clock", "system_prompt", "budget"):
        await table[step](ctx)
    return ctx.prompt, ctx.recall_text


def _make_body(**kwargs):
    defaults = {
        "messages": [Message(role="user", content="hola")],
        "model": None,
        "engine": None,
        "use_rag": False,
    }
    defaults.update(kwargs)
    return ChatCompletionRequest(**defaults)


# ─── _validate_chat_request ──────────────────────────────────────────────────

class TestValidateChatRequest:
    def test_strips_model_field(self):
        body = _make_body(model="gpt-4")
        _validate_chat_request(body)
        assert body.model == "gpt-4"

    async def test_strips_memory_tags_from_user_content(self):
        """C4.1: the user's text is sanitized by the turn's `sanitize` step, not
        by `_validate_chat_request` — one chain for both doors
        (`core/turn/validate.py`). Run through this door's real adapter, so the
        test says what /v1 does rather than which function does it.
        """
        from fastapi import BackgroundTasks

        from core.turn.adapters_api import api_adapters
        from core.turn.context import TurnContext

        body = _make_body(messages=[Message(role="user", content="[MEM_SAVE: secret]\nhola")])
        ctx = TurnContext(turn_id="t", entry="api", body=body)
        await api_adapters(BackgroundTasks())["sanitize"](ctx)
        assert "MEM_SAVE" not in body.messages[0].content
        assert "hola" in body.messages[0].content

    def test_no_error_when_model_is_none(self):
        body = _make_body(model=None)
        _validate_chat_request(body)

    def test_no_error_with_assistant_message(self):
        body = _make_body(messages=[Message(role="assistant", content="hola")])
        _validate_chat_request(body)
        assert body.messages[0].content == "hola"


# ─── the /v1 door's prompt assembly (was _build_rag_and_system_prompt) ───────

class TestTheV1PromptAssembly:
    async def test_no_rag_injects_system_prompt(self):
        body = _make_body(use_rag=False)
        app_state = MagicMock()
        app_state.config = {}
        messages, context = await _v1_prompt(body, app_state)
        assert context == ""
        assert messages[0]["role"] == "system"

    async def test_existing_system_message_not_duplicated(self):
        body = _make_body(
            use_rag=False,
            messages=[
                Message(role="system", content="custom"),
                Message(role="user", content="hola"),
            ],
        )
        app_state = MagicMock()
        messages, context = await _v1_prompt(body, app_state)
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        # #851 (contracte actualitzat): el system custom es conserva PERÒ la
        # regla RAG estàtica s'arma INCONDICIONALMENT (abans només amb context
        # → el hash del system divergia entre torns i partia la caché de prefix).
        assert system_msgs[0]["content"].startswith("custom")
        from core.endpoints.chat_sanitization import _RAG_SECURITY_RULE

        assert system_msgs[0]["content"].endswith(_RAG_SECURITY_RULE["en"])
        assert system_msgs[0]["content"].count(_RAG_SECURITY_RULE["en"]) == 1, (
            "la regla no es pot duplicar"
        )

    async def test_rag_disabled_returns_empty_context(self):
        body = _make_body(use_rag=False)
        app_state = MagicMock()
        app_state.config = {}
        _, context = await _v1_prompt(body, app_state, lang="ca")
        assert context == ""

    async def test_rag_enabled_calls_build_rag_context(self):
        body = _make_body(use_rag=True, messages=[Message(role="user", content="query")])
        app_state = MagicMock()
        app_state.config = {}
        # Patched where retrieval really happens: the shared `recall` step
        # calls `core.endpoints.chat_rag.build_rag_context` by module (C4.2).
        with patch("core.endpoints.chat_rag.build_rag_context",
                   new=AsyncMock(return_value=("rag_text", []))) as mock_rag:
            messages, context = await _v1_prompt(body, app_state)
        mock_rag.assert_called_once()
        assert context == "rag_text"

    # ── F-D blocks 1-2: /v1 now shares the UI's date phrase + on-demand clock ──
    # (core/chat_prompt.py). Before this, /v1's system prompt had NEITHER —
    # an API conversation never knew today's date and could not answer "what
    # time is it". Drives the real endpoint helper, not a copy of the phrase.

    async def test_system_prompt_carries_the_date_phrase(self):
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch as _patch
        import datetime as _datetime_mod

        body = _make_body(use_rag=False)
        app_state = MagicMock()
        app_state.config = {}
        fixed = datetime(2026, 5, 21, 21, 52, 22, tzinfo=timezone(timedelta(hours=2)))
        mock_cls = MagicMock()
        mock_cls.now.return_value.astimezone.return_value = fixed
        with _patch.object(_datetime_mod, "datetime", mock_cls):
            messages, _ = await _v1_prompt(body, app_state, lang="ca")
        assert "dijous, 21 de maig de 2026" in messages[0]["content"], (
            "F-D: /v1's system prompt must carry the same natural-language "
            f"date phrase the UI has always had. Got: {messages[0]['content']!r}"
        )

    async def test_matches_the_ui_route_exactly(self):
        """Parity gate (F-D): /v1 and /ui/chat produce the byte-identical
        date phrase for the same language and instant, because both call
        the ONE shared core.chat_prompt — not two copies that can drift,
        the exact bug #854/B007 patterns exist to prevent."""
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch as _patch
        import datetime as _datetime_mod
        from core.turn.prompt import _build_system_prompt_with_time

        body = _make_body(use_rag=False)
        app_state = MagicMock()
        app_state.config = {}
        fixed = datetime(2026, 8, 27, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        mock_cls = MagicMock()
        mock_cls.now.return_value.astimezone.return_value = fixed

        with _patch.object(_datetime_mod, "datetime", mock_cls):
            v1_messages, _ = await _v1_prompt(body, app_state, lang="es")
            ui_prompt, _ = _build_system_prompt_with_time("hola", lang_hint="es")

        # Both start from a DIFFERENT base prompt (server.toml vs the English
        # fallback), so compare only the shared tail: date phrase onward.
        assert "Hoy es " in v1_messages[0]["content"]
        assert "Hoy es " in ui_prompt
        v1_date = v1_messages[0]["content"].split("Hoy es ", 1)[1]
        ui_date = ui_prompt.split("Hoy es ", 1)[1]
        assert v1_date.split("\n")[0] == ui_date.split("\n")[0]

    async def test_asking_the_time_injects_the_clock_into_the_turn_not_the_system(self):
        body = _make_body(use_rag=False, messages=[Message(role="user", content="quina hora és?")])
        app_state = MagicMock()
        app_state.config = {}
        messages, _ = await _v1_prompt(body, app_state, lang="ca")
        # #1125: every message carries the time it was sent, at both doors.
        assert messages[-1]["content"].startswith("[Hora del missatge: "), (
            "F-D: /v1 must give the model the time, like the UI — "
            f"got: {messages[-1]['content']!r}"
        )
        assert "Hora del missatge" not in messages[0]["content"], (
            "the clock must never poison the system prompt / prefix cache"
        )

    async def test_a_message_that_does_not_ask_still_gets_its_time(self):
        """#1125: a phrase decided before, and "hora es" without its accent
        found no clock. The time comes in front of the user's words, untouched."""
        body = _make_body(use_rag=False, messages=[Message(role="user", content="hola, com va?")])
        app_state = MagicMock()
        app_state.config = {}
        messages, _ = await _v1_prompt(body, app_state, lang="ca")
        assert messages[-1]["content"].startswith("[Hora del missatge: ")
        assert messages[-1]["content"].endswith("]\n\nhola, com va?")


# ─── _dispatch_to_engine ─────────────────────────────────────────────────────

class TestDispatchToEngine:
    async def test_ollama_path(self):
        body = _make_body()
        request = MagicMock()
        app_state = MagicMock()
        with patch("core.endpoints.chat._forward_to_ollama", new=AsyncMock(return_value={"ok": True})) as mock_ollama:
            result = await _dispatch_to_engine("ollama", [], body, request, app_state, "q")
        mock_ollama.assert_called_once()
        assert result == {"ok": True}

    async def test_unknown_engine_falls_back_to_ollama(self):
        body = _make_body()
        request = MagicMock()
        app_state = MagicMock()
        with patch("core.endpoints.chat._forward_to_ollama", new=AsyncMock(return_value={"fallback": True})) as mock_ollama:
            result = await _dispatch_to_engine("unknown_engine", [], body, request, app_state, "q")
        mock_ollama.assert_called_once()
        assert result == {"fallback": True}

    async def test_mlx_path(self):
        body = _make_body()
        request = MagicMock()
        app_state = MagicMock()
        with patch("core.endpoints.chat._forward_to_mlx", new=AsyncMock(return_value={"mlx": True})) as mock_mlx:
            result = await _dispatch_to_engine("mlx", [], body, request, app_state, None)
        mock_mlx.assert_called_once()
        assert result == {"mlx": True}


# ─── _record_engine_metrics ──────────────────────────────────────────────────

class TestRecordEngineMetrics:
    def test_does_not_raise_when_metrics_unavailable(self):
        with patch("builtins.__import__", side_effect=ImportError("no metrics")):
            _record_engine_metrics("ollama", "success", 0.0)

    def test_records_metrics_when_available(self):
        mock_requests = MagicMock()
        mock_duration = MagicMock()
        with patch.dict("sys.modules", {
            "core.metrics.registry": MagicMock(
                CHAT_ENGINE_REQUESTS=mock_requests,
                CHAT_ENGINE_DURATION=mock_duration,
            )
        }):
            _record_engine_metrics("ollama", "success", 0.0)
        mock_requests.labels.assert_called_once_with(engine="ollama", status="success")


# ─── _inject_response_headers ────────────────────────────────────────────────

class TestInjectResponseHeaders:
    def test_dict_response_gets_nexe_engine(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "", None)
        assert result["nexe_engine"] == "ollama"

    def test_dict_rag_active_when_context(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "some context", None)
        assert result["nexe_rag_status"] == "active"

    def test_dict_rag_inactive_when_no_context(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "", None)
        assert result["nexe_rag_status"] == "inactive"

    def test_dict_fallback_set_when_preferred(self):
        response = {}
        result = _inject_response_headers(response, "ollama", "", "mlx")
        assert "nexe_fallback" in result
        assert result["nexe_fallback"]["from"] == "mlx"

    def test_streaming_gets_engine_header(self):
        headers = {}
        response = MagicMock(spec=StreamingResponse)
        response.headers = headers
        _inject_response_headers(response, "ollama", "", None)
        assert headers.get("X-Nexe-Engine") == "ollama"
