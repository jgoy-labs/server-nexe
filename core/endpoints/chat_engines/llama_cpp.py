"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/llama_cpp.py
Description: Llama.cpp (GGUF) engine integration for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..chat_schemas import ChatCompletionRequest
from ._common import extract_last_user_msg, separate_messages, derive_session_id, build_openai_response, mark_served_model, resolve_loaded_model_name
from ._streaming import TokenBridge, _prepend_chunk, format_engine_token, stream_end

logger = logging.getLogger(__name__)


async def _forward_to_llama_cpp(
    messages: List[Dict], request: ChatCompletionRequest, req: Request, *, cancel_event=None,
    images: Optional[List[str]] = None,
):
    """Forward to Llama.cpp module (GGUF models).

    #1036 (C2.4): this used to catch its own failures and jump straight to
    Ollama, a second fallback mechanism that contradicted (and pre-empted)
    the mlx→llama_cpp→ollama cascade in ``_dispatch_through_cascade``. Every
    exception here now propagates instead, so the cascade is the ONLY place
    that decides what runs next.

    `cancel_event` (#1041, C2.5): threaded through from ``_dispatch_to_engine``
    — see ``_llama_cpp_stream_generator``'s docstring for why /v1 needed this
    door at all.

    `images` (#1081): a single base64 string in a list, the same shape
    `_start_engine_call` has always passed at the UI door — llama.cpp decides
    whether the loaded model reads it, never this forwarder.
    """
    # #1107: a resume ends inside the cut answer. Only an explicit True counts;
    # a MagicMock request grows a truthy `.resume` that must not resume.
    resuming = getattr(request, "resume", False) is True
    continued = {"continue_final": True} if resuming else {}
    last_user_msg = extract_last_user_msg(messages)
    # F-C: derived from the RAW client request (request.messages), not the
    # RAG/system-prompt-augmented `messages` param.
    session_id = derive_session_id(req, request.messages)

    llama_module = None
    if hasattr(req.app.state, 'modules'):
        llama_module = req.app.state.modules.get('llama_cpp_module')

    if not llama_module or not hasattr(llama_module, 'chat'):
        # Should not happen in practice: resolve_engine_cascade already
        # filters on _engine_available before choosing "llama_cpp". Raising
        # (not falling back here) still lets the cascade move on if this
        # module died between that check and this call.
        raise RuntimeError("Llama.cpp module not available (model not configured)")

    system_msg, user_messages = separate_messages(messages)
    # B075-C3: report the model that actually ran, not the client's
    # request.model (llama.cpp runs the single loaded GGUF, ignoring it).
    model_name = resolve_loaded_model_name(llama_module, "llama-cpp-local")

    if request.stream:
        agen = _llama_cpp_stream_generator(
            llama_module, user_messages, system_msg, model_name,
            app_state=req.app.state, user_msg=last_user_msg,
            session_id=session_id, max_tokens=request.max_tokens,
            temperature=request.temperature, top_p=request.top_p,
            cancel_event=cancel_event, images=images,
            continue_final=resuming,
        )
        # Peek the first chunk BEFORE committing to a StreamingResponse: an
        # error before any token reaches the client raises here as a real
        # exception (#1036), which the cascade can still retry.
        first_chunk = await agen.__anext__()
        return mark_served_model(StreamingResponse(
            _prepend_chunk(first_chunk, agen),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        ), model_name)

    logger.info("Forwarding to Llama.cpp module...")
    result = await llama_module.chat(
        messages=user_messages, system=system_msg, session_id=session_id,
        max_tokens=request.max_tokens, temperature=request.temperature,
        top_p=request.top_p, cancel_event=cancel_event, images=images,
        **continued,
    )
    return build_openai_response(result, model_name, "llamacpp")

async def _llama_cpp_stream_generator(
    llama_module,
    user_messages: List[Dict],
    system_msg: str,
    model_name: str,
    app_state=None,
    user_msg: Optional[str] = None,
    session_id: str = "chat_session",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    cancel_event=None,
    images: Optional[List[str]] = None,
    continue_final: bool = False,
):
    """SSE generator for Llama.cpp streaming.

    Uses :class:`TokenBridge` to bridge the synchronous llama.cpp callback
    to the async generator that FastAPI requires.

    `cancel_event` (#1041, C2.5): the UI's own `_start_engine_call` already
    threads one through for a client disconnect; `/v1` never had a monitor at
    all before C2.5 (`core.turn.adapters_api::generate`), so a deadline timer
    is the first thing that sets it here. Either way the module's own token
    loop is what checks it — this generator only has to pass it along.
    """
    bridge = TokenBridge(cancel_event=cancel_event)

    async def run_llama():
        try:
            result = await llama_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id=session_id,
                stream_callback=bridge.on_token,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                cancel_event=cancel_event,
                images=images,
                continue_final=continue_final,
            )
            bridge.set_done(result=result)
        except Exception as e:
            bridge.set_done(error=str(e))
            logger.error("Llama.cpp streaming error: %s", e, exc_info=True)

    llama_task = asyncio.create_task(run_llama())
    got_any_token = False

    try:
        try:
            async for token in bridge:
                got_any_token = True
                sse = format_engine_token(token, model_name, "llamacpp")  # ADR-010
                if sse is not None:
                    yield sse

            await llama_task
        except asyncio.CancelledError:
            logger.debug("Llama.cpp stream cancelled (client disconnected)")
            return
        except Exception as e:
            logger.exception("Llama.cpp streaming failed")
            if not got_any_token:
                raise
            yield stream_end(failure=str(e), truncated=bridge._truncated)
            return

        if bridge.error:
            if not got_any_token:
                # #1036 (C2.4): nothing reached the client yet. This raise is
                # outside the try/except above on purpose — the forwarder's
                # peek retries the cascade.
                raise RuntimeError(bridge.error)
            logger.error("Llama.cpp streaming error surfaced to client: %s", bridge.error)
            yield stream_end(failure=str(bridge.error), truncated=bridge._truncated)
            return

        # Ceiling cut vs queue overflow: the turn's `emit` writes both (#989).
        # Persistence is the turn's `persist_assistant_turn`.
        yield stream_end(
            truncated=bridge._truncated,
            finish_reason=(bridge.result or {}).get("finish_reason"),
        )

    finally:
        if not llama_task.done():
            llama_task.cancel()
