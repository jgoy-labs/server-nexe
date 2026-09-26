"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_g10_memsave_nonstream_parity.py
Description: #856, la meitat que faltava — PARITAT COMPLETA del torn que només
             produeix [MEM_SAVE: ...].

             El camí streaming fa dues coses (Bug #3): (1) re-prompta el model
             amb _REPROMPT_OVERRIDE i, (2) si això tampoc rendeix text, emet la
             confirmació. El fix acea60f1 (31/07) va portar al camí no-streaming
             NOMÉS la segona — el comentari del codi ho deia: el re-prompt
             necessitava engine/sig/system_prompt/messages, locals de
             _handle_chat_engine. Conseqüència visible: amb un model que
             respon bé al re-prompt, l'usuari de la UI (stream) rebia una
             resposta conversacional i el client no-stream (API/CLI) rebia
             «Memòria desada: …». Dos productes diferents pel mateix torn.

             Aquest gate mesura la paritat amb un model que SÍ rendeix al segon
             intent. Els tests de acea60f1 (test_chat_inner_behavior.py,
             secció 7) cobreixen el cas contrari — el re-prompt torna a fallar i
             els dos camins han de dir la confirmació.

             Mutació que l'ha de matar: treure la crida a
             `_reprompt_nonstreaming` de `_postprocess_nonstreaming` →
             el no-stream torna a la confirmació i la paritat es trenca.
             (C1.4, 06/09/2026: `_handle_nonstreaming_response`, la funció
             citada aquí originalment, s'ha retirat — sense cridador de
             producció des que `turn_adapters.py` crida `postprocess` i
             `memory.write` per separat.)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi.responses import StreamingResponse

from core.turn.policy import empty_reply_text
from tests.plugins.web_ui_module.test_chat_inner_behavior import (
    _Harness,
    _make_server_state,
    _visible_stream_text,
)

_ONLY_TAG = "[MEM_SAVE: l'usuari es diu Aran]"
_SECOND_TURN = "Molt bé, Aran, ho tindré present."


#: C4.5: what the user reads when the second call is off or yields nothing.
_ACKS = {empty_reply_text(lang) for lang in ("ca", "es", "en")}


class _MemSaveThenAnswerEngine:
    """Primer torn: només la directiva. Segon torn (el re-prompt): text real.

    El contingut es decideix pel NOMBRE de crida, no pels arguments: així el
    doble no amaga cap camí del codi de producció segons què li arribi. La
    forma del retorn sí que depèn de `stream` perquè és el contracte de
    `engine.chat` (dict quan és False, async generator quan és True) — el
    re-prompt de `_yield_reprompt` sempre crida amb stream=True, tant si el
    torn original era streaming com si no.
    """

    def __init__(self):
        self.calls = 0

    def chat(self, model, messages, stream=False, images=None, thinking_enabled=False):
        self.calls += 1
        text = _ONLY_TAG if self.calls == 1 else _SECOND_TURN
        if stream:
            return self._astream(text)
        return {"message": {"content": text}, "done": True}

    async def _astream(self, text):
        yield {"message": {"content": text}}

    async def is_model_loaded(self, model_name):
        return True


@pytest.mark.asyncio
class TestG10NonStreamReprompts:

    async def test_nonstream_reprompts_instead_of_confirming(self):
        """#856 (2a meitat): si el re-prompt rendeix text, el client no-stream
        rep AQUELL text, no el missatge de confirmació."""
        engine = _MemSaveThenAnswerEngine()
        h = _Harness(intent="chat")
        result = await h.call(
            {"message": "recorda que em dic Aran", "stream": False},
            server_state=_make_server_state(engine=engine),
        )

        assert engine.calls == 2, (
            f"#856: el camí no-stream no ha re-promptat (crides a l'engine: {engine.calls})"
        )
        assert result["response"] == _SECOND_TURN, (
            "#856: el no-stream ha caigut a la confirmació en comptes de fer servir "
            f"el re-prompt (resposta: {result['response']!r})"
        )
        assert "Memòria desada" not in result["response"]
        assert result["memory_action"] == "mem_save_inline"

    async def test_the_reprompted_answer_is_the_one_persisted(self):
        """El torn desat ha de ser el que l'usuari veu: si es desa la
        confirmació i es retorna el re-prompt, la propera recàrrega menteix."""
        h = _Harness(intent="chat")
        await h.call(
            {"message": "recorda que em dic Aran", "stream": False},
            server_state=_make_server_state(engine=_MemSaveThenAnswerEngine()),
        )
        assistant = [m for m in h.session.messages if m["role"] == "assistant"]
        assert assistant, "no s'ha persistit cap torn d'assistent"
        assert assistant[-1]["content"] == _SECOND_TURN

    async def test_stream_and_nonstream_say_the_same_thing(self):
        """La paritat, mesurada: mateix model, mateix text visible als dos camins."""
        h_ns = _Harness(intent="chat")
        result = await h_ns.call(
            {"message": "recorda que em dic Aran", "stream": False},
            server_state=_make_server_state(engine=_MemSaveThenAnswerEngine()),
        )

        h_st = _Harness(intent="chat")
        streamed = await h_st.call(
            {"message": "recorda que em dic Aran", "stream": True},
            server_state=_make_server_state(engine=_MemSaveThenAnswerEngine()),
        )
        assert isinstance(streamed, StreamingResponse)
        body = ""
        async for chunk in streamed.body_iterator:
            body += chunk if isinstance(chunk, str) else chunk.decode()

        assert _visible_stream_text(body) == result["response"].strip(), (
            "#856: streaming i no-streaming donen respostes diferents pel mateix torn"
        )

    async def test_the_mem_save_tag_never_reaches_the_client(self):
        """El re-prompt no pot obrir la porta a que el tag surti pel cos."""
        h = _Harness(intent="chat")
        result = await h.call(
            {"message": "recorda que em dic Aran", "stream": False},
            server_state=_make_server_state(engine=_MemSaveThenAnswerEngine()),
        )
        assert "[MEM_SAVE:" not in result["response"]


@pytest.mark.asyncio
class TestG10ReprompFlagD3:
    """D3 (ADR-007 §6, C2.5): NEXE_REPROMPT_IF_ONLY_MEMSAVE. ON (default) is
    exactly the parity gate above (`calls == 2`); OFF skips the extra LLM
    call and goes straight to the confirmation (`calls == 1`) — on BOTH wire
    shapes, without breaking parity between them.

    Mutation (exercised by hand before merging, see the diari): removing the
    `_reprompt_enabled()` guard from `_postprocess_nonstreaming` turns
    `test_flag_off_skips_the_reprompt_call[false-False]` red (calls stays 2).
    """

    @pytest.mark.parametrize("flag_value,expect_reprompt_call", [
        ("true", True),
        ("false", False),
    ])
    async def test_flag_off_skips_the_reprompt_call(self, monkeypatch, flag_value, expect_reprompt_call):
        monkeypatch.setenv("NEXE_REPROMPT_IF_ONLY_MEMSAVE", flag_value)
        engine = _MemSaveThenAnswerEngine()
        h = _Harness(intent="chat")
        result = await h.call(
            {"message": "recorda que em dic Aran", "stream": False},
            server_state=_make_server_state(engine=engine),
        )
        assert engine.calls == (2 if expect_reprompt_call else 1)
        if expect_reprompt_call:
            assert result["response"] == _SECOND_TURN
        else:
            # C4.5: no second call → the neutral stand-in, never a "saved" (decision 1).
            assert result["response"] in _ACKS, result["response"]
            assert "Memòria desada" not in result["response"]

    async def test_flag_off_keeps_stream_and_nonstream_in_parity(self, monkeypatch):
        monkeypatch.setenv("NEXE_REPROMPT_IF_ONLY_MEMSAVE", "false")
        h_ns = _Harness(intent="chat")
        result = await h_ns.call(
            {"message": "recorda que em dic Aran", "stream": False},
            server_state=_make_server_state(engine=_MemSaveThenAnswerEngine()),
        )

        h_st = _Harness(intent="chat")
        streamed = await h_st.call(
            {"message": "recorda que em dic Aran", "stream": True},
            server_state=_make_server_state(engine=_MemSaveThenAnswerEngine()),
        )
        body = ""
        async for chunk in streamed.body_iterator:
            body += chunk if isinstance(chunk, str) else chunk.decode()

        assert _visible_stream_text(body) == result["response"].strip()
        assert result["response"] in _ACKS, result["response"]
