"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/chat.py
Description: Ollama Chat — streaming and direct inference.
             Extracted from module.py during BUS normalisation 2026-04-06.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

from core.endpoints.chat_engines.ollama_helpers import auto_num_ctx
from core.resilience import CircuitOpenError

from .errors import ModelNotFoundError, OllamaSemanticError

logger = logging.getLogger(__name__)

STOP_SEQUENCES = [
    "<|end|>", "<|endoftext|>", "</s>",
    "<|eot_id|>", "<end_of_turn>", "<|im_end|>",
]

# Families that support think:true in Ollama without returning 400.
# Update when new thinking-capable models are released.
THINKING_CAPABLE = {
    "qwen3.5", "qwen3", "qwq",
    "deepseek-r1", "deepseek-r1-distill",
    "gemma3", "gemma4",
    "llama4",
    "gpt-oss",
}


def can_think(model: str) -> bool:
    """Return True if the model supports think:true in Ollama without 400."""
    name = model.split("/")[-1].split(":")[0].lower()
    return any(family in name for family in THINKING_CAPABLE)


def _parent():
    """Lazy import of the parent module (tests patch httpx/ollama_breaker there).

    FIXME (post-release): Refactor tests to patch core/ instead of module/.
    See plugins/ollama_module/core/client.py for the full justification.
    """
    from plugins.ollama_module import module as _m
    return _m


class OllamaChat:
    """Ollama chat engine (streaming + direct)."""

    def __init__(self, client):
        self.client = client

    @property
    def base_url(self) -> str:
        return self.client.base_url

    def _build_payload(self, model: str, messages: List[Dict[str, str]], stream: bool,
                       images: Optional[List[str]] = None, thinking_enabled: bool = False,
                       top_p: Optional[float] = None) -> Dict[str, Any]:
        """Builds the /api/chat payload."""
        # Env var override (global) takes precedence if explicitly set
        env_think = os.getenv("NEXE_OLLAMA_THINK")
        if env_think is not None:
            effective_think = env_think.lower() == "true"
        else:
            # Per-session thinking intersected with model capability (safety belt)
            effective_think = thinking_enabled and can_think(model)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "stop": STOP_SEQUENCES,
            "keep_alive": os.getenv("NEXE_OLLAMA_KEEP_ALIVE", "30m"),
            "think": effective_think,
            "options": {
                "num_ctx": auto_num_ctx(),
            },
        }
        # Opt-in nucleus sampling (mirror of the /v1 path): forward only when set
        # so omitting it preserves the prior payload (Ollama uses its own default).
        if top_p is not None:
            payload["options"]["top_p"] = top_p
        if images:
            # Ollama /api/chat: images must go inside the last user message
            # (not at the top-level — that is the format of /api/generate, not /api/chat)
            for i in range(len(payload["messages"]) - 1, -1, -1):
                if payload["messages"][i].get("role") == "user":
                    payload["messages"][i] = dict(payload["messages"][i])
                    payload["messages"][i]["images"] = images
                    break
        return payload

    async def _stream_request(self, httpx, ollama_breaker, url: str, payload: Dict[str, Any]):
        """Execute a streaming POST and yield parsed JSON lines."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                await ollama_breaker.record_success()
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON in chat: %s", line)

    async def _direct_request(self, httpx, ollama_breaker, url: str, payload: Dict[str, Any]):
        """Execute a non-streaming POST and yield the single JSON response."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            await ollama_breaker.record_success()
            yield response.json()

    @staticmethod
    def _starved_by_thinking(chunk: Dict[str, Any], saw_content: bool, saw_thinking: bool) -> bool:
        """True when this final chunk ends a turn that reasoned and never answered (#984).

        Ollama keeps reasoning in ``message.thinking`` and the answer in
        ``message.content``, so the two are told apart without parsing tags: a
        turn that stopped at the ceiling having produced only the former holds
        nothing the user can read. Measured on qwen3.5:4b, where a trivial
        question spends ~3100 tokens reasoning and 25 answering.
        """
        return (
            bool(chunk.get("done"))
            and chunk.get("done_reason") == "length"
            and saw_thinking
            and not saw_content
        )

    async def _generate_with_answer_guarantee(
        self, httpx, ollama_breaker, url: str, payload: Dict[str, Any],
        stream: bool, model: str,
    ):
        """Yield the turn's chunks, retrying once without thinking if it starved.

        The final chunk of a starved turn is held back rather than forwarded:
        it carries ``done``, and a consumer that sees it stops listening. If
        the retry itself fails, that held chunk is released so the turn ends
        the way it would have without this guarantee — degraded, never hung.
        """
        source = self._stream_request if stream else self._direct_request
        saw_content = saw_thinking = False
        held = None
        async for chunk in source(httpx, ollama_breaker, url, payload):
            message = chunk.get("message") or {}
            saw_content = saw_content or bool(message.get("content"))
            saw_thinking = saw_thinking or bool(message.get("thinking"))
            if self._starved_by_thinking(chunk, saw_content, saw_thinking):
                held = chunk
                break
            yield chunk
        if held is None:
            return
        try:
            async for chunk in self._retry_without_thinking(
                httpx, ollama_breaker, url, payload, stream, model,
                reason="the ceiling ended the turn inside the reasoning (#984)",
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001 — degrade, never hang the turn
            await ollama_breaker.record_failure(exc)
            logger.error(
                "Chat retry (no-think, #984) failed with model %s: %s — releasing "
                "the reasoning-only turn", model, repr(exc),
            )
            yield held

    async def _retry_without_thinking(self, httpx, ollama_breaker, url: str,
                                      payload: Dict[str, Any], stream: bool, model: str,
                                      reason: str = "the model rejects think:true (400)"):
        """Retry the request with think:false.

        Two callers: a 400 from a model that cannot think at all, and #984's
        answer guarantee when reasoning ate the whole ceiling.
        """
        logger.warning("Retrying model %s without thinking — %s", model, reason)
        payload["think"] = False
        if stream:
            async for chunk in self._stream_request(httpx, ollama_breaker, url, payload):
                yield chunk
        else:
            async for chunk in self._direct_request(httpx, ollama_breaker, url, payload):
                yield chunk

    async def chat(
        self, model: str, messages: List[Dict[str, str]], stream: bool = True,
        images: Optional[List[str]] = None, thinking_enabled: bool = False,
        top_p: Optional[float] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Chat with Ollama model (streaming or direct). images: optional base64 strings."""
        p = _parent()
        httpx = p.httpx
        ollama_breaker = p.ollama_breaker

        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )

        url = f"{self.base_url}/api/chat"
        # Build payload outside try so it's always bound in the except clause.
        payload = self._build_payload(model, messages, stream, images=images,
                                      thinking_enabled=thinking_enabled, top_p=top_p)
        try:
            async for chunk in self._generate_with_answer_guarantee(
                httpx, ollama_breaker, url, payload, stream, model
            ):
                yield chunk

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and payload.get("think"):
                # B119: the retry runs INSIDE this except clause, so a failure
                # here would bypass record_failure (sibling except clauses don't
                # catch each other) and leave the circuit breaker blind to real
                # infra failures during the retry. Guard it explicitly.
                try:
                    async for chunk in self._retry_without_thinking(
                        httpx, ollama_breaker, url, payload, stream, model
                    ):
                        yield chunk
                except Exception as retry_exc:
                    await ollama_breaker.record_failure(retry_exc)
                    logger.error("Chat retry (no-think) failed with model %s: %s", model, repr(retry_exc))
                    raise
                return
            if e.response.status_code == 404:
                logger.warning("Ollama chat: model %s not found (404)", model)
                raise ModelNotFoundError(model) from e
            if p._is_semantic_http_error(e):
                logger.warning("Ollama chat semantic error %d for %s", e.response.status_code, model)
                raise OllamaSemanticError(str(e), e.response.status_code) from e
            await ollama_breaker.record_failure(e)
            logger.error("Chat failed with model %s: %s", model, repr(e))
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            logger.error("Chat failed with model %s: %s", model, repr(e))
            raise

    @property
    def _timeout(self):
        httpx = _parent().httpx  # lazy-import pattern maintained for tests patch
        owner = getattr(self, "_owner", None)
        if owner is not None and getattr(owner, "timeout", None) is not None:
            return owner.timeout
        return httpx.Timeout(
            connect=float(os.getenv("NEXE_OLLAMA_CONNECT_TIMEOUT", "5.0")),
            read=float(os.getenv("NEXE_OLLAMA_READ_TIMEOUT", "600.0")),
            write=float(os.getenv("NEXE_OLLAMA_WRITE_TIMEOUT", "10.0")),
            pool=float(os.getenv("NEXE_OLLAMA_POOL_TIMEOUT", "5.0")),
        )
