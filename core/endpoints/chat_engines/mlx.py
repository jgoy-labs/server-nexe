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

from ..chat_memory import _pending_save_tasks
from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest
from ._common import extract_last_user_msg, separate_messages, derive_session_id, build_openai_response, fallback_to_ollama, resolve_loaded_model_name
from ._streaming import TokenBridge, format_sse_chunk, format_sse_done, SSE_DONE, background_memory_save

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
):
    """SSE generator for MLX streaming.

    Uses :class:`TokenBridge` to bridge the synchronous MLX callback
    to the async generator that FastAPI requires.
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
            )
            bridge.set_done(result=result)
        except Exception as e:
            bridge.set_done(error=str(e))
            logger.error("MLX streaming error: %s", e, exc_info=True)

    mlx_task = asyncio.create_task(run_mlx())

    try:
        async for token in bridge:
            yield format_sse_chunk(token, model_name, "mlx")

        await mlx_task

        # If the engine task failed, surface the error to the client instead of
        # closing with a normal "done". Previously the error was only logged
        # (bridge.error) and the stream ended clean → the user saw nothing.
        # This mirrors the Ollama path, which emits an error chunk on failure.
        if bridge.error:
            logger.error("MLX streaming error surfaced to client: %s", bridge.error)
            error_chunk = {"error": _sanitize_sse_token(str(bridge.error))}
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield SSE_DONE
            return

        yield format_sse_done(model_name, "mlx", truncated=bridge._truncated)
        yield SSE_DONE

        full_response_text = bridge.get_response_text()
        if app_state and user_msg and full_response_text.strip():
            task = asyncio.create_task(background_memory_save(app_state, user_msg, full_response_text))
            _pending_save_tasks.add(task)
            task.add_done_callback(_pending_save_tasks.discard)

        if bridge.result:
            logger.info(
                "MLX stream completed: %d tokens, %.1f tok/s",
                bridge.result.get("tokens", 0),
                bridge.result.get("tokens_per_second", 0),
            )

    except asyncio.CancelledError:
        logger.debug("MLX stream cancelled (client disconnected)")
        return
    except Exception as e:
        logger.exception("MLX streaming failed")
        error_chunk = {"error": _sanitize_sse_token(str(e))}
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        if not mlx_task.done():
            mlx_task.cancel()


async def _forward_to_mlx(messages: List[Dict], request: ChatCompletionRequest, req: Request):
    """Forward to MLX module (Apple Silicon optimized)."""
    last_user_msg = extract_last_user_msg(messages)

    try:
        mlx_module = None
        if hasattr(req.app.state, 'modules'):
            mlx_module = req.app.state.modules.get('mlx_module')

        if not mlx_module or not hasattr(mlx_module, 'chat'):
            logger.warning("MLX module not available (Metal/model not configured). Falling back to Ollama.")
            logger.info("To use MLX: Set NEXE_MLX_MODEL in .env and ensure Metal is available")
            return await fallback_to_ollama(messages, request, req.app.state, last_user_msg, "mlx", "module_unavailable")

        system_msg, user_messages = separate_messages(messages)
        session_id = derive_session_id(req)
        # B075-C3: report the model that actually ran, not the client's
        # request.model (MLX runs the single loaded model, ignoring the param).
        model_name = resolve_loaded_model_name(mlx_module, "mlx-local")

        if request.stream:
            logger.info("Forwarding to MLX module (streaming)...")
            return StreamingResponse(
                _mlx_stream_generator(
                    mlx_module, user_messages, system_msg, model_name,
                    app_state=req.app.state, user_msg=last_user_msg,
                    session_id=session_id, max_tokens=request.max_tokens,
                    temperature=request.temperature, top_p=request.top_p,
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        logger.info("Forwarding to MLX module...")
        result = await mlx_module.chat(
            messages=user_messages, system=system_msg, session_id=session_id,
            max_tokens=request.max_tokens, temperature=request.temperature,
            top_p=request.top_p,
        )
        return build_openai_response(result, model_name, "mlx")

    except Exception as e:
        logger.error("MLX execution failed: %s. Falling back to Ollama.", e)
        return await fallback_to_ollama(messages, request, req.app.state, last_user_msg, "mlx", "execution_failed")
