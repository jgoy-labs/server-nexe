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
import json
import logging
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest
from ._common import extract_last_user_msg, separate_messages, derive_session_id, build_openai_response, mark_served_model, resolve_loaded_model_name, persist_v1_turn
from ._streaming import TokenBridge, _prepend_chunk, format_engine_token, format_sse_done, SSE_DONE

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
    bridge = TokenBridge()

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
            error_chunk = {"error": _sanitize_sse_token(str(e))}
            yield f"data: {json.dumps(error_chunk)}\n\n"
            return

        # If the engine task failed, surface the error to the client instead of
        # closing with a normal "done". Previously the error was only logged
        # (bridge.error) and the stream ended clean → the user saw nothing.
        # This mirrors the Ollama path, which emits an error chunk on failure.
        if bridge.error:
            if not got_any_token:
                # #1036 (C2.4): nothing reached the client yet. This raise is
                # OUTSIDE the try/except above on purpose — it must propagate
                # as a real exception (not a yielded chunk) so the forwarder's
                # peek-before-first-byte can catch it and let the cascade
                # retry the next engine.
                raise RuntimeError(bridge.error)
            logger.error("MLX streaming error surfaced to client: %s", bridge.error)
            # #1040 (C2.4): the wire is already committed (tokens went out
            # before this failed) — persist what reached the client as a
            # PARTIAL turn instead of losing it from the mirrored session.
            persist_v1_turn(app_state, session_id, bridge.get_response_text(), partial=True)
            error_chunk = {"error": _sanitize_sse_token(str(bridge.error))}
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield SSE_DONE
            return

        # The engine's own reason (ceiling cut) travels in bridge.result, which
        # this path used to drop on the floor — the close always said "stop".
        # bridge._truncated is a DIFFERENT cut (queue overflow, B216); both
        # both collapse into "length", so the chunk carries x_nexe_truncation
        # to tell a missing TAIL from a missing MIDDLE (#989).
        yield format_sse_done(
            model_name,
            "mlx",
            truncated=bridge._truncated,
            finish_reason=(bridge.result or {}).get("finish_reason"),
        )
        yield SSE_DONE

        full_response_text = bridge.get_response_text()
        persist_v1_turn(app_state, session_id, full_response_text)

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

    if request.stream:
        logger.info("Forwarding to MLX module (streaming)...")
        agen = _mlx_stream_generator(
            mlx_module, user_messages, system_msg, model_name,
            app_state=req.app.state, user_msg=last_user_msg,
            session_id=session_id, max_tokens=request.max_tokens,
            temperature=request.temperature, top_p=request.top_p,
            cancel_event=cancel_event, images=images,
            thinking_enabled=request.wants_reasoning(),
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
        thinking_enabled=request.wants_reasoning(),  # ADR-010: off unless asked
    )
    return build_openai_response(result, model_name, "mlx")
