"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/chat.py
Description: Chat Ollama — inference amb streaming i directa.
             Extret de module.py durant normalitzacio BUS 2026-04-06.

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


def _parent():
    """Lazy import del modul parent (tests patchen httpx/ollama_breaker alla).

    FIXME (post-release): Refactor tests to patch core/ instead of module/.
    Veure plugins/ollama_module/core/client.py per a la justificacio completa.
    """
    from plugins.ollama_module import module as _m
    return _m


class OllamaChat:
    """Motor de chat Ollama (streaming + directa)."""

    def __init__(self, client):
        self.client = client

    @property
    def base_url(self) -> str:
        return self.client.base_url

    def _build_payload(self, model: str, messages: List[Dict[str, str]], stream: bool, images: Optional[List[str]] = None) -> Dict[str, Any]:
        """Construeix el payload /api/chat."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "stop": STOP_SEQUENCES,
            "keep_alive": os.getenv("NEXE_OLLAMA_KEEP_ALIVE", "30m"),
            "think": os.getenv("NEXE_OLLAMA_THINK", "true").lower() == "true",
            "options": {
                "num_ctx": auto_num_ctx(),
            },
        }
        if images:
            payload["images"] = images
        return payload

    async def chat(
        self, model: str, messages: List[Dict[str, str]], stream: bool = True,
        images: Optional[List[str]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Chat amb model Ollama (streaming o directe). images: base64 strings opcionals."""
        p = _parent()
        httpx = p.httpx
        ollama_breaker = p.ollama_breaker

        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )

        try:
            payload = self._build_payload(model, messages, stream, images=images)

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                if stream:
                    async with client.stream(
                        "POST", f"{self.base_url}/api/chat", json=payload
                    ) as response:
                        response.raise_for_status()
                        await ollama_breaker.record_success()
                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    data = json.loads(line)
                                    yield data
                                except json.JSONDecodeError:
                                    logger.warning("JSON invalid a chat: %s", line)
                else:
                    response = await client.post(
                        f"{self.base_url}/api/chat", json=payload
                    )
                    response.raise_for_status()
                    await ollama_breaker.record_success()
                    yield response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Ollama chat: model %s not found (404)", model)
                raise ModelNotFoundError(model) from e
            if p._is_semantic_http_error(e):
                logger.warning("Ollama chat semantic error %d for %s", e.response.status_code, model)
                raise OllamaSemanticError(str(e), e.response.status_code) from e
            await ollama_breaker.record_failure(e)
            logger.error("Chat fallida amb model %s: %s", model, repr(e))
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            logger.error("Chat fallida amb model %s: %s", model, repr(e))
            raise

    @property
    def _timeout(self):
        httpx = _parent().httpx  # lazy-import pattern mantingut per a tests patch
        owner = getattr(self, "_owner", None)
        if owner is not None and getattr(owner, "timeout", None) is not None:
            return owner.timeout
        return httpx.Timeout(
            connect=float(os.getenv("NEXE_OLLAMA_CONNECT_TIMEOUT", "5.0")),
            read=float(os.getenv("NEXE_OLLAMA_READ_TIMEOUT", "600.0")),
            write=float(os.getenv("NEXE_OLLAMA_WRITE_TIMEOUT", "10.0")),
            pool=float(os.getenv("NEXE_OLLAMA_POOL_TIMEOUT", "5.0")),
        )
