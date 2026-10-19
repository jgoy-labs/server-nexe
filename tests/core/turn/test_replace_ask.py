"""pla-comportament-segons-mida-model, C: what a door asks at `emit`."""
from types import SimpleNamespace

import pytest

from core.turn import model_tier as mt
from core.turn import replace_ask
from core.turn.model_size import API, ModelSize


def _session():
    from core.sessions import ChatSession
    session = ChatSession(session_id="s1")
    session.add_message("assistant", "ok")
    session._pending_replace = {"old": "User is 45 years old", "new": "User is 46 years old"}
    return session


async def _ask(monkeypatch, size, session=None):
    async def fake(engine, model):
        return size
    monkeypatch.setattr(mt, "model_size", fake)
    monkeypatch.delenv("NEXE_ASSISTED_BELOW_B", raising=False)
    ctx = SimpleNamespace(usage={}, lang="en")
    return ctx, await replace_ask.question_for(ctx, session or _session(), "mlx", "m")


async def test_a_9b_is_asked_for(monkeypatch):
    ctx, q = await _ask(monkeypatch, ModelSize(9.65, None, "estimated"))
    assert "User is 46 years old" in q
    assert ctx.usage["model_tier"]["tier"] == mt.ASSISTED


async def test_an_api_is_asked_for_too_by_default(monkeypatch):
    ctx, q = await _ask(monkeypatch, API)
    assert "User is 46 years old" in q and ctx.usage["model_tier"]["tier"] == mt.ASSISTED


async def test_an_api_asks_by_itself_when_a_cut_is_set(monkeypatch):
    monkeypatch.setattr(mt, "DEFAULT_BELOW_B", 30.0)
    ctx, q = await _ask(monkeypatch, API)
    assert q == "" and ctx.usage["model_tier"]["tier"] == mt.AUTONOMOUS


async def test_the_tier_is_worked_out_even_with_nothing_waiting(monkeypatch):
    s = _session()
    s._pending_replace = None
    ctx, q = await _ask(monkeypatch, ModelSize(9.65, None, "estimated"), s)
    assert q == "" and "model_tier" in ctx.usage


# ───────────────────────── the doors ─────────────────────────
import pytest as _pytest  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from core.endpoints.chat import chat_completions  # noqa: E402,F401 — breaks a circular import
from core.turn.adapters_api import api_adapters  # noqa: E402
from core.turn.context import TurnContext  # noqa: E402
from plugins.web_ui_module.api.turn_adapters import ui_adapters  # noqa: E402


@_pytest.fixture
def nine_b(monkeypatch):
    async def fake(engine, model):
        return ModelSize(9.65, None, "estimated")
    monkeypatch.setattr(mt, "model_size", fake)
    monkeypatch.delenv("NEXE_ASSISTED_BELOW_B", raising=False)


@_pytest.fixture
def cloud(monkeypatch):
    async def fake(engine, model):
        return API
    monkeypatch.setattr(mt, "model_size", fake)
    monkeypatch.setattr(mt, "DEFAULT_BELOW_B", 30.0)


def _v1_ctx(streaming):
    from fastapi.background import BackgroundTasks  # noqa: F401
    from starlette.datastructures import State

    session = _session()
    mgr = MagicMock()
    mgr.get_or_create_session.return_value = session
    state = State()
    state.session_manager = mgr
    ctx = TurnContext(turn_id="t", entry="api", lang="en", engine="mlx", app_state=state)
    ctx.session_id = "s1"
    ctx.usage["served_model"] = "Qwen3.5-9B-MLX-4bit"
    ctx.response = "Got it."
    ctx.wire = None if streaming else {"choices": [{"message": {"role": "assistant", "content": "Got it."}}]}
    return ctx, session, mgr


async def _drain(gen):
    return [chunk async for chunk in gen]


class TestV1Door:
    async def test_json_reply_ends_with_the_servers_question(self, nine_b):
        from fastapi import BackgroundTasks
        ctx, session, mgr = _v1_ctx(streaming=False)
        await api_adapters(BackgroundTasks())["emit"](ctx)
        content = ctx.wire["choices"][0]["message"]["content"]
        assert content.startswith("Got it.\n\n") and "User is 46 years old" in content
        mgr._save_session_to_disk.assert_called_once_with(session)
        assert session._pending_replace["old"] == "User is 45 years old", "armed, not carried out"

    async def test_json_reply_of_an_autonomous_model_is_untouched(self, cloud):
        from fastapi import BackgroundTasks
        ctx, session, mgr = _v1_ctx(streaming=False)
        await api_adapters(BackgroundTasks())["emit"](ctx)
        assert ctx.wire["choices"][0]["message"]["content"] == "Got it."
        mgr._save_session_to_disk.assert_not_called()

    async def test_stream_gets_the_question_before_done(self, nine_b):
        from fastapi import BackgroundTasks
        ctx, session, mgr = _v1_ctx(streaming=True)
        chunks = await _drain(api_adapters(BackgroundTasks(), streaming=True)["emit"](ctx))
        text = "".join(chunks)
        assert "User is 46 years old" in text
        assert text.index("User is 46 years old") < text.index("[DONE]")

    async def test_stream_of_an_autonomous_model_is_untouched(self, cloud):
        from fastapi import BackgroundTasks
        ctx, session, mgr = _v1_ctx(streaming=True)
        chunks = await _drain(api_adapters(BackgroundTasks(), streaming=True)["emit"](ctx))
        assert "User is 46 years old" not in "".join(chunks)

    async def test_a_memory_command_json_is_never_asked(self, nine_b):
        from fastapi import BackgroundTasks
        ctx, session, mgr = _v1_ctx(streaming=False)
        ctx.outcomes["generate"] = "skipped"
        await api_adapters(BackgroundTasks())["emit"](ctx)
        assert ctx.wire["choices"][0]["message"]["content"] == "Got it."

    async def test_a_memory_command_is_never_asked(self, nine_b):
        from fastapi import BackgroundTasks
        ctx, session, mgr = _v1_ctx(streaming=True)
        ctx.outcomes["generate"] = "skipped"
        chunks = await _drain(api_adapters(BackgroundTasks(), streaming=True)["emit"](ctx))
        assert "User is 46 years old" not in "".join(chunks)


def _ui_ctx(session, mgr, *, engine_name="mlx"):
    from types import SimpleNamespace as NS
    ctx = TurnContext(turn_id="t", entry="ui", lang="en", engine=None, app_state=MagicMock())
    ctx.app_state.config = {}
    ctx.session = session
    ctx.session_id = "s1"
    ctx.response = "Got it."
    ctx.usage["ui"] = {
        "engine_name": engine_name, "model_name": "Qwen3.5-9B-MLX-4bit",
        "memory_action": None,
        "stream_ctx": NS(session=session, engine=None, model_name="Qwen3.5-9B-MLX-4bit"),
    }
    return ctx


class TestWebDoor:
    async def test_json_reply_ends_with_the_servers_question(self, nine_b):
        session, mgr = _session(), MagicMock()
        ctx = _ui_ctx(session, mgr)
        await ui_adapters(mgr, streaming=False)["emit"](ctx)
        assert ctx.wire["response"].startswith("Got it.\n\n") and "User is 46 years old" in ctx.wire["response"]
        mgr._save_session_to_disk.assert_called_once_with(session)
        assert session._pending_replace["new"] == "User is 46 years old"

    async def test_json_reply_of_an_autonomous_model_is_untouched(self, cloud):
        session, mgr = _session(), MagicMock()
        ctx = _ui_ctx(session, mgr)
        await ui_adapters(mgr, streaming=False)["emit"](ctx)
        assert ctx.wire["response"] == "Got it."
        mgr._save_session_to_disk.assert_not_called()

    async def test_a_turn_no_engine_answered_is_never_asked(self, nine_b):
        session, mgr = _session(), MagicMock()
        ctx = _ui_ctx(session, mgr, engine_name="")
        await ui_adapters(mgr, streaming=False)["emit"](ctx)
        assert ctx.wire["response"] == "Got it."

    async def test_stream_carries_the_question_as_text(self, nine_b):
        session, mgr = _session(), MagicMock()
        ctx = _ui_ctx(session, mgr)
        chunks = await _drain(ui_adapters(mgr, streaming=True)["emit"](ctx))
        assert any("User is 46 years old" in c for c in chunks if not c.startswith("\x00"))
        mgr._save_session_to_disk.assert_called_with(session)

    async def test_stream_of_an_autonomous_model_is_untouched(self, cloud):
        session, mgr = _session(), MagicMock()
        ctx = _ui_ctx(session, mgr)
        chunks = await _drain(ui_adapters(mgr, streaming=True)["emit"](ctx))
        assert not any("User is 46 years old" in c for c in chunks)
