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

from core.ollama_utils import resolve_ollama_url
from ..chat_sanitization import _sanitize_sse_token
from ..chat_schemas import ChatCompletionRequest
from ._common import mark_served_model
from .ollama_helpers import auto_num_ctx
from ._streaming import MAX_STREAM_BYTES, NEXE_END, _close_agen, _prepend_chunk, stream_end

logger = logging.getLogger(__name__)

# CS4: Cache for Ollama /api/tags — avoid HTTP call on every chat request
_ollama_tags_cache: dict = {"models": None, "ts": 0.0}
TAGS_CACHE_TTL = 30  # seconds

# CS7: Configurable stream timeout via env var (default 300s for thinking models)
def _ollama_stream_timeout() -> float:
    """Seconds the /v1 Ollama stream may run. Guarded: this module is imported
    at boot, so a typo used to be a boot failure (same class as #978)."""
    raw = os.environ.get("NEXE_OLLAMA_STREAM_TIMEOUT", "300")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("NEXE_OLLAMA_STREAM_TIMEOUT=%r is not a number — using 300", raw)
        return 300.0
    if value != value or value <= 0.0:
        logger.warning("NEXE_OLLAMA_STREAM_TIMEOUT=%r must be positive — using 300", raw)
        return 300.0
    return value


_OLLAMA_STREAM_TIMEOUT = _ollama_stream_timeout()

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


def _think_for(request) -> bool:
    """ADR-010: the request decides (off unless asked); `NEXE_OLLAMA_THINK`,
    when set, still overrides it for this whole door, as it always has.

    A resume wins over both: `think:true` opens a new reasoning channel and
    the prefix stops being the cut answer. Same rule as the plugin's
    `continue_final`.
    """
    # `is True`: a MagicMock request grows a truthy `.resume` and would force
    # think off on every ordinary payload this door builds.
    if getattr(request, "resume", False) is True:
        return False
    env = os.getenv("NEXE_OLLAMA_THINK")
    if env is not None and env.strip():
        return env.strip().lower() == "true"
    wants = getattr(request, "wants_reasoning", None)
    return callable(wants) and wants() is True


def _without_think(payload: dict) -> Optional[dict]:
    """The same request with reasoning off, for a model that refuses it (the
    web UI's plugin has retried this way since B119); None if already off."""
    if not payload.get("think"):
        return None
    logger.warning("Retrying model %s without thinking — it rejects think:true (400)", payload.get("model"))
    return {**payload, "think": False}


def _build_ollama_payload(
    request, messages: List[Dict], model_name: str, images: Optional[List[str]] = None,
) -> dict:
    """Builds the payload for the Ollama API.

    `images` (#1081): Ollama's `/api/chat` wants them INSIDE the last
    user message, not as a top-level payload key (that shape is
    `/api/generate`'s). Duplicated from
    `plugins/ollama_module/core/chat.py::OllamaChat._build_payload` rather
    than imported: this is `core/`, that is a plugin, and `core -> plugins`
    is the one direction the layering gate forbids.
    """
    options = {
        "temperature": request.temperature,
        "num_predict": request.max_tokens or int(os.getenv("NEXE_DEFAULT_MAX_TOKENS", "4096")),
        "num_ctx": auto_num_ctx(),
    }
    # top_p is opt-in (mirror of temperature): forward only when explicitly set so
    # omitting it preserves Ollama's own default (byte-exact with prior behavior).
    # `is not None` (never truthiness); schema enforces gt=0.0 so 0.0 never reaches here.
    if request.top_p is not None:
        options["top_p"] = request.top_p
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": request.stream,
        "think": _think_for(request),
        "options": options
    }
    if images:
        for i in range(len(payload["messages"]) - 1, -1, -1):
            if payload["messages"][i].get("role") == "user":
                payload["messages"][i] = dict(payload["messages"][i])
                payload["messages"][i]["images"] = images
                break
        else:
            # No user turn to attach them to: the images would leave this
            # function without ever reaching Ollama. The llama.cpp module
            # warns in the same situation; this copy used to be the silent
            # one of the three.
            logger.warning(
                "Ollama payload: %d image(s) dropped — no user message to attach them to",
                len(images),
            )
    return payload


async def _ollama_streaming_response(
    url: str, payload: dict, app_state, user_msg,
    fallback_from: Optional[str], fallback_reason: Optional[str],
    session_id: Optional[str] = None,
) -> StreamingResponse:
    """Peek the first chunk, then build the StreamingResponse.

    Same as MLX and llama.cpp (#1036): a failure before any token raises out
    of this call, so the cascade can still answer with HTTP instead of an SSE
    error the client only sees after a 200.
    """
    headers = {"X-Nexe-Engine": "ollama"}
    if fallback_from:
        headers["X-Nexe-Fallback-From"] = fallback_from
        headers["X-Nexe-Fallback-Reason"] = fallback_reason or "fallback"
    agen = _ollama_stream_generator(url, payload, app_state, user_msg, session_id=session_id)
    try:
        first = await agen.__anext__()
    except StopAsyncIteration:
        await _close_agen(agen)
        raise RuntimeError("Ollama produced no stream")
    end = first.get(NEXE_END) if isinstance(first, dict) else None
    if isinstance(end, dict) and end.get("failure"):
        await _close_agen(agen)
        raise RuntimeError(end["failure"])
    # #1054: the name is already in the payload this stream was built from.
    return mark_served_model(StreamingResponse(
        _prepend_chunk(first, agen),
        media_type="text/event-stream",
        headers=headers,
    ), payload.get("model") or "")


def _openai_message(message: dict) -> dict:
    """Ollama's message in the OpenAI shape: its native `thinking` becomes
    `reasoning` (ADR-010) instead of travelling as an unknown key."""
    out = {"role": message.get("role", "assistant"),
           "content": _sanitize_sse_token(message.get("content", "") or "")}
    if message.get("thinking"):
        out["reasoning"] = _sanitize_sse_token(message["thinking"])
    return out


def _reasoning_sse(data: dict) -> tuple[str, int]:
    """ADR-010: Ollama's native reasoning on one stream line, as a
    `delta.reasoning` chunk, and its size for the B104 byte cap (which the
    answer's branch enforces on the running total; `num_predict` bounds a
    generation that only reasons)."""
    thinking = _sanitize_sse_token(data.get("message", {}).get("thinking", "") or "")
    if not thinking:
        return "", 0
    size = len(thinking.encode("utf-8", errors="replace"))
    return f"data: {json.dumps({'choices': [{'delta': {'reasoning': thinking}}]})}\n\n", size


async def _ollama_blocking_response(
    url: str, payload: dict,
    fallback_from: Optional[str], fallback_reason: Optional[str]
) -> dict:
    """Blocking POST to Ollama + conversion to OpenAI format + error handling."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=_OLLAMA_STREAM_TIMEOUT)
            retry = _without_think(payload) if resp.status_code == 400 else None
            if retry is not None:
                resp = await client.post(url, json=retry, timeout=_OLLAMA_STREAM_TIMEOUT)
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
                    "message": _openai_message(raw.get("message") or {}),
                    # A blocking call only returns once generation is over, so
                    # `done` is always True and cannot tell why it stopped.
                    # Ollama puts the reason in `done_reason` — the same field
                    # the UI path reads to offer Continue. Reporting "stop" on a
                    # ceiling cut makes an OpenAI client drop the tail silently.
                    "finish_reason": "length" if raw.get("done_reason") == "length" else "stop",
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
    session_id: Optional[str] = None,
    images: Optional[List[str]] = None,
):
    """Forward request to local Ollama instance."""
    # MC-089: honour the full cascade (SidecarConfig → NEXE_OLLAMA_HOST →
    # OLLAMA_HOST → default), same as warmup/health, not NEXE_OLLAMA_HOST-only.
    _ollama_host = resolve_ollama_url()
    url = f"{_ollama_host}/api/chat"
    model_name = _resolve_ollama_model(request, app_state)
    model_name, _ = await _validate_ollama_model(_ollama_host, model_name)  # raises status_code=404 if not found, 503 if unavailable
    payload = _build_ollama_payload(request, messages, model_name, images=images)
    if request.stream:
        return await _ollama_streaming_response(
            url, payload, app_state, user_msg, fallback_from, fallback_reason, session_id=session_id
        )
    return await _ollama_blocking_response(url, payload, fallback_from, fallback_reason)

def _ollama_stream_gate(resp, payload: dict) -> Optional[dict]:
    """A 400 that was the think flag is a payload to send again.

    Any other non-200 raises before a token, so the peek can still answer
    with HTTP. `None` means this response is the stream to read.
    """
    retry = _without_think(payload) if resp.status_code == 400 else None
    if retry is not None:
        return retry
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Ollama returned HTTP {resp.status_code}",
        )
    return None


def _ollama_line_events(data: dict, response_bytes: int) -> tuple[int, list, str]:
    """One Ollama JSON line, as SSE strings plus at most one sentinel.

    The status is `open` (keep reading), `capped` (byte cap, stop) or
    `done` (Ollama closed the generation). The byte total includes reasoning.
    """
    events: list = []
    reasoning_sse, reasoning_bytes = _reasoning_sse(data)
    response_bytes += reasoning_bytes
    if reasoning_sse:
        events.append(reasoning_sse)

    content = _sanitize_sse_token(data.get("message", {}).get("content", ""))
    if content:
        # B104: hard byte cap, symmetric with TokenBridge.
        response_bytes += len(content.encode("utf-8", errors="replace"))
        if response_bytes > MAX_STREAM_BYTES:
            logger.warning(
                "Ollama stream cap reached (%d bytes > %d). Terminating early.",
                response_bytes, MAX_STREAM_BYTES,
            )
            events.append(stream_end(failure="stream_cap_exceeded", truncated=True))
            return response_bytes, events, "capped"
        chunk = {"choices": [{"delta": {"content": content}}]}
        events.append(f"data: {json.dumps(chunk)}\n\n")

    if data.get("done", False):
        # `done_reason` is the ceiling cut. Absence is a clean stop, and
        # the turn's emit writes it.
        reason = data.get("done_reason")
        events.append(stream_end(finish_reason="length" if reason == "length" else None))
        return response_bytes, events, "done"
    return response_bytes, events, "open"


async def _ollama_stream_generator(
    url: str, payload: dict, app_state=None, user_msg: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """Tokens from Ollama, then one `stream_end` sentinel.

    `[DONE]`, the final chunk and persistence belong to the turn (C4.6-b).
    A non-200 or a connection error before the first token raises, so the
    caller — which peeks — can still answer with HTTP. `user_msg` stays in
    the signature: `test_user_msg_signatures_regression.py` pins it.
    """
    _response_bytes = 0
    got_any = False

    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_STREAM_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                retry = _ollama_stream_gate(resp, payload)
                if retry is not None:
                    async for chunk in _ollama_stream_generator(url, retry, app_state, user_msg, session_id=session_id):
                        yield chunk
                    return

                ended = False
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as jde:
                        logger.debug("Ollama stream: JSON decode error on line: %s", jde)
                        continue
                    _response_bytes, events, status = _ollama_line_events(data, _response_bytes)
                    for event in events:
                        got_any = True
                        yield event
                    if status != "open":
                        ended = True
                        return
                if not ended:
                    yield stream_end()
    except asyncio.CancelledError:
        logger.debug("Ollama stream cancelled (client disconnected)")
        return
    except httpx.ConnectError:
        if got_any:
            yield stream_end(failure="ollama_unavailable")
            return
        from core.messages import get_message as _core_msg
        raise HTTPException(
            status_code=503,
            detail=_core_msg(None, "core.ollama.not_responding"),
        )
