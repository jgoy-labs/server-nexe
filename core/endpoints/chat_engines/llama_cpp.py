"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/endpoints/chat_engines/llama_cpp.py
Description: Llama.cpp (GGUF) engine integration for Chat endpoint.

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

from ..chat_memory import _pending_save_tasks, _save_conversation_to_memory
from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest

logger = logging.getLogger(__name__)


async def _forward_to_llama_cpp(messages: List[Dict], request: ChatCompletionRequest, req: Request):
    """Forward to Llama.cpp module (GGUF models)."""
    try:
        # Get llama_cpp module from app state
        llama_module = None
        if hasattr(req.app.state, 'modules'):
            llama_module = req.app.state.modules.get('llama_cpp_module')

        last_user_msg = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )

        if not llama_module or not hasattr(llama_module, 'chat'):
            # Llama.cpp module not loaded - fallback to Ollama
            logger.warning("Llama.cpp module not available (model not configured). Falling back to Ollama.")
            logger.info("To use Llama.cpp: Set NEXE_LLAMA_CPP_MODEL in .env")
            from .ollama import _forward_to_ollama
            return await _forward_to_ollama(
                messages,
                request,
                app_state=req.app.state,
                user_msg=last_user_msg,
                fallback_from="llama_cpp",
                fallback_reason="module_unavailable",
            )

        # Prepare messages for llama.cpp
        system_msg = ""
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                user_messages.append(msg)

        # Derive session_id from X-Session-Id header or API key hash
        _api_key = (req.headers.get("x-api-key") or req.headers.get("authorization", "")).encode()
        session_id = req.headers.get("x-session-id") or f"sess_{hashlib.sha256(_api_key).hexdigest()[:16]}"

        if request.stream:
            model_name = request.model or "llama-cpp-local"
            return StreamingResponse(
                _llama_cpp_stream_generator(
                    llama_module,
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

        # Call llama.cpp module
        logger.info("Forwarding to Llama.cpp module...")
        result = await llama_module.chat(
            messages=user_messages,
            system=system_msg,
            session_id=session_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        # Convert llama.cpp response to OpenAI format
        return {
            "id": f"llamacpp-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model or "llama-cpp-local",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result.get("response", "")
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
        logger.error("Llama.cpp execution failed: %s. Falling back to Ollama.", e)
        from .ollama import _forward_to_ollama
        return await _forward_to_ollama(
            messages,
            request,
            app_state=req.app.state,
            user_msg=last_user_msg,
            fallback_from="llama_cpp",
            fallback_reason="execution_failed",
        )

async def _llama_cpp_stream_generator(
    llama_module,
    user_messages: List[Dict],
    system_msg: str,
    model_name: str,
    app_state=None,
    user_msg: str = None,
    session_id: str = "chat_session",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
):
    """
    Generator SSE per Llama.cpp streaming.

    Usa asyncio.Queue per fer pont entre el callback de llama.cpp
    i l'async generator que necessita FastAPI.
    """
    tokens_queue: asyncio.Queue = asyncio.Queue(maxsize=2048)
    loop = asyncio.get_running_loop()
    generation_done = asyncio.Event()
    result_holder = {"result": None, "error": None}
    response_parts_llama = []

    def on_token(token: str):
        """Callback cridat per cada token generat (des de thread)."""
        response_parts_llama.append(token)
        try:
            loop.call_soon_threadsafe(
                tokens_queue.put_nowait,
                token
            )
        except Exception as e:
            logger.warning("Llama.cpp stream token enqueue failed (queue full/closed): %s", e)

    async def run_llama():
        """Executa Llama.cpp en background amb stream_callback."""
        try:
            result = await llama_module.chat(
                messages=user_messages,
                system=system_msg,
                session_id=session_id,
                stream_callback=on_token,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            result_holder["result"] = result
        except Exception as e:
            result_holder["error"] = str(e)
            logger.error("Llama.cpp streaming error: %s", e)
        finally:
            generation_done.set()

    llama_task = asyncio.create_task(run_llama())

    try:
        while not generation_done.is_set() or not tokens_queue.empty():
            try:
                token = await asyncio.wait_for(
                    tokens_queue.get(),
                    timeout=0.1
                )
                chunk = {
                    "id": f"llamacpp-stream-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": _sanitize_sse_token(token)},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            except asyncio.TimeoutError:
                if generation_done.is_set() and tokens_queue.empty():
                    break

        await llama_task

        final_chunk = {
            "id": f"llamacpp-stream-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

        full_response_text = "".join(response_parts_llama)
        if app_state and user_msg and full_response_text.strip():
            async def _background_save_llama():
                for attempt in range(2):
                    try:
                        await _save_conversation_to_memory(app_state, user_msg, full_response_text)
                        return
                    except Exception as e:
                        if attempt == 0:
                            await asyncio.sleep(1)
                        else:
                            logger.error("Llama.cpp Stream Auto-Save failed after retry: %s", e)
            task = asyncio.create_task(_background_save_llama())
            _pending_save_tasks.add(task)
            task.add_done_callback(_pending_save_tasks.discard)

    except asyncio.CancelledError:
        logger.debug("Llama.cpp stream cancelled (client disconnected)")
        return
    except Exception as e:
        logger.exception("Llama.cpp streaming failed")
        error_chunk = {"error": str(e)}
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        if not llama_task.done():
            llama_task.cancel()
