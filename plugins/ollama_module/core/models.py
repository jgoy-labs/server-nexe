"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/models.py
Description: Gestor de models Ollama — list, pull, info, delete.
             Extret de module.py durant normalitzacio BUS 2026-04-06.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List

from core.resilience import CircuitOpenError

from .errors import ModelNotFoundError, OllamaSemanticError

logger = logging.getLogger(__name__)


def _parent():
    """Lazy import del modul parent (tests patchen httpx/ollama_breaker alla).

    FIXME (post-release): Refactor tests to patch core/ instead of module/.
    Veure plugins/ollama_module/core/client.py per a la justificacio completa.
    """
    from plugins.ollama_module import module as _m
    return _m


class OllamaModels:
    """Gestio de models Ollama locals."""

    def __init__(self, client):
        self.client = client

    @property
    def base_url(self) -> str:
        return self.client.base_url

    async def list_models(self) -> List[Dict[str, Any]]:
        """List all available local models.

        Bug 15: ja no usa @ollama_breaker.protect directament perque aquest
        decorator registra qualsevol Exception com a failure. Fem el control
        manual per filtrar errors semantics 4xx (no infra) abans del breaker.
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
                # No tocar breaker — error d'aplicacio
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
                                logger.warning("JSON invalid a pull: %s", line)
        except httpx.HTTPStatusError as e:
            if p._is_semantic_http_error(e):
                logger.warning("Ollama pull semantic error %d for %s", e.response.status_code, model_name)
                if e.response.status_code == 404:
                    raise ModelNotFoundError(model_name) from e
                raise OllamaSemanticError(str(e), e.response.status_code) from e
            await ollama_breaker.record_failure(e)
            logger.error("Error descarregant model %s: %s", model_name, repr(e))
            raise
        except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
            await ollama_breaker.record_failure(e)
            logger.error("Error descarregant model %s: %s", model_name, repr(e))
            raise

    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Obte informacio detallada d'un model.

        Bug 15: gestio manual del circuit breaker per distingir 404 (model
        no trobat, error semantic) d'errors d'infraestructura. Un 404 NO ha
        d'obrir el breaker — re-llancem ModelNotFoundError perque el caller
        ho gestioni separadament.
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
        """Elimina un model local.

        Bug 15: gestio manual del breaker per filtrar 404 (model inexistent)
        com a error semantic, no infraestructura.
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
                logger.info("Model %s eliminat correctament", model_name)
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

    # --- Helpers injectats pel OllamaModule parent ---

    def _t(self, key: str, fallback: str, **kwargs) -> str:
        # Redirigit al modul pare si hi es, altrament fallback directe.
        owner = getattr(self, "_owner", None)
        if owner is not None:
            return owner._t(key, fallback, **kwargs)
        return fallback.format(**kwargs) if kwargs else fallback

    @property
    def _timeout(self) -> float:
        owner = getattr(self, "_owner", None)
        return owner.timeout if owner is not None else 600.0

    @property
    def _pull_timeout(self) -> float:
        owner = getattr(self, "_owner", None)
        return owner.pull_timeout if owner is not None else 600.0
