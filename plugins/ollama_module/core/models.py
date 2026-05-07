"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/models.py
Description: Ollama model manager — list, pull, info, delete.
             Extracted from module.py during BUS normalisation 2026-04-06.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List

from core.resilience import CircuitOpenError

from .errors import ModelNotFoundError, OllamaSemanticError

logger = logging.getLogger(__name__)


def _parent():
    """Lazy import of the parent module (tests patch httpx/ollama_breaker there).

    FIXME (post-release): Refactor tests to patch core/ instead of module/.
    See plugins/ollama_module/core/client.py for the full justification.
    """
    from plugins.ollama_module import module as _m
    return _m


class OllamaModels:
    """Management of local Ollama models."""

    def __init__(self, client):
        self.client = client

    @property
    def base_url(self) -> str:
        return self.client.base_url

    async def list_models(self) -> List[Dict[str, Any]]:
        """List all available local models.

        Bug 15: no longer uses @ollama_breaker.protect directly because that
        decorator records any Exception as a failure. We do manual control
        to filter semantic 4xx errors (non-infra) before the breaker.
        """
        p = _parent()
        httpx = p.httpx
        ollama_breaker = p.ollama_breaker

        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
                models = data.get("models", [])
                msg = self._t("logs.models_found", "Found {count} Ollama models", count=len(models))
                logger.info(msg)
                await ollama_breaker.record_success()
                return models
        except httpx.HTTPStatusError as e:
            if p._is_semantic_http_error(e):
                # Do not touch breaker — application error
                raise
            await ollama_breaker.record_failure(e)
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            raise

    async def pull_model(self, model_name: str) -> AsyncIterator[Dict[str, Any]]:
        """Download an Ollama model (streaming progress)."""
        p = _parent()
        httpx = p.httpx
        ollama_breaker = p.ollama_breaker

        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )

        try:
            async with httpx.AsyncClient(timeout=self._pull_timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/pull", json={"name": model_name}
                ) as response:
                    response.raise_for_status()
                    await ollama_breaker.record_success()
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                yield data
                            except json.JSONDecodeError:
                                logger.warning("Invalid JSON in pull: %s", line)
        except httpx.HTTPStatusError as e:
            if p._is_semantic_http_error(e):
                logger.warning("Ollama pull semantic error %d for %s", e.response.status_code, model_name)
                if e.response.status_code == 404:
                    raise ModelNotFoundError(model_name) from e
                raise OllamaSemanticError(str(e), e.response.status_code) from e
            await ollama_breaker.record_failure(e)
            logger.error("Error downloading model %s: %s", model_name, repr(e))
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            logger.error("Error downloading model %s: %s", model_name, repr(e))
            raise

    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Retrieves detailed information about a model.

        Bug 15: manual circuit breaker management to distinguish 404 (model
        not found, semantic error) from infrastructure errors. A 404 must NOT
        open the breaker — we re-raise ModelNotFoundError so the caller
        can handle it separately.
        """
        p = _parent()
        httpx = p.httpx
        ollama_breaker = p.ollama_breaker

        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/show", json={"name": model_name}
                )
                response.raise_for_status()
                await ollama_breaker.record_success()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Ollama model not found: %s", model_name)
                raise ModelNotFoundError(model_name) from e
            if p._is_semantic_http_error(e):
                logger.warning("Ollama semantic error %d for model %s", e.response.status_code, model_name)
                raise OllamaSemanticError(str(e), e.response.status_code) from e
            await ollama_breaker.record_failure(e)
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            raise

    async def delete_model(self, model_name: str) -> bool:
        """Deletes a local model.

        Bug 15: manual breaker management to filter 404 (non-existent model)
        as a semantic error, not infrastructure.
        """
        p = _parent()
        httpx = p.httpx
        ollama_breaker = p.ollama_breaker

        if not await ollama_breaker.check_circuit():
            raise CircuitOpenError(
                f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
            )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.delete(
                    f"{self.base_url}/api/delete", json={"name": model_name}
                )
                response.raise_for_status()
                logger.info("Model %s deleted successfully", model_name)
                await ollama_breaker.record_success()
                return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ModelNotFoundError(model_name) from e
            if p._is_semantic_http_error(e):
                raise OllamaSemanticError(str(e), e.response.status_code) from e
            await ollama_breaker.record_failure(e)
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            raise

    # --- Helpers injected by the parent OllamaModule ---

    def _t(self, key: str, fallback: str, **kwargs) -> str:
        # Delegated to the parent module if present, otherwise direct fallback.
        owner = getattr(self, "_owner", None)
        if owner is not None:
            return owner._t(key, fallback, **kwargs)
        return fallback.format(**kwargs) if kwargs else fallback

    @property
    def _timeout(self):
        httpx = _parent().httpx  # lazy-import pattern maintained for tests patch
        owner = getattr(self, "_owner", None)
        if owner is not None and getattr(owner, "timeout", None) is not None:
            return owner.timeout
        return httpx.Timeout(
            connect=float(os.getenv("NEXE_OLLAMA_CONNECT_TIMEOUT", "5.0")),
            read=float(os.getenv("NEXE_OLLAMA_MODELS_READ_TIMEOUT", "60.0")),
            write=float(os.getenv("NEXE_OLLAMA_WRITE_TIMEOUT", "10.0")),
            pool=float(os.getenv("NEXE_OLLAMA_POOL_TIMEOUT", "5.0")),
        )

    @property
    def _pull_timeout(self) -> float:
        owner = getattr(self, "_owner", None)
        return owner.pull_timeout if owner is not None else 600.0
