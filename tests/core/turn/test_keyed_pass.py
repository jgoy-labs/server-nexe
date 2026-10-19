"""pla-memoria-fiable, F-C: the second pass of memory.write, for either door."""
import json
from types import SimpleNamespace

import pytest

from core.turn import keyed_pass
from core.turn.gate import GateBusy

pytestmark = pytest.mark.asyncio

REPLY = json.dumps({"facts": [{"entity": "user", "attribute": "age", "value": "46",
                                "statement": "L'usuari té 46 anys", "intent": "change"}]})


class FakeGate:
    def __init__(self, busy=False):
        self.busy, self.released = busy, 0

    async def acquire(self, *a, **k):
        if self.busy:
            raise GateBusy("busy")
        return object()

    async def release(self, slot):
        self.released += 1


class Engine:
    """An engine whose chat() is an async generator, like Ollama's."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def chat(self, model, messages, stream=True, thinking_enabled=False, response_schema=None):
        self.calls.append({"model": model, "schema": response_schema, "user": messages[-1]["content"],
                           "system": messages[0]["content"]})
        yield {"message": {"content": self.replies.pop(0) if self.replies else ""}}


class FakePort:
    def __init__(self):
        self.saved = []

    async def get_memory_api(self):
        return SimpleNamespace(collection_exists=lambda n: _true(), scroll=lambda **k: _empty())

    async def save_to_memory(self, content, session_id, metadata=None, collections=None, force=False):
        self.saved.append((content, metadata))
        return {"success": True, "document_id": "d"}


async def _true():
    return True


async def _empty():
    return [], None


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("NEXE_MEMORY_KEYED", "true")
    gate = FakeGate()
    monkeypatch.setattr(keyed_pass, "gate_for", lambda app_state, engine=None: gate)
    return gate


def _ctx(message="Ara tinc 46 anys.", **kw):
    return SimpleNamespace(usage={}, message=message, resume=False, app_state=None, turn_id="t", facts=[], **kw)


async def _run(ctx, engine, port=None, **kw):
    return await keyed_pass.run(ctx, engine=engine, engine_name="ollama", model_name="m",
                                session=SimpleNamespace(id="s", _pending_replace=None), port=port or FakePort(), **kw)


async def test_the_message_is_read_and_its_fact_saved(on):
    ctx, port = _ctx(), FakePort()
    out = await _run(ctx, Engine([REPLY]), port)
    assert out.handled and out.saved == 1 and port.saved[0][0] == "L'usuari té 46 anys"
    assert ctx.usage["llm"]["calls"][-1]["step"] == "memory.write" and on.released == 1


async def test_ollama_is_asked_for_the_shape(on):
    engine = Engine([REPLY])
    await _run(_ctx(), engine)
    assert engine.calls[0]["schema"]["required"] == ["facts"] and engine.calls[0]["user"] == "Ara tinc 46 anys."


async def test_a_reply_that_is_not_json_gets_one_more_try(on):
    engine = Engine(["sorry", REPLY])
    out = await _run(_ctx(), engine)
    assert out.handled and len(engine.calls) == 2


async def test_two_bad_replies_leave_the_tags_to_do_it(on):
    out = await _run(_ctx(), Engine(["no", "still no"]))
    assert out.handled is False


async def test_a_message_with_no_fact_leaves_the_tags(on):
    out = await _run(_ctx("Quina hora és bona per dinar?"), Engine([json.dumps({"facts": []})]))
    assert out.handled is False


async def test_a_value_the_user_did_not_write_is_not_kept(on):
    invented = json.dumps({"facts": [{"entity": "user", "attribute": "age", "value": "99",
                                       "statement": "L'usuari té 99 anys", "intent": "set"}]})
    port = FakePort()
    out = await _run(_ctx(), Engine([invented]), port)
    assert out.handled is False and port.saved == []


async def test_a_delete_only_message_is_not_this_passes_business(on):
    gone = json.dumps({"facts": [{"entity": "user", "attribute": "phone", "value": "", "statement": "", "intent": "delete"}]})
    assert (await _run(_ctx("Oblida el meu telèfon."), Engine([gone]))).handled is False


@pytest.mark.parametrize("why", ["switch_off", "no_engine", "saved_by_intent", "resumed", "memory_off"])
async def test_it_does_not_run_when_it_should_not(on, monkeypatch, why):
    ctx, engine, kw = _ctx(), Engine([REPLY]), {}
    if why == "switch_off":
        monkeypatch.setenv("NEXE_MEMORY_KEYED", "false")
    elif why == "no_engine":
        engine = None
    elif why == "saved_by_intent":
        ctx.usage["saved_by_intent"] = True
    elif why == "resumed":
        ctx.resume = True
    elif why == "memory_off":
        kw["rag_collections"] = ["documents"]
    out = await _run(ctx, engine, **kw)
    assert out.handled is False and (engine is None or engine.calls == [])


async def test_a_busy_engine_leaves_the_tags(on):
    on.busy = True
    engine = Engine([REPLY])
    assert (await _run(_ctx(), engine)).handled is False and engine.calls == []


async def test_a_failing_engine_never_fails_the_turn(on):
    class Broken:
        async def chat(self, model, messages, stream=True, thinking_enabled=False):
            raise RuntimeError("down")
            yield  # pragma: no cover

    assert (await _run(_ctx(), Broken())).handled is False and on.released == 1


async def test_a_provider_gets_the_names_of_the_stored_keys_not_their_values(on, monkeypatch):
    seen = {}

    async def fake_stored(port):
        return [{"entity": "user", "attribute": "phone", "value": "600111222", "text": "t", "value_norm": "600111222"}]

    real_extract = keyed_pass._keyed().extract

    async def spy(engine, model_name, sig, message, known=None):
        seen["known"] = known
        return await real_extract(engine, model_name, sig, message, known)

    monkeypatch.setattr(keyed_pass._keyed(), "stored_keyed", fake_stored)
    monkeypatch.setattr(keyed_pass._keyed(), "extract", spy)
    out = await keyed_pass.run(_ctx(), engine=Engine([REPLY]), engine_name="api", model_name="m",
                               session=SimpleNamespace(id="s", _pending_replace=None), port=FakePort())
    assert out.handled and seen["known"] == [{"entity": "user", "attribute": "phone", "value": "",
                                              "text": "t", "value_norm": "600111222"}]
    seen.clear()
    await keyed_pass.run(_ctx(), engine=Engine([REPLY]), engine_name="ollama", model_name="m",
                         session=SimpleNamespace(id="s", _pending_replace=None), port=FakePort())
    assert seen["known"][0]["value"] == "600111222"


async def test_the_prompt_a_provider_receives_holds_no_stored_value_and_no_other_person(on, monkeypatch):
    rows = [{"entity": "user", "attribute": "phone", "value": "600111222", "text": "t", "value_norm": "600111222"},
            {"entity": "maria", "attribute": "age", "value": "61", "text": "t2", "value_norm": "61"}]

    async def fake_stored(port):
        return rows

    monkeypatch.setattr(keyed_pass._keyed(), "stored_keyed", fake_stored)
    engine = Engine([REPLY])
    await keyed_pass.run(_ctx(), engine=engine, engine_name="api", model_name="m",
                         session=SimpleNamespace(id="s", _pending_replace=None), port=FakePort())
    system = engine.calls[0]["system"]
    assert "user.phone" in system and "600111222" not in system and "maria" not in system and "61" not in system


async def test_the_tags_the_facts_do_not_account_for_stay_for_the_old_path(on):
    ctx = _ctx()
    ctx.facts = ["L'usuari té 46 anys", "L'usuari treballa de fuster"]
    out = await _run(ctx, Engine([REPLY]))
    assert out.handled and ctx.facts == ["L'usuari treballa de fuster"]
