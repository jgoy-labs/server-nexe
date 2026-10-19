"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/api.py
Description: The `/v1` forwarder of the API engine (phase 3 of the API providers).

    `engine="api"` sends the conversation, the retrieved documents and the
    memory to an external provider, so this forwarder does what no other one
    does: it asks the cloud gate (`core/providers/cloud.py`) ITSELF, on the body
    it is handed, before it touches the module. The turn's `session` and
    `engine` steps already asked it; asking again here means a caller that
    reaches the forwarder some other way (the re-prompt, a test, tomorrow's
    door) still cannot send a byte without the switch, a model and key a
    provider owns, and the request's own consent.

    It never answers with another engine: a refusal is an HTTP error, a
    provider that fails is that error, and nothing here (or in the dispatcher
    that calls it) falls to Ollama.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from core.providers.cloud import CLOUD_ENGINE
from core.turn.text.chunks import parse_chunk

from ..chat_schemas import ChatCompletionRequest
from core.turn.usage import from_openai as usage_from_openai

from ._common import build_openai_response, mark_served_model
from ._streaming import MAX_STREAM_BYTES, format_engine_token, stream_end
from .routing import bind_to_model, cloud_gate, get_engine_module

logger = logging.getLogger(__name__)


def _live_engine(request: ChatCompletionRequest, req: Request) -> Any:
    """The API engine bound to the request's model, or a 503 if it is not loaded."""
    module = get_engine_module(CLOUD_ENGINE, req.app.state)
    if module is None or not hasattr(module, "chat"):
        raise HTTPException(status_code=503, detail="The API engine is not loaded on this server")
    return bind_to_model(module, request.model)


async def _let_go(chunks: Any) -> None:
    """Close the provider's stream, which closes its connection: on every way out of a read."""
    close = getattr(chunks, "aclose", None)
    if close is None:
        return
    try:
        await close()
    except Exception:  # letting go must never replace the error (or the answer) that is on its way out
        logger.debug("API stream: closing the provider's stream raised", exc_info=True)


def _chunk_end(chunk: Dict[str, Any]) -> Optional[str]:
    """`"length"` if the provider cut the answer at its ceiling, else None."""
    return "length" if isinstance(chunk, dict) and chunk.get("done_reason") == "length" else None


async def _api_stream_generator(chunks: Any, model_name: str):
    """The provider's chunks as SSE, then one `stream_end` sentinel.

    Same contract as the other forwarders: an error before the first token is
    RAISED (the cascade's peek can still answer with HTTP, and the curated
    class — auth, provider, timeout — decides what the client is told); after
    a token the wire is committed and the failure travels in the sentinel.
    A client that leaves closes this generator, which closes the provider's
    stream (and the connection) underneath it.
    """
    got_any = False
    produced = 0
    finish: Optional[str] = None
    usage: Optional[dict] = None
    try:
        async for chunk in chunks:
            usage = usage_of_chunk(chunk) or usage
            content, thinking = parse_chunk(chunk)
            produced += len((content + thinking).encode("utf-8", errors="replace"))
            if produced > MAX_STREAM_BYTES:
                logger.warning("API stream cap reached (%d bytes > %d). Terminating early.", produced, MAX_STREAM_BYTES)
                yield stream_end(failure="stream_cap_exceeded", truncated=True)
                return
            sse = format_engine_token(chunk, model_name, CLOUD_ENGINE)
            if sse is not None:
                got_any = True
                yield sse
            finish = _chunk_end(chunk) or finish
    except asyncio.CancelledError:
        logger.debug("API stream cancelled (client disconnected)")
        raise  # a cancellation leaves: the turn must not see a clean end
    except Exception as exc:
        if not got_any:
            raise
        # The text of a curated error names the provider and the status, never a key or a body.
        logger.warning("API stream failed after its first token: %s", type(exc).__name__)
        yield stream_end(failure=type(exc).__name__)
        return
    finally:
        await _let_go(chunks)
    yield stream_end(finish_reason=finish, usage=usage)


def usage_of_chunk(chunk: Any) -> Optional[dict]:
    """What the provider said the call cost, if this chunk carries it."""
    return usage_from_openai(chunk.get("usage")) if isinstance(chunk, dict) else None


async def _whole_reply(chunks: Any) -> Dict[str, Any]:
    """A non-streaming call: the provider's single chunk as the engine-result dict."""
    text, thinking, finish, usage = "", "", None, None
    try:
        async for chunk in chunks:
            usage = usage_of_chunk(chunk) or usage
            content, reasoning = parse_chunk(chunk)
            text, thinking = text + content, thinking + reasoning
            finish = _chunk_end(chunk) or finish
    finally:
        await _let_go(chunks)
    result = {"response": text, "thinking": thinking, "finish_reason": finish}
    if usage:  # the JSON body is built from these two (`build_openai_response`)
        result.update(prompt_tokens=usage.get("tokens_in") or 0, tokens=usage.get("tokens_out") or 0)
    return result


async def _forward_to_api(
    messages: List[Dict], request: ChatCompletionRequest, req: Request, *, cancel_event: Any = None,
    images: Optional[List[str]] = None,
):
    """Forward the request to the API engine, if — and only if — the cloud gate says so.

    Not sent: `temperature` and `max_tokens` (the provider's own defaults stand,
    as at the web door: some models renamed or refuse them), nor `resume` (a
    provider cannot resume mid-sentence; a Continue never reaches here).
    """
    cloud_gate(request)
    engine = _live_engine(request, req)
    resuming = getattr(request, "resume", False) is True
    chunks = engine.chat(
        model=request.model, messages=messages, stream=bool(request.stream), images=images,
        thinking_enabled=request.wants_reasoning() and not resuming,
        top_p=request.top_p, cancel_event=cancel_event,
    )
    if request.stream:
        logger.info("Forwarding to the API engine (streaming)...")
        # Not peeked here: the cascade reads the first chunk before it commits
        # to this engine (`peek_stream`), so an error before any token is a real exception.
        return mark_served_model(StreamingResponse(
            _api_stream_generator(chunks, request.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        ), request.model)
    logger.info("Forwarding to the API engine...")
    return build_openai_response(await _whole_reply(chunks), request.model, CLOUD_ENGINE)
