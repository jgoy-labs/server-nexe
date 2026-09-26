"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_reprompt_one_policy.py
Description: ADR-007 C4.5 — one re-prompt for the three entries. A turn whose
             whole answer was [MEM_SAVE:] tags asks the model again at
             UI-stream, UI-JSON and /v1 JSON alike; the second call is counted
             ONCE (I8), takes an engine slot, and with the flag off none of
             the three spends it and all three answer the same neutral phrase.

             Real turns through the real adapter tables (`turn_lab`); the only
             fake is the model, which answers a tag first and a sentence next.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.turn import policy
from core.turn.gate import EngineGate

ONLY_TAG = "[MEM_SAVE: l'usuari es diu Aran]"
ANSWER = "Encantat, Aran. Què vols fer avui?"
MESSAGE = "recorda que em dic Aran"
ACKS = {policy.empty_reply_text(lang) for lang in ("ca", "es", "en")}


class _OllamaShapedEngine:
    """Ollama shape (`model` in the signature) — the shape the web door can
    call twice. Answers by CALL NUMBER, never by argument, so the double hides
    no production path: tag first, sentence next, sentence forever after."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False, **_kwargs):
        self.calls += 1
        text = self.replies[min(self.calls, len(self.replies)) - 1]
        if stream:
            return self._astream(text)
        return {"message": {"content": text}, "done": True}

    async def _astream(self, text):
        # In pieces, as an engine streams: a tag may well be cut in two.
        half = len(text) // 2
        for piece in (text[:half], text[half:]):
            if piece:
                yield {"message": {"content": piece}}

    async def is_model_loaded(self, model_name):
        return True


def _reprompt_calls(ctx) -> list:
    return [c for c in (ctx.usage.get("llm") or {}).get("calls", []) if c["step"] == "reprompt"]


def _steps(ctx) -> list:
    return [c["step"] for c in (ctx.usage.get("llm") or {}).get("calls", [])]


async def _turn(turn_lab, door: str, session_id: str):
    if door == "ui-json":
        return await turn_lab.ui(streaming=False, session_id=session_id, message=MESSAGE)
    if door == "ui-stream":
        return await turn_lab.ui(streaming=True, session_id=session_id, message=MESSAGE)
    return await turn_lab.api(session_id=session_id, message=MESSAGE)


def _text_of(ctx) -> str:
    if ctx.entry == "api":
        return ctx.wire["choices"][0]["message"]["content"]
    return ctx.response


@pytest.fixture
def engine(turn_lab) -> _OllamaShapedEngine:
    eng = _OllamaShapedEngine([ONLY_TAG, ANSWER])
    turn_lab.app_state.modules = {"ollama_module": eng}
    turn_lab.api_answers = [ONLY_TAG, ANSWER]
    return eng


@pytest.mark.parametrize("door", ["ui-json", "ui-stream", "api"])
async def test_a_tags_only_turn_asks_the_model_again_at_every_entry(turn_lab, engine, door):
    ctx = await _turn(turn_lab, door, f"rp-{door}")

    assert _text_of(ctx) == ANSWER, f"{door}: {_text_of(ctx)!r}"
    assert "MEM_SAVE" not in _text_of(ctx)
    if door.startswith("ui"):
        assert engine.calls == 2, f"{door}: the model was asked {engine.calls} time(s)"
    else:
        assert _steps(ctx) == ["generate", "reprompt"], _steps(ctx)
        assert "reprompt" not in ctx.usage.get("degraded", {}), "C4.5 closed this limit"


@pytest.mark.parametrize("door", ["ui-json", "ui-stream", "api"])
async def test_the_second_call_is_counted_exactly_once(turn_lab, engine, door):
    """I8: the streaming door counted it whenever the reply was empty (flag off
    or engine skipped alike), the JSON door never, /v1 never spent it."""
    ctx = await _turn(turn_lab, door, f"rp-count-{door}")
    calls = _reprompt_calls(ctx)
    assert len(calls) == 1, f"{door}: {calls}"
    assert calls[0]["engine"], "the entry names the engine"
    if door.startswith("ui"):
        assert calls[0]["model"] == "llama3.2:3b", "the entry names the model (I8, 13/09 esmena c)"


async def test_the_streamed_second_answer_reaches_the_wire(turn_lab, engine):
    ctx = await turn_lab.ui(streaming=True, session_id="rp-wire", message=MESSAGE)
    wire = "".join(c if isinstance(c, str) else c.decode() for c in ctx.lab_wire_chunks)
    assert ANSWER in wire
    assert "Memòria desada" not in wire


@pytest.mark.parametrize("door", ["ui-json", "ui-stream", "api"])
async def test_flag_off_spends_nothing_and_answers_the_same_neutral_phrase(turn_lab, engine, monkeypatch, door):
    monkeypatch.setenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, "false")
    ctx = await _turn(turn_lab, door, f"rp-off-{door}")
    text = _text_of(ctx)
    assert text in ACKS, f"{door}: {text!r}"
    assert "Memòria desada" not in text and "MEM_SAVE" not in text
    assert _reprompt_calls(ctx) == []
    if door.startswith("ui"):
        assert engine.calls == 1
    else:
        assert _steps(ctx) == ["generate"]


@pytest.mark.parametrize("door", ["ui-json", "ui-stream", "api"])
async def test_the_second_call_takes_a_slot_generate_gave_back_and_returns_it(turn_lab, engine, door):
    """One slot on the gate: the re-prompt can only run if `generate` released
    its own before `postprocess`, and it must leave the gate as it found it."""
    gate = EngineGate(slots=1)
    turn_lab.app_state.engine_gate = gate
    ctx = await _turn(turn_lab, door, f"rp-gate-{door}")
    assert _text_of(ctx) == ANSWER, f"{door}: the second call found no slot"
    assert gate._free() == 1, f"{door}: a slot was not given back"


@pytest.mark.parametrize("door", ["ui-json", "ui-stream", "api"])
async def test_a_second_answer_that_is_the_tag_again_shows_the_neutral_phrase(turn_lab, door):
    """Live 26/09 (gemma4:e4b): asked again, the model wrote the same tag and
    nothing else — streamed in pieces, so no single chunk holds the whole tag.
    What the user reads is the neutral phrase, never the tag."""
    engine = _OllamaShapedEngine([ONLY_TAG, ONLY_TAG])
    turn_lab.app_state.modules = {"ollama_module": engine}
    turn_lab.api_answers = [ONLY_TAG, ONLY_TAG]
    ctx = await _turn(turn_lab, door, f"rp-tag-again-{door}")
    text = _text_of(ctx)
    assert text in ACKS, f"{door}: {text!r}"
    assert "MEM_SAVE" not in text
    assert len(_reprompt_calls(ctx)) == 1
