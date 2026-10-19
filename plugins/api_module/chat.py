"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/api_module/chat.py
Description: One chat request to an OpenAI-compatible provider, read back in
             the shape the turn already understands (Ollama's):
             {"message": {"content", "thinking"}, "done", "done_reason"}.

             The key travels in ONE header of ONE request. It is read at the
             moment of the call, held in a local, and never reaches a log, an
             exception text, a result or a repr; response bodies are never
             echoed either — a failure is a status code and a curated text
             (`errors.py`). Redirects are not followed (they would carry the
             Authorization header to another host).

             Reasoning: a provider that streams `reasoning_content` (DeepSeek's
             reasoner) has it mapped to `message.thinking`, the field every
             other engine's reasoning already uses, so `engine_events` splits
             it from the answer without a special case.

             Core imports are deferred (layering gate, #471).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .errors import ApiAuthError, ApiProviderError, ApiTimeout, ApiUnreachable

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120.0

#: How often a read in flight looks at the turn's cancel event. A deadline only
#: SETS the event (nothing cancels the asyncio task), so the read has to look.
CANCEL_POLL_SECONDS = 0.1


def request_timeout() -> httpx.Timeout:
    """Connect fast, wait as long as `NEXE_API_TIMEOUT` between two chunks."""
    try:
        read = float(os.environ.get("NEXE_API_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        read = DEFAULT_TIMEOUT_SECONDS
    if not 0 < read < float("inf"):  # also refuses nan: every comparison with it is False
        read = DEFAULT_TIMEOUT_SECONDS
    return httpx.Timeout(connect=10.0, read=read, write=30.0, pool=10.0)


def _image_mime(b64: str) -> str:
    """The MIME the image's own first bytes say; JPEG when they say nothing."""
    try:
        head = base64.b64decode(b64[:24] + "=" * (-len(b64[:24]) % 4))
    except (ValueError, TypeError):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def build_messages(messages: List[Dict[str, Any]], images: Optional[List[str]]) -> List[Dict[str, Any]]:
    """Only role and text leave the server (no stray keys), the turn's image
    attached to the last user message in the provider's content-part form."""
    out: List[Dict[str, Any]] = [
        {"role": str(m.get("role", "user")), "content": m.get("content") if isinstance(m.get("content"), str)
         else ("" if m.get("content") is None else str(m.get("content")))}
        for m in messages if isinstance(m, dict)
    ]
    if images:
        for message in reversed(out):
            if message["role"] == "user":
                parts: List[Dict[str, Any]] = [{"type": "text", "text": message["content"]}]
                parts += [{"type": "image_url", "image_url": {"url": f"data:{_image_mime(i)};base64,{i}"}}
                          for i in images]
                message["content"] = parts
                break
    return out


def where_you_run(messages: List[Dict[str, Any]], provider_name: str, model: str) -> List[Dict[str, Any]]:
    """The turn's messages with a closing note on the system message saying
    where this answer is produced.

    The base prompt says Nexe "runs 100% locally, zero cloud", which is true
    for a local engine and false here: asked who it was, the model answered it
    could not tell and might be local (live 13/10, Claude Sonnet 5.5 through
    the API). Only this engine knows the turn leaves the machine, so the note
    is added here and not in the shared prompt, whose prefix local engines
    cache. Nothing is changed in the caller's list.
    """
    note = (
        f"Where you run in THIS conversation: you answer through the cloud API of {provider_name}, "
        f"with the model {model}. The lines above saying that Nexe runs locally describe Nexe with a local "
        f"engine; here this conversation, its documents and its memory are sent to {provider_name}, "
        f"with the user's consent. If asked which model you are or where you run, say so plainly "
        f"and do not claim to be a different model."
    )
    out = [dict(m) if isinstance(m, dict) else m for m in messages]
    if out and isinstance(out[0], dict) and out[0].get("role") == "system" and isinstance(out[0].get("content"), str):
        out[0]["content"] = out[0]["content"].rstrip() + "\n\n" + note
    else:
        out.insert(0, {"role": "system", "content": note})
    return out


def build_payload(model: str, messages: List[Dict[str, Any]], stream: bool, top_p: Optional[float],
                  images: Optional[List[str]]) -> Dict[str, Any]:
    """No output ceiling is sent: `max_tokens` was renamed on some providers'
    newer models, and a refused parameter would fail a turn. The reply is
    bounded by the provider's own default and by NEXE_MAX_STREAM_MB.

    A streamed request asks for the closing usage event (`include_usage`):
    without it these providers send no token count in a stream, and the turn
    would show `null`/`~` where the provider could have said the real figure."""
    payload: Dict[str, Any] = {"model": model, "messages": build_messages(messages, images), "stream": bool(stream)}
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if top_p is not None:
        payload["top_p"] = top_p
    return payload


def _chunk(content: str = "", thinking: str = "", *, done: bool = False, reason: Optional[str] = None,
           usage: Any = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"message": {"role": "assistant", "content": content, "thinking": thinking}, "done": done}
    if isinstance(usage, dict):
        out["usage"] = usage  # what the provider says the call cost; the core reads it
    if done:
        out["done_reason"] = reason or "stop"
        out["continuable"] = False  # a provider cannot resume mid-sentence
    return out


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse_stream_event(event: Dict[str, Any], provider_name: str) -> Optional[Dict[str, Any]]:
    """One decoded SSE payload as a turn chunk, or None when it carries nothing."""
    if "error" in event:
        raise ApiProviderError(provider_name, 502)
    choices = event.get("choices")
    usage = event.get("usage")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        # The usage-only event that closes a stream (`include_usage`): no text, just the count.
        return _chunk(usage=usage) if isinstance(usage, dict) else None
    choice = choices[0]
    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
    content, thinking = _text(delta.get("content")), _text(delta.get("reasoning_content"))
    reason = choice.get("finish_reason")
    if reason:
        return _chunk(content, thinking, done=True, reason=str(reason), usage=usage)
    if content or thinking:
        return _chunk(content, thinking, usage=usage)
    return _chunk(usage=usage) if isinstance(usage, dict) else None


def parse_whole_reply(payload: Any, provider_name: str) -> Dict[str, Any]:
    """The reply of a non-streaming request as one final turn chunk."""
    if not isinstance(payload, dict) or "error" in payload:
        raise ApiProviderError(provider_name, 502)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ApiProviderError(provider_name, 502)
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    return _chunk(_text(message.get("content")), _text(message.get("reasoning_content")),
                  done=True, reason=str(choices[0].get("finish_reason") or "stop"), usage=payload.get("usage"))


def raise_for_status(status: int, provider_name: str) -> None:
    """Map a non-2xx status to a curated error. The body is never read."""
    if 200 <= status < 300:
        return
    if status in (401, 403):
        raise ApiAuthError(provider_name, status)
    raise ApiProviderError(provider_name, status)


async def _sse_events(response: httpx.Response) -> AsyncIterator[Dict[str, Any]]:
    async for raw in response.aiter_lines():
        line = raw.strip()
        if not line.startswith("data:"):
            continue  # blank separators and ": keep-alive" comments
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except ValueError:
            logger.debug("API stream: skipped a payload that is not JSON")
            continue
        if isinstance(event, dict):
            yield event


def _count(provider_key: str, status: str) -> None:
    try:
        from core.metrics.registry import API_ENGINE_REQUESTS  # deferred (layering gate)
        API_ENGINE_REQUESTS.labels(provider=provider_key, status=status).inc()
    except Exception:  # a metric must never fail a turn
        logger.debug("API engine metric not recorded", exc_info=True)


async def _until_cancelled(source: AsyncIterator[Any], cancel_event: Optional[Any]) -> AsyncIterator[Any]:
    """The items of `source` until `cancel_event` (a `threading.Event`) is set.

    The read in flight is CANCELLED, and `source` closed, which unwinds the
    `async with` blocks under it and closes the connection to the provider: a
    client that left, or a deadline, stops the bytes now instead of at the
    provider's own timeout. Without an event it is a plain pass-through.
    """
    if cancel_event is None:
        async for item in source:
            yield item
        return
    iterator = source.__aiter__()
    pending: Optional["asyncio.Future[Any]"] = None
    try:
        while not cancel_event.is_set():
            pending = asyncio.ensure_future(iterator.__anext__())
            while not pending.done() and not cancel_event.is_set():
                await asyncio.wait({pending}, timeout=CANCEL_POLL_SECONDS)
            if not pending.done():
                return
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            # `wait`, not `await pending`: it lets the read unwind without re-raising ITS cancellation here,
            # and a cancellation of our own (the consumer's task) still propagates instead of being swallowed.
            await asyncio.wait({pending})
            if not pending.cancelled():
                pending.exception()  # retrieved: what a read that was ending anyway raised is not ours to report
        await source.aclose()  # type: ignore[attr-defined]


async def _exchange(
    provider: Any, url: str, payload: Dict[str, Any], headers: Dict[str, str], stream: bool,
    transport: Optional[httpx.AsyncBaseTransport],
) -> AsyncIterator[Dict[str, Any]]:
    """One request to the provider, read back as the turn's chunks."""
    async with httpx.AsyncClient(timeout=request_timeout(), transport=transport, follow_redirects=False) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            raise_for_status(response.status_code, provider.name)
            if stream:
                async for event in _sse_events(response):
                    chunk = parse_stream_event(event, provider.name)
                    if chunk is not None:
                        yield chunk
            else:
                yield parse_whole_reply(json.loads(await response.aread()), provider.name)


async def run_chat(
    provider: Any, api_key: str, model: str, messages: List[Dict[str, Any]], stream: bool,
    images: Optional[List[str]], top_p: Optional[float], transport: Optional[httpx.AsyncBaseTransport],
    cancel_event: Optional[Any] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Send the request and yield the turn's chunks. Raises only curated errors.

    `cancel_event`: set, the read stops and the connection closes; what was
    already yielded stands, and nothing more is (not an error)."""
    url = provider.endpoint.rstrip("/") + provider.chat_path
    payload = build_payload(model, messages, stream, top_p, images)
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream" if stream else "application/json"}
    status = "ok"
    try:
        # `aclosing`: a consumer that walks away closes THIS generator, and an `async for` does not close the
        # generator it iterates (PEP 525): without it the connection would stay open until garbage collection.
        async with contextlib.aclosing(_until_cancelled(
            _exchange(provider, url, payload, headers, stream, transport), cancel_event,
        )) as chunks:
            async for chunk in chunks:
                yield chunk
        if cancel_event is not None and cancel_event.is_set():
            status = "cancelled"
    except GeneratorExit:
        status = "cancelled"  # the consumer walked away: not an error, and not a request that ran to its end
        raise
    except httpx.TimeoutException:
        status = "error"
        raise ApiTimeout(provider.name) from None
    except httpx.HTTPError:
        status = "error"
        raise ApiUnreachable(provider.name) from None
    except ValueError:
        status = "error"
        raise ApiProviderError(provider.name, 502) from None
    except Exception:
        # A refused key, a provider error: the curated errors pass through as they are.
        status = "error"
        raise
    finally:
        _count(provider.key, status)
