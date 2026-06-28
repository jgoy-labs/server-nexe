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
from ._common import extract_last_user_msg, separate_messages, derive_session_id, build_openai_response, fallback_to_ollama, resolve_loaded_model_name
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
        # B075-C3: report the model that actually ran, not the client's
        # request.model (llama.cpp runs the single loaded GGUF, ignoring it).
        model_name = resolve_loaded_model_name(llama_module, "llama-cpp-local")

        if request.stream:
            return StreamingResponse(
                _llama_cpp_stream_generator(
                    llama_module, user_messages, system_msg, model_name,
                    app_state=req.app.state, user_msg=last_user_msg,
                    session_id=session_id, max_tokens=request.max_tokens,
                    temperature=request.temperature, top_p=request.top_p,
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )

        logger.info("Forwarding to Llama.cpp module...")
        result = await llama_module.chat(
            messages=user_messages, system=system_msg, session_id=session_id,
            max_tokens=request.max_tokens, temperature=request.temperature,
            top_p=request.top_p,
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
    top_p: Optional[float] = None,
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
                top_p=top_p,
            )
            bridge.set_done(result=result)
        except Exception as e:
            bridge.set_done(error=str(e))
            logger.error("Llama.cpp streaming error: %s", e, exc_info=True)

    llama_task = asyncio.create_task(run_llama())

    try:
        async for token in bridge:
            yield format_sse_chunk(token, model_name, "llamacpp")

        await llama_task

        # If the engine task failed, surface the error to the client instead of
        # closing with a normal "done". Previously the error was only logged
        # (bridge.error) and the stream ended clean → the user saw nothing.
        # This mirrors the Ollama path, which emits an error chunk on failure.
        if bridge.error:
            logger.error("Llama.cpp streaming error surfaced to client: %s", bridge.error)
            error_chunk = {"error": _sanitize_sse_token(str(bridge.error))}
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield SSE_DONE
            return

        yield format_sse_done(model_name, "llamacpp", truncated=bridge._truncated)
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
