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
from .ollama_helpers import auto_num_ctx

logger = logging.getLogger(__name__)

# CS4: Cache for Ollama /api/tags — avoid HTTP call on every chat request
_ollama_tags_cache: dict = {"models": None, "ts": 0.0}
TAGS_CACHE_TTL = 30  # seconds

# CS7: Configurable stream timeout via env var (default 300s for thinking models)
_OLLAMA_STREAM_TIMEOUT = float(os.environ.get("NEXE_OLLAMA_STREAM_TIMEOUT", "300"))

_OLLAMA_NUM_CTX = auto_num_ctx()

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


def _resolve_ollama_model(request, app_state) -> str:
    """Cascade: request.model → NEXE_OLLAMA_MODEL → NEXE_DEFAULT_MODEL (no URL) → config → 'llama3.2'."""
    model_name = request.model
    if not model_name:
        model_name = os.environ.get("NEXE_OLLAMA_MODEL")
    if not model_name:
        # Legacy: NEXE_DEFAULT_MODEL may be an HF URL or path — ignore it for Ollama.
        # read via runtime_state so a UI selection wins.
        from core.runtime_state import get_with_env_fallback
        _default = get_with_env_fallback("NEXE_DEFAULT_MODEL", "")
        if _default and not _default.startswith(("http", "/", "~", "storage/")):
            model_name = _default
    if not model_name and app_state:
        config = getattr(app_state, "config", {}) or {}
        model_name = config.get("plugins", {}).get("models", {}).get("primary")
    return model_name or "llama3.2"


async def _fetch_ollama_available_models(host: str) -> list:
    """Fetch model list from Ollama /api/tags, using cache if fresh. Raises HTTPException on failure."""
    _now = time.time()
    if _ollama_tags_cache["models"] is not None and (_now - _ollama_tags_cache["ts"]) < TAGS_CACHE_TTL:
        return _ollama_tags_cache["models"]

    async with httpx.AsyncClient(timeout=3.0) as client:
        tags_resp = await client.get(f"{host}/api/tags")
        if tags_resp.status_code != 200:
            from core.messages import get_message as _core_msg
            raise HTTPException(status_code=502, detail=_core_msg(None, "core.ollama.http_error", status=tags_resp.status_code))
        available_models = [m.get("name", "") for m in tags_resp.json().get("models", [])]
        _ollama_tags_cache["models"] = available_models
        _ollama_tags_cache["ts"] = _now
        return available_models


def _filter_chat_models(available_models: list) -> list:
    """Return only chat-capable models (exclude embedding models)."""
    EMBEDDING_MODELS = {"nomic-embed", "mxbai-embed", "all-minilm", "bge-", "embed"}
    return [m for m in available_models if not any(emb in m.lower() for emb in EMBEDDING_MODELS)]


def _resolve_model_name(model_name: str, available_models: list, chat_models: list) -> str:
    """Resolve the final model name, applying partial-match fallback. Raises HTTPException if not found.

    Bug 23 (2026-04-06): raise 404/503 instead of silent fallback.
    """
    if model_name in available_models or f"{model_name}:latest" in available_models:
        return model_name

    matching = [m for m in chat_models if model_name.split(":")[0] in m]
    if matching:
        model_name = matching[0]
        logger.info("Using available model: %s", model_name)
        return model_name

    _lang = os.getenv("NEXE_LANG", "en").split("-")[0].lower()
    if chat_models:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Model '{model_name}' not found. "
                f"Available chat models: {', '.join(chat_models[:5])}"
            ),
        )
    raise HTTPException(
        status_code=503,
        detail=_OLLAMA_ERRORS.get(_lang, _OLLAMA_ERRORS["en"])["no_model"]
    )


async def _validate_ollama_model(host: str, model_name: str) -> tuple[str, list]:
    """Verifies the model exists in Ollama. Returns (model_name_final, chat_models).
    Raises HTTPException if Ollama is unavailable or model not found."""
    try:
        available_models = await _fetch_ollama_available_models(host)
        # Filter out embedding models (they can't chat!) — runs on BOTH cache hit and miss
        chat_models = _filter_chat_models(available_models)
        model_name = _resolve_model_name(model_name, available_models, chat_models)
    except httpx.ConnectError:
        _lang = os.getenv("NEXE_LANG", "en").split("-")[0].lower()
        raise HTTPException(
            status_code=503,
            detail=_OLLAMA_ERRORS.get(_lang, _OLLAMA_ERRORS["en"])["unavailable"]
        )
    return model_name, chat_models


def _build_ollama_payload(request, messages: List[Dict], model_name: str) -> dict:
    """Builds the payload for the Ollama API."""
    return {
        "model": model_name,
        "messages": messages,
        "stream": request.stream,
        "think": os.getenv("NEXE_OLLAMA_THINK", "false").lower() == "true",  # NEVER default true — 400 on non-thinking models
        "options": {
            "temperature": request.temperature,
            "num_predict": request.max_tokens or int(os.getenv("NEXE_DEFAULT_MAX_TOKENS", "4096")),
            "num_ctx": _OLLAMA_NUM_CTX
        }
    }


def _ollama_streaming_response(
    url: str, payload: dict, app_state, user_msg,
    fallback_from: Optional[str], fallback_reason: Optional[str]
) -> StreamingResponse:
    """Builds and returns the StreamingResponse with fallback headers if applicable."""
    headers = {"X-Nexe-Engine": "ollama"}
    if fallback_from:
        headers["X-Nexe-Fallback-From"] = fallback_from
        headers["X-Nexe-Fallback-Reason"] = fallback_reason or "fallback"
    return StreamingResponse(
        _ollama_stream_generator(url, payload, app_state, user_msg),
        media_type="text/event-stream",
        headers=headers,
    )


async def _ollama_blocking_response(
    url: str, payload: dict,
    fallback_from: Optional[str], fallback_reason: Optional[str]
) -> dict:
    """Blocking POST to Ollama + conversion to OpenAI format + error handling."""
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
        from core.messages import get_message as _core_msg
        raise HTTPException(
            status_code=503,
            detail=_core_msg(None, "core.ollama.not_responding")
        )


async def _forward_to_ollama(
    messages: List[Dict],
    request: ChatCompletionRequest,
    app_state=None,
    user_msg: Optional[str] = None,
    fallback_from: Optional[str] = None,
    fallback_reason: Optional[str] = None,
):
    """Forward request to local Ollama instance."""
    _ollama_host = os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    url = f"{_ollama_host}/api/chat"
    model_name = _resolve_ollama_model(request, app_state)
    model_name, _ = await _validate_ollama_model(_ollama_host, model_name)  # raises status_code=404 if not found, 503 if unavailable
    payload = _build_ollama_payload(request, messages, model_name)
    if request.stream:
        return _ollama_streaming_response(url, payload, app_state, user_msg, fallback_from, fallback_reason)
    return await _ollama_blocking_response(url, payload, fallback_from, fallback_reason)

async def _ollama_stream_generator(url: str, payload: dict, app_state=None, user_msg: Optional[str] = None):
    """OpenAI-compatible streaming generator from Ollama with Auto-Save support."""
    response_parts = []

    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_STREAM_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    err_str = _sanitize_sse_token(f"Ollama stream failed with status {resp.status_code}")
                    yield f"data: {json.dumps({'error': err_str})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        # Ollama returns JSON lines
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
        _lang = os.getenv("NEXE_LANG", "en").split("-")[0].lower()
        error_msg = {"error": _sanitize_sse_token(_OLLAMA_ERRORS.get(_lang, _OLLAMA_ERRORS["en"])["stream_unavailable"])}
        yield f"data: {json.dumps(error_msg)}\n\n"
        yield "data: [DONE]\n\n"
