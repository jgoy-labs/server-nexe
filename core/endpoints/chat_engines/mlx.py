"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/mlx.py
Description: MLX (Apple Silicon) engine integration for Chat endpoint.

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


async def _mlx_stream_generator(
    mlx_module,
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
    thinking_enabled: bool = False,
    continue_final: bool = False,
):
    """SSE generator for MLX streaming.

    Uses :class:`TokenBridge` to bridge the synchronous MLX callback
    to the async generator that FastAPI requires.

    `cancel_event` (#1041, C2.5): the UI's own `_start_engine_call` already
    threads one through for a client disconnect; `/v1` never had a monitor at
    all before C2.5 (`core.turn.adapters_api::generate`), so a deadline timer
    is the first thing that sets it here. Either way the module's own token
    loop is what checks it — this generator only has to pass it along.
    """
    bridge = TokenBridge(cancel_event=cancel_event)

    async def run_mlx():
        try:
            result = await mlx_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id=session_id,
                stream_callback=bridge.on_token,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                cancel_event=cancel_event,
                images=images,
                thinking_enabled=thinking_enabled,
                **({"continue_final": True} if continue_final else {}),
            )
            bridge.set_done(result=result)
        except Exception as e:
            bridge.set_done(error=str(e))
            logger.error("MLX streaming error: %s", e, exc_info=True)

    mlx_task = asyncio.create_task(run_mlx())
    got_any_token = False

    try:
        try:
            async for token in bridge:
                got_any_token = True
                sse = format_engine_token(token, model_name, "mlx")  # ADR-010
                if sse is not None:
                    yield sse

            await mlx_task
        except asyncio.CancelledError:
            logger.debug("MLX stream cancelled (client disconnected)")
            return
        except Exception as e:
            logger.exception("MLX streaming failed")
            # Before any token this is still the cascade's to retry (#1036).
            # After a token the wire is committed: the turn saves a partial.
            if not got_any_token:
                raise
            yield stream_end(failure=str(e), truncated=bridge._truncated)
            return

        # If the engine task failed, surface it as the end sentinel instead of
        # closing as a clean stop. Before any token the raise leaves this
        # function so the forwarder's peek can retry the cascade (#1036).
        if bridge.error:
            if not got_any_token:
                raise RuntimeError(bridge.error)
            logger.error("MLX streaming error surfaced to client: %s", bridge.error)
            yield stream_end(failure=str(bridge.error), truncated=bridge._truncated)
            return

        # The engine's own reason (ceiling cut) travels in bridge.result.
        # bridge._truncated is a DIFFERENT cut (queue overflow, B216). The
        # turn's `emit` writes both into the client's final chunk (#989).
        # Persistence is the turn's `persist_assistant_turn`, not this generator.
        yield stream_end(
            truncated=bridge._truncated,
            finish_reason=(bridge.result or {}).get("finish_reason"),
        )

        if bridge.result:
            logger.info(
                "MLX stream completed: %d tokens, %.1f tok/s",
                bridge.result.get("tokens", 0),
                bridge.result.get("tokens_per_second", 0),
            )
    finally:
        if not mlx_task.done():
            mlx_task.cancel()


async def _forward_to_mlx(
    messages: List[Dict], request: ChatCompletionRequest, req: Request, *, cancel_event=None,
    images: Optional[List[str]] = None,
):
    """Forward to MLX module (Apple Silicon optimized).

    #1036 (C2.4): this used to catch its own failures and jump straight to
    Ollama, a second fallback mechanism that contradicted (and pre-empted)
    the mlx→llama_cpp→ollama cascade in ``_dispatch_through_cascade``. Every
    exception here now propagates instead, so the cascade is the ONLY place
    that decides what runs next.

    `cancel_event` (#1041, C2.5): threaded through from ``_dispatch_to_engine``
    — see ``_mlx_stream_generator``'s docstring for why /v1 needed this door
    at all.

    `images` (#1081): a single base64 string in a list, the same shape
    `_start_engine_call` has always passed at the UI door — MLX decides
    whether the loaded model reads it (`_detect_vlm_capability`), never this
    forwarder.
    """
    last_user_msg = extract_last_user_msg(messages)
    # F-C: derived from the RAW client request (request.messages), not the
    # RAG/system-prompt-augmented `messages` param — the thread id must track
    # what the client actually sent, not what the engine ends up seeing.
    session_id = derive_session_id(req, request.messages)

    mlx_module = None
    if hasattr(req.app.state, 'modules'):
        mlx_module = req.app.state.modules.get('mlx_module')

    if not mlx_module or not hasattr(mlx_module, 'chat'):
        # Should not happen in practice: resolve_engine_cascade already
        # filters on _engine_available before choosing "mlx". Raising (not
        # falling back here) still lets the cascade move on if this module
        # died between that check and this call.
        raise RuntimeError("MLX module not available (Metal/model not configured)")

    system_msg, user_messages = separate_messages(messages)
    # B075-C3: report the model that actually ran, not the client's
    # request.model (MLX runs the single loaded model, ignoring the param).
    model_name = resolve_loaded_model_name(mlx_module, "mlx-local")
    # A resume ends inside the cut answer. Thinking would open a new
    # reasoning block and the prefix would stop being the one that was cut.
    resuming = getattr(request, "resume", False) is True
    thinking = request.wants_reasoning() and not resuming
    continued = {"continue_final": True} if resuming else {}

    if request.stream:
        logger.info("Forwarding to MLX module (streaming)...")
        agen = _mlx_stream_generator(
            mlx_module, user_messages, system_msg, model_name,
            app_state=req.app.state, user_msg=last_user_msg,
            session_id=session_id, max_tokens=request.max_tokens,
            temperature=request.temperature, top_p=request.top_p,
            cancel_event=cancel_event, images=images,
            thinking_enabled=thinking,
            **continued,
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

    logger.info("Forwarding to MLX module...")
    result = await mlx_module.chat(
        messages=user_messages, system=system_msg, session_id=session_id,
        max_tokens=request.max_tokens, temperature=request.temperature,
        top_p=request.top_p, cancel_event=cancel_event, images=images,
        thinking_enabled=thinking,  # ADR-010: off unless asked; off on a resume
        **continued,
    )
    return build_openai_response(result, model_name, "mlx")
