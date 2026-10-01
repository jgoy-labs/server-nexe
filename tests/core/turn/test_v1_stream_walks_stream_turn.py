"""C4.6-b: a `/v1` stream walks `stream_turn`, like the web door.

The forwarders yield tokens and one sentinel. This turn reads the facts,
asks again when the reply was only a tag, saves a partial when the client
leaves, and puts what it stored on the last chunk before `[DONE]`.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import BackgroundTasks

from core.endpoints.chat_engines._streaming import NEXE_END
from core.turn.adapters_api import api_adapters
from core.turn.run import stream_turn

pytestmark = pytest.mark.asyncio


def _events(chunks: list) -> list[dict]:
    """SSE payloads, in order. The sentinel never reaches this list."""
    out = []
    for chunk in chunks:
        if not isinstance(chunk, str) or not chunk.startswith("data:"):
            continue
        payload = chunk[len("data:"):].strip()
        if payload == "[DONE]":
            out.append({"_done": True})
            continue
        out.append(json.loads(payload))
    return out


def _text(chunks: list) -> str:
    parts = []
    for event in _events(chunks):
        delta = ((event.get("choices") or [{}])[0].get("delta") or {})
        content = delta.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


async def test_the_first_chunk_is_the_role_and_the_stream_ends_with_done(turn_lab):
    ctx = await turn_lab.api(streaming=True, session_id="b-role")
    events = _events(ctx.lab_wire_chunks)

    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    assert events[-1] == {"_done": True}
    assert _text(ctx.lab_wire_chunks) == "Hola, Aran."
    assert "MEM_SAVE" not in _text(ctx.lab_wire_chunks)


async def test_a_fact_is_saved_and_the_last_chunk_names_it(turn_lab):
    turn_lab.api_stream_texts = ["D'acord. [MEM_SAVE: L'usuari viu a Manresa]"]

    ctx = await turn_lab.api(streaming=True, session_id="b-fact", message="visc a Manresa")

    assert ctx.facts == ["L'usuari viu a Manresa"]
    assert "MEM_SAVE" not in _text(ctx.lab_wire_chunks)
    assert "D'acord." in _text(ctx.lab_wire_chunks)
    final = _events(ctx.lab_wire_chunks)[-2]
    assert final["nexe_memory_saved"] == 1
    assert final["nexe_memory_facts"] == ["L'usuari viu a Manresa"]
    session = turn_lab.session_manager.get_session("b-fact")
    assert session.messages[-1]["role"] == "assistant"
    assert "MEM_SAVE" not in session.messages[-1]["content"]


async def test_a_tag_only_reply_asks_again_in_sse(turn_lab):
    turn_lab.api_stream_texts = [
        "[MEM_SAVE: L'usuari viu a Manresa]",
        "Visc a Manresa, ho recordo.",
    ]

    ctx = await turn_lab.api(streaming=True, session_id="b-reprompt", message="visc a Manresa")

    text = _text(ctx.lab_wire_chunks)
    assert "MEM_SAVE" not in text
    assert "Visc a Manresa" in text
    assert ctx.lab_wire_chunks[-1].strip() == "data: [DONE]"


async def test_the_lease_is_held_until_done(turn_lab):
    from tests.core.turn.conftest import LAB_PRINCIPAL, door_patches, make_request
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message
    from core.turn.context import TurnContext

    body = ChatCompletionRequest(
        messages=[Message(role="user", content="hola")],
        use_rag=True, stream=True, engine="ollama",
    )
    request = make_request(turn_lab.app_state)
    request.scope["headers"] = [
        (b"x-api-key", b"test-key"), (b"x-session-id", b"b-lease"),
    ]
    ctx = TurnContext(
        turn_id="turn-b-lease", entry="api", streaming=True, principal=LAB_PRINCIPAL,
        body=body, request=request, app_state=turn_lab.app_state,
    )
    with door_patches(turn_lab.server_state, turn_lab.memory_helper, streaming=True):
        agen = await stream_turn(ctx, api_adapters(BackgroundTasks(), streaming=True))
        first = await agen.__anext__()
        assert "role" in first
        held = turn_lab.session_manager.get_session("b-lease")
        assert held.lease["turn_id"] == "turn-b-lease"
        rest = []
        saw_final_while_held = False
        async for chunk in agen:
            rest.append(chunk)
            # The final chunk is already in our hands and `[DONE]` has not
            # been asked for yet. Releasing before that chunk would drop the
            # lease here, while the client still has the stream open.
            if not isinstance(chunk, str) or not chunk.startswith("data:"):
                continue
            payload = chunk[len("data:"):].strip()
            if payload == "[DONE]":
                continue
            reason = (json.loads(payload).get("choices") or [{}])[0].get("finish_reason")
            if reason:
                assert held.lease is not None
                assert held.lease["turn_id"] == "turn-b-lease"
                saw_final_while_held = True

    assert saw_final_while_held
    assert any(isinstance(c, str) and c.strip() == "data: [DONE]" for c in rest)
    assert turn_lab.session_manager.get_session("b-lease").lease is None


async def test_a_disconnect_saves_the_partial(turn_lab):
    from tests.core.turn.conftest import LAB_PRINCIPAL, make_request
    from core.endpoints.chat_engines._common import mark_served_model
    from core.endpoints.chat_engines._streaming import format_sse_chunk
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message
    from core.turn.context import TurnContext
    from fastapi.responses import StreamingResponse
    from unittest.mock import AsyncMock, patch

    async def agen():
        # The token leaves, then the engine stays open. Closing the turn
        # here is the client leaving mid-stream. `started` cannot be set
        # AFTER this yield: nothing resumes the generator until aclose, so
        # the test would wait forever.
        yield format_sse_chunk("parcial", "llama3.2:3b", "ollama")
        await asyncio.Event().wait()

    def _response(*_a, **_k):
        return mark_served_model(
            StreamingResponse(agen(), media_type="text/event-stream"), "llama3.2:3b",
        )

    body = ChatCompletionRequest(
        messages=[Message(role="user", content="hola")],
        use_rag=True, stream=True, engine="ollama",
    )
    request = make_request(turn_lab.app_state)
    request.scope["headers"] = [(b"x-api-key", b"test-key"), (b"x-session-id", b"b-partial")]
    ctx = TurnContext(
        turn_id="turn-b-partial", entry="api", streaming=True, principal=LAB_PRINCIPAL,
        body=body, request=request, app_state=turn_lab.app_state,
    )

    async def _no_rag(*_a, **_k):
        return "", []

    with patch("core.lifespan.get_server_state", return_value=turn_lab.server_state), \
         patch("core.memory_facts.helper_for", return_value=turn_lab.memory_helper), \
         patch("core.endpoints.chat_rag.build_rag_context", new=_no_rag), \
         patch("core.endpoints.chat.build_rag_context", new=_no_rag), \
         patch("core.endpoints.chat._forward_to_ollama", new=AsyncMock(side_effect=_response)):
        stream = await stream_turn(ctx, api_adapters(BackgroundTasks(), streaming=True))
        await stream.__anext__()  # role
        await stream.__anext__()  # the partial token
        await stream.aclose()

    saved = turn_lab.session_manager.get_session("b-partial").messages[-1]
    assert saved["content"] == "parcial"
    assert saved.get("partial") is True
    assert turn_lab.session_manager.get_session("b-partial").lease is None


async def test_ollama_refuses_before_the_first_token_as_http():
    from core.endpoints.chat_engines.ollama import _ollama_stream_generator
    from fastapi import HTTPException
    from unittest.mock import AsyncMock, MagicMock, patch

    resp = AsyncMock()
    resp.status_code = 503
    resp.aiter_lines = MagicMock(return_value=_empty())
    stream_cm = AsyncMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.stream = MagicMock(return_value=stream_cm)

    with patch("httpx.AsyncClient", return_value=client):
        gen = _ollama_stream_generator("http://127.0.0.1:11434/api/chat", {"model": "qwen3.5:4b"})
        with pytest.raises(HTTPException) as exc:
            await gen.__anext__()
    assert exc.value.status_code == 503


async def _empty():
    if False:
        yield ""


async def test_a_memory_command_streams_sse_not_json(turn_lab):
    """A command answers before `generate`. With `stream: true` the client
    still gets SSE: role, the answer, `[DONE]`."""
    turn_lab.memory_helper.detect_intent = lambda _message: ("list", None)

    ctx = await turn_lab.api(streaming=True, session_id="b-memory", message="què recordes")

    events = _events(ctx.lab_wire_chunks)
    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    assert events[-1] == {"_done": True}
    assert _text(ctx.lab_wire_chunks)
    assert ctx.outcomes.get("generate") == "skipped"
    assert not isinstance(ctx.lab_wire_chunks[0], dict)


async def test_the_sentinel_key_is_not_error():
    """`test_sse_sanitize_coverage` treats an `"error"` key as an SSE chunk."""
    assert NEXE_END != "error"
