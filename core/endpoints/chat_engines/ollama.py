"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/ollama.py
Description: Ollama engine integration for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..chat_memory import _pending_save_tasks, _save_conversation_to_memory
from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest

logger = logging.getLogger(__name__)

# CS4: Cache for Ollama /api/tags — avoid HTTP call on every chat request
_ollama_tags_cache: dict = {"models": None, "ts": 0.0}
TAGS_CACHE_TTL = 30  # seconds

# CS7: Configurable stream timeout via env var (default 300s for thinking models)
_OLLAMA_STREAM_TIMEOUT = float(os.environ.get("NEXE_OLLAMA_STREAM_TIMEOUT", "300"))

_OLLAMA_ERRORS = {
    "ca": {
        "no_model": "No hi ha cap model de CHAT descarregat a Ollama. Executa: ollama pull llama3.2",
        "unavailable": "Ollama no disponible. El servidor s'està iniciant o Ollama no està instal·lat. Espera uns segons i torna-ho a provar, o executa: curl -fsSL https://ollama.com/install.sh | sh",
        "stream_unavailable": "Ollama no disponible. Espera uns segons i torna-ho a provar.",
    },
    "es": {
        "no_model": "No hay ningún modelo de CHAT descargado en Ollama. Ejecuta: ollama pull llama3.2",
        "unavailable": "Ollama no disponible. El servidor se está iniciando o Ollama no está instalado. Espera unos segundos y vuelve a intentarlo, o ejecuta: curl -fsSL https://ollama.com/install.sh | sh",
        "stream_unavailable": "Ollama no disponible. Espera unos segundos y vuelve a intentarlo.",
    },
    "en": {
        "no_model": "No CHAT model downloaded in Ollama. Run: ollama pull llama3.2",
        "unavailable": "Ollama unavailable. Server is starting or Ollama is not installed. Wait a few seconds and retry, or run: curl -fsSL https://ollama.com/install.sh | sh",
        "stream_unavailable": "Ollama unavailable. Wait a few seconds and retry.",
    },
}


async def _forward_to_ollama(
    messages: List[Dict],
    request: ChatCompletionRequest,
    app_state=None,
    user_msg: str = None,
    fallback_from: Optional[str] = None,
    fallback_reason: Optional[str] = None,
):
    """Forward request to local Ollama instance."""
    _ollama_host = os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    url = f"{_ollama_host}/api/chat"

    # Get model from: request > NEXE_OLLAMA_MODEL > NEXE_DEFAULT_MODEL (if not a URL) > config > fallback
    model_name = request.model
    if not model_name:
        model_name = os.environ.get("NEXE_OLLAMA_MODEL")
    if not model_name:
        # Legacy: NEXE_DEFAULT_MODEL pot ser una URL HF o path — ignorar-la per Ollama
        _default = os.environ.get("NEXE_DEFAULT_MODEL", "")
        if _default and not _default.startswith(("http", "/", "~", "storage/")):
            model_name = _default
    if not model_name and app_state:
        config = getattr(app_state, "config", {}) or {}
        model_name = config.get("plugins", {}).get("models", {}).get("primary")
    if not model_name:
        model_name = "llama3.2"  # Last resort fallback

    # Check if Ollama is available before trying to connect
    try:
        _now = time.time()
        if _ollama_tags_cache["models"] is not None and (_now - _ollama_tags_cache["ts"]) < TAGS_CACHE_TTL:
            available_models = _ollama_tags_cache["models"]
        else:
            async with httpx.AsyncClient(timeout=3.0) as client:
                tags_resp = await client.get(f"{_ollama_host}/api/tags")
                if tags_resp.status_code != 200:
                     raise HTTPException(status_code=502, detail=f"Ollama error (HTTP {tags_resp.status_code})")
                available_models = [m.get("name", "") for m in tags_resp.json().get("models", [])]
                _ollama_tags_cache["models"] = available_models
                _ollama_tags_cache["ts"] = _now

        # Filter out embedding models (they can't chat!) — runs on BOTH cache hit and miss
        EMBEDDING_MODELS = {"nomic-embed", "mxbai-embed", "all-minilm", "bge-", "embed"}
        chat_models = [m for m in available_models
                      if not any(emb in m.lower() for emb in EMBEDDING_MODELS)]

        # Verify the model exists
        if model_name not in available_models and f"{model_name}:latest" not in available_models:
            # Try to find a partial match in chat models only
            matching = [m for m in chat_models if model_name.split(":")[0] in m]
            if matching:
                model_name = matching[0]
                logger.info("Using available model: %s", model_name)
            elif chat_models:
                # Use first available chat model as fallback
                model_name = chat_models[0]
                logger.warning("Requested model not found. Using available model: %s", model_name)
            else:
                _lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()
                raise HTTPException(
                    status_code=503,
                    detail=_OLLAMA_ERRORS.get(_lang, _OLLAMA_ERRORS["en"])["no_model"]
                )
    except httpx.ConnectError:
        _lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()
        raise HTTPException(
            status_code=503,
            detail=_OLLAMA_ERRORS.get(_lang, _OLLAMA_ERRORS["en"])["unavailable"]
        )

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": request.stream,
        "options": {
            "temperature": request.temperature,
            "num_predict": request.max_tokens or int(os.getenv("NEXE_DEFAULT_MAX_TOKENS", "4096"))
        }
    }

    if request.stream:
        headers = {"X-Nexe-Engine": "ollama"}
        if fallback_from:
            headers["X-Nexe-Fallback-From"] = fallback_from
            headers["X-Nexe-Fallback-Reason"] = fallback_reason or "fallback"
        return StreamingResponse(
            _ollama_stream_generator(url, payload, app_state, user_msg),
            media_type="text/event-stream",
            headers=headers,
        )
    else:
        # Blocking call
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=_OLLAMA_STREAM_TIMEOUT)
                if resp.status_code != 200:
                    try:
                        error_detail = resp.json().get("error", "Unknown Ollama error")
                    except (ValueError, json.JSONDecodeError, AttributeError):
                        error_detail = f"Ollama returned HTTP {resp.status_code}"
                    raise HTTPException(status_code=resp.status_code, detail=error_detail)
                raw = resp.json()
                # Convert Ollama native format to OpenAI-compatible format
                response = {
                    "id": f"chatcmpl-{raw.get('created_at', '')}",
                    "object": "chat.completion",
                    "model": raw.get("model", ""),
                    "choices": [{
                        "index": 0,
                        "message": raw.get("message", {"role": "assistant", "content": ""}),
                        "finish_reason": "stop" if raw.get("done") else "length",
                    }],
                    "usage": {
                        "prompt_tokens": raw.get("prompt_eval_count", 0),
                        "completion_tokens": raw.get("eval_count", 0),
                        "total_tokens": (raw.get("prompt_eval_count", 0) or 0) + (raw.get("eval_count", 0) or 0),
                    },
                    "nexe_engine": "ollama",
                }
                if fallback_from:
                    response["nexe_fallback"] = {
                        "from": fallback_from, "to": "ollama", "reason": fallback_reason or "fallback",
                    }
                return response
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail="Ollama not responding. Verify it is running: ollama serve"
            )

async def _ollama_stream_generator(url: str, payload: dict, app_state=None, user_msg: str = None):
    """OpenAI-compatible streaming generator from Ollama with Auto-Save support."""
    response_parts = []

    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_STREAM_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    yield f"data: {json.dumps({'error': f'Ollama stream failed with status {resp.status_code}'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line: continue
                    try:
                        # Ollama retorna JSON lines
                        data = json.loads(line)
                        content = _sanitize_sse_token(data.get("message", {}).get("content", ""))
                        done = data.get("done", False)

                        if content:
                            response_parts.append(content)
                            # Wrap in OpenAI-like SSe format for our client convenience
                            chunk = {
                                "choices": [{"delta": {"content": content}}]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"

                        if done:
                            yield "data: [DONE]\n\n"
                            # --- TRIGGER AUTO-SAVE (fire-and-forget) ---
                            full_response_text = "".join(response_parts)
                            if app_state and user_msg and full_response_text.strip():
                                async def _background_save_ollama():
                                    for attempt in range(2):
                                        try:
                                            await _save_conversation_to_memory(app_state, user_msg, full_response_text)
                                            return
                                        except Exception as e:
                                            if attempt == 0:
                                                await asyncio.sleep(1)
                                            else:
                                                logger.error("Stream Auto-Save failed after retry: %s", e)
                                task = asyncio.create_task(_background_save_ollama())
                                _pending_save_tasks.add(task)
                                task.add_done_callback(_pending_save_tasks.discard)
                            break

                    except json.JSONDecodeError as jde:
                        logger.debug("Ollama stream: JSON decode error on line: %s", jde)
    except asyncio.CancelledError:
        # Client disconnected during streaming — clean exit, no error.
        logger.debug("Ollama stream cancelled (client disconnected)")
        return
    except httpx.ConnectError:
        _lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()
        error_msg = {"error": _OLLAMA_ERRORS.get(_lang, _OLLAMA_ERRORS["en"])["stream_unavailable"]}
        yield f"data: {json.dumps(error_msg)}\n\n"
        yield "data: [DONE]\n\n"
