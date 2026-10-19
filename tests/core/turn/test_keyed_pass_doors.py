"""Review 19/10, finding 8: the keyed pass through the two doors' `memory.write`, switched ON."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.turn import keyed_pass

pytestmark = pytest.mark.asyncio

REPLY = json.dumps({"facts": [{"entity": "user", "attribute": "age", "value": "46",
                                "statement": "L'usuari té 46 anys", "intent": "change"}]})


class _Gate:
    async def acquire(self, *a, **k):
        return object()

    async def release(self, slot):
        pass


class _Engine:
    def __init__(self):
        self.calls = 0

    async def chat(self, model, messages, stream=True, thinking_enabled=False, response_schema=None):
        self.calls += 1
        yield {"message": {"content": REPLY}}


def _memory_helper():
    helper = MagicMock()
    memory = MagicMock()
    memory.collection_exists = AsyncMock(return_value=True)
    memory.scroll = AsyncMock(return_value=([], None))
    helper.get_memory_api = AsyncMock(return_value=memory)
    helper.save_to_memory = AsyncMock(return_value={"success": True, "document_id": "d"})
    return helper


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("NEXE_MEMORY_KEYED", "true")
    monkeypatch.setattr(keyed_pass, "gate_for", lambda app_state, engine=None: _Gate())


async def test_v1_reads_the_message_and_still_passes_the_tags_it_does_not_cover(on, monkeypatch):
    from core.endpoints.chat import chat_completions  # noqa: F401 (breaks a circular import)
    from core.turn.adapters_api import api_adapters
    from core.turn.context import TurnContext

    engine, helper = _Engine(), _memory_helper()
    session = MagicMock()
    session.id = "s-1"
    session.messages = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hey"},
                        {"role": "user", "content": "Ara tinc 46 anys"}]
    session._recently_deleted_facts = []
    state = SimpleNamespace(session_manager=MagicMock(), memory_helper=helper)
    state.session_manager.get_or_create_session.return_value = session
    monkeypatch.setattr("core.turn.adapters_api._engine_module_of", lambda ctx: engine)

    ctx = TurnContext(turn_id="t", entry="api")
    ctx.app_state, ctx.session_id, ctx.message, ctx.engine = state, "s-1", "Ara tinc 46 anys", "ollama"
    ctx.facts = ["L'usuari té 46 anys", "L'usuari treballa de fuster"]
    await api_adapters(MagicMock())["memory.write"](ctx)

    saved = [c.kwargs["content"] if c.kwargs else c.args[0] for c in helper.save_to_memory.await_args_list]
    assert "L'usuari té 46 anys" in saved and engine.calls == 1
    assert any("fuster" in text for text in saved), "the tag the extractor did not cover was dropped"
    assert ctx.usage["memory_saved"] == len(saved)
    assert any(c["step"] == "memory.write" for c in ctx.usage["llm"]["calls"])


async def test_the_web_door_writes_the_stats_of_what_the_pass_saved(on, monkeypatch):
    from plugins.web_ui_module.api import turn_adapters

    outcome = SimpleNamespace(handled=True, saved=1, kept=["L'usuari té 46 anys"], facts=["L'usuari té 46 anys"])

    async def fake_run(ctx, **kw):
        ctx.facts = []
        return outcome

    monkeypatch.setattr(keyed_pass, "run", fake_run)
    session = SimpleNamespace(messages=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "ok"}])
    mgr = MagicMock()
    ctx = SimpleNamespace(usage={}, facts=["x" * 6], resume=False, engine=object(), body={})
    got = await turn_adapters._keyed_memory(ctx, {"memory_helper": object()}, session, mgr)
    assert got is outcome and ctx.usage["memory_saved"] == 1
    assert session.messages[-1]["stats"] == {"mem_saved": 1, "mem_facts": ["L'usuari té 46 anys"]}
    mgr._save_session_to_disk.assert_called_once()
