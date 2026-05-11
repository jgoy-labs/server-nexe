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
import json
import logging
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..chat_memory import _pending_save_tasks
from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest
from ._common import extract_last_user_msg, separate_messages, derive_session_id, build_openai_response, fallback_to_ollama
from ._streaming import TokenBridge, format_sse_chunk, format_sse_done, SSE_DONE, background_memory_save

logger = logging.getLogger(__name__)


async def _forward_to_llama_cpp(messages: List[Dict], request: ChatCompletionRequest, req: Request):
    """Forward to Llama.cpp module (GGUF models)."""
    last_user_msg = extract_last_user_msg(messages)

    try:
        llama_module = None
        if hasattr(req.app.state, 'modules'):
            llama_module = req.app.state.modules.get('llama_cpp_module')

        if not llama_module or not hasattr(llama_module, 'chat'):
            logger.warning("Llama.cpp module not available (model not configured). Falling back to Ollama.")
            logger.info("To use Llama.cpp: Set NEXE_LLAMA_CPP_MODEL in .env")
            return await fallback_to_ollama(messages, request, req.app.state, last_user_msg, "llama_cpp", "module_unavailable")

        system_msg, user_messages = separate_messages(messages)
        session_id = derive_session_id(req)
        model_name = request.model or "llama-cpp-local"

        if request.stream:
            return StreamingResponse(
                _llama_cpp_stream_generator(
                    llama_module, user_messages, system_msg, model_name,
                    app_state=req.app.state, user_msg=last_user_msg,
                    session_id=session_id, max_tokens=request.max_tokens,
                    temperature=request.temperature,
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        logger.info("Forwarding to Llama.cpp module...")
        result = await llama_module.chat(
            messages=user_messages, system=system_msg, session_id=session_id,
            max_tokens=request.max_tokens, temperature=request.temperature,
        )
        return build_openai_response(result, model_name, "llamacpp")

    except Exception as e:
        logger.error("Llama.cpp execution failed: %s. Falling back to Ollama.", e)
        return await fallback_to_ollama(messages, request, req.app.state, last_user_msg, "llama_cpp", "execution_failed")

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
):
    """SSE generator for Llama.cpp streaming.

    Uses :class:`TokenBridge` to bridge the synchronous llama.cpp callback
    to the async generator that FastAPI requires.
    """
    bridge = TokenBridge()

    async def run_llama():
        try:
            result = await llama_module.chat(
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
            logger.error("Llama.cpp streaming error: %s", e)

    llama_task = asyncio.create_task(run_llama())

    try:
        async for token in bridge:
            yield format_sse_chunk(token, model_name, "llamacpp")

        await llama_task

        yield format_sse_done(model_name, "llamacpp")
        yield SSE_DONE

        full_response_text = bridge.get_response_text()
        if app_state and user_msg and full_response_text.strip():
            task = asyncio.create_task(background_memory_save(app_state, user_msg, full_response_text))
            _pending_save_tasks.add(task)
            task.add_done_callback(_pending_save_tasks.discard)

    except asyncio.CancelledError:
        logger.debug("Llama.cpp stream cancelled (client disconnected)")
        return
    except Exception as e:
        logger.exception("Llama.cpp streaming failed")
        error_chunk = {"error": _sanitize_sse_token(str(e))}
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        if not llama_task.done():
            llama_task.cancel()
