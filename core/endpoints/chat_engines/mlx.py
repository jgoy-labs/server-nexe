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
import hashlib
import json
import logging
import time
import uuid
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..chat_memory import _pending_save_tasks
from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest
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
            )
            bridge.set_done(result=result)
        except Exception as e:
            bridge.set_done(error=str(e))
            logger.error("MLX streaming error: %s", e)

    mlx_task = asyncio.create_task(run_mlx())

    try:
        async for token in bridge:
            yield format_sse_chunk(token, model_name, "mlx")

        await mlx_task

        yield format_sse_done(model_name, "mlx")
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
    try:
        # Get MLX module from app state
        mlx_module = None
        if hasattr(req.app.state, 'modules'):
            mlx_module = req.app.state.modules.get('mlx_module')

        last_user_msg = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )

        if not mlx_module or not hasattr(mlx_module, 'chat'):
            # MLX module not loaded or not available - fallback to Ollama
            logger.warning("MLX module not available (Metal/model not configured). Falling back to Ollama.")
            logger.info("To use MLX: Set NEXE_MLX_MODEL in .env and ensure Metal is available")
            from .ollama import _forward_to_ollama
            return await _forward_to_ollama(
                messages,
                request,
                app_state=req.app.state,
                user_msg=last_user_msg,
                fallback_from="mlx",
                fallback_reason="module_unavailable",
            )

        # Prepare messages for MLX
        system_msg = ""
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                user_messages.append(msg)

        model_name = request.model or "mlx-local"

        # Derive session_id from X-Session-Id header or API key hash
        _api_key = (req.headers.get("x-api-key") or req.headers.get("authorization", "")).encode()
        session_id = req.headers.get("x-session-id") or f"sess_{hashlib.sha256(_api_key).hexdigest()[:16]}"

        # STREAMING MODE
        if request.stream:
            logger.info("Forwarding to MLX module (streaming)...")
            return StreamingResponse(
                _mlx_stream_generator(
                    mlx_module,
                    user_messages,
                    system_msg,
                    model_name,
                    app_state=req.app.state,
                    user_msg=last_user_msg,
                    session_id=session_id,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # NON-STREAMING MODE
        logger.info("Forwarding to MLX module...")
        result = await mlx_module.chat(
            messages=user_messages,
            system=system_msg,
            session_id=session_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        return {
            "id": f"mlx-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": _sanitize_sse_token(result.get("response", ""))
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("tokens", 0),
                "total_tokens": result.get("context_used", 0)
            }
        }

    except Exception as e:
        logger.error("MLX execution failed: %s. Falling back to Ollama.", e)
        from .ollama import _forward_to_ollama
        return await _forward_to_ollama(
            messages,
            request,
            app_state=req.app.state,
            user_msg=last_user_msg,
            fallback_from="mlx",
            fallback_reason="execution_failed",
        )
