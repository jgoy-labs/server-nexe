"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/api/routes.py
Description: FastAPI endpoints for the Ollama module.
             Separated from manifest.py during normalisation.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
import os
import re
from fnmatch import fnmatch
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel, field_validator

import httpx

from plugins.security.core.validators import validate_safe_path
from plugins.security.core.auth import require_api_key
from plugins.ollama_module.core.errors import ModelNotFoundError, OllamaSemanticError

logger = logging.getLogger(__name__)


# Ollama supply-chain hardening.
#
# Ollama model names follow `[registry/]repo[:tag]`. We accept ASCII letters,
# digits, dots, underscores, hyphens and a single optional `:tag` suffix.
# This rejects shell metacharacters, whitespace, NUL bytes, URLs and any
# non-ASCII payload that could smuggle homoglyph registries.
#
# `\A...\Z` (not `^...$`) so a trailing newline does NOT pass: by default `$`
# matches before a final `\n`, which would let `qwen3\n; rm -rf /` slip through.
# Path-traversal `..` segments are rejected by an explicit check after the regex.
_OLLAMA_MODEL_NAME_RE = re.compile(r'\A[a-zA-Z0-9._\-/]+(:[a-zA-Z0-9._\-]+)?\Z')
_OLLAMA_MODEL_NAME_MAX_LEN = 200


def _ollama_allowlist_patterns() -> list[str] | None:
    """Read `NEXE_OLLAMA_ALLOWED_MODELS` at call-time (not import-time, so tests
    can monkeypatch without reload). Comma-separated fnmatch patterns.

    Returns `None` if the env var is unset/empty: only the format regex applies
    (permissive default, preserving current UX). Returns the parsed list when
    the operator opts in to a closed allowlist — typical operator value:
    `"qwen3*,llama3*,gemma*,mistral*"`.
    """
    raw = os.environ.get("NEXE_OLLAMA_ALLOWED_MODELS", "").strip()
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


class PullModelRequest(BaseModel):
    """Request to download a model"""
    name: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or len(v) > _OLLAMA_MODEL_NAME_MAX_LEN:
            raise ValueError("invalid model name length (1..200 ASCII chars)")
        if not _OLLAMA_MODEL_NAME_RE.match(v):
            raise ValueError(
                "invalid model name format — must match "
                "[a-zA-Z0-9._-/]+(:[a-zA-Z0-9._-]+)?"
            )
        # Defence-in-depth: reject path-traversal segments even though the
        # regex above already restricts the alphabet — the dots+slashes alone
        # could still spell `../`.
        if ".." in v:
            raise ValueError("path traversal segments ('..') not allowed in model name")
        allowlist = _ollama_allowlist_patterns()
        if allowlist is not None and not any(fnmatch(v, pat) for pat in allowlist):
            # B256: do not echo the user-supplied model name in the message. For a
            # custom field_validator Pydantic surfaces ``msg`` in the 422 body and
            # the error log; ``loc`` already identifies the offending field.
            raise ValueError(
                "model not in NEXE_OLLAMA_ALLOWED_MODELS allowlist"
            )
        return v


def create_router(module_instance) -> APIRouter:
    """
    Create the FastAPI router with all Ollama endpoints.

    Args:
        module_instance: OllamaModule instance
    """
    # Deferred (function-local) import: keeps the plugins -> core.resilience
    # edge OUT of the import-time layering baseline (finding #471 / check_layering).
    # Only used in the except clauses of the nested get_model_info / delete_model
    # handlers below; the closure captures it once per router creation.
    from core.resilience.circuit_breaker import CircuitOpenError

    router = APIRouter(prefix="/ollama")
    ui_path = Path(__file__).parent.parent / "ui"

    def _get_module():
        if module_instance is None:
            raise HTTPException(status_code=503, detail="OllamaModule not initialized")
        return module_instance

    # --- UI ---

    @router.get("/ui", response_class=HTMLResponse, operation_id="ollama_serve_ui")
    async def serve_ui():
        """Serves the Ollama chatbot web interface."""
        index_path = ui_path / "index.html"
        if not index_path.exists():
            return HTMLResponse(content="<h1>Ollama UI not found</h1>", status_code=404)
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content)

    @router.get("/ui/assets/css/{path:path}", operation_id="ollama_serve_css")
    async def serve_css(path: str):
        """Serves CSS files"""
        css_base = ui_path / "assets" / "css"
        safe_path = validate_safe_path(css_base / path, css_base)
        return FileResponse(safe_path, media_type="text/css")

    @router.get("/ui/assets/js/{path:path}", operation_id="ollama_serve_js")
    async def serve_js(path: str):
        """Serves JavaScript files from assets/js (matches index.html script src)"""
        js_base = ui_path / "assets" / "js"
        safe_path = validate_safe_path(js_base / path, js_base)
        return FileResponse(safe_path, media_type="application/javascript")

    # --- Models ---

    @router.get("/api/models", dependencies=[Depends(require_api_key)], operation_id="ollama_list_models")
    async def list_models():
        """Lists local Ollama models."""
        module = _get_module()
        try:
            models = await module.list_models()
            return {"status": "ok", "total": len(models), "models": models}
        except Exception as e:
            # MC-074: `str(e)` only in the log; the client gets a generic message.
            logger.error("Failed to list Ollama models: %s", e)
            raise HTTPException(status_code=503, detail="Ollama connection failed")

    @router.post("/api/pull", operation_id="ollama_pull_model")
    async def pull_model(request: PullModelRequest, _: str = Depends(require_api_key)):
        """Download Ollama model with streaming progress. Requires API key."""
        module = _get_module()

        async def progress_stream():
            try:
                async for progress in module.pull_model(request.name):
                    data = json.dumps(progress)
                    yield f"data: {data}\n\n"
            except Exception as e:
                # MC-074: don't leak `str(e)` into the SSE; generic message to the client.
                logger.error("Pull model failed: %s", e)
                yield f"data: {json.dumps({'error': 'Pull failed', 'status': 'error'})}\n\n"

        return StreamingResponse(
            progress_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    @router.get("/api/models/{model_name}/info", dependencies=[Depends(require_api_key)], operation_id="ollama_model_info")
    async def get_model_info(model_name: str):
        """Get detailed information about a model."""
        module = _get_module()
        try:
            info = await module.get_model_info(model_name)
            return {"status": "ok", "model": model_name, "info": info}
        except ModelNotFoundError:
            # MC-073: a non-existent model is 404 (not infra), generic message.
            raise HTTPException(status_code=404, detail="Model not found")
        except OllamaSemanticError as e:
            # MC-073: semantic 4xx from Ollama → propagate its status, without `str(e)`.
            logger.error("Ollama semantic error for model info %s: %s", model_name, e)
            raise HTTPException(status_code=e.status_code, detail="Ollama request error")
        except (CircuitOpenError, httpx.HTTPError, ConnectionError, TimeoutError) as e:
            # MC-073: infrastructure error → 503, not 404; `str(e)` only in the log.
            logger.error("Ollama unavailable for model info %s: %s", model_name, e)
            raise HTTPException(status_code=503, detail="Ollama service unavailable")
        except Exception as e:
            logger.error("Unexpected error getting model info %s: %s", model_name, e, exc_info=True)
            raise HTTPException(status_code=500, detail="Internal error")

    @router.delete("/api/models/{model_name}", operation_id="ollama_delete_model")
    async def delete_model(model_name: str, _: str = Depends(require_api_key)):
        """Delete a local model. Requires API key."""
        module = _get_module()
        try:
            await module.delete_model(model_name)
            return {"status": "ok", "message": f"Model {model_name} deleted successfully"}
        except ModelNotFoundError:
            # MC-074: deleting a non-existent model is 404, not 500.
            raise HTTPException(status_code=404, detail="Model not found")
        except (CircuitOpenError, httpx.HTTPError, ConnectionError, TimeoutError) as e:
            logger.error("Ollama unavailable for delete %s: %s", model_name, e)
            raise HTTPException(status_code=503, detail="Ollama service unavailable")
        except Exception as e:
            # MC-074: `str(e)` only in the log; generic message to the client.
            logger.error("Failed to delete model %s: %s", model_name, e, exc_info=True)
            raise HTTPException(status_code=500, detail="Delete failed")

    # --- Health & Info ---

    @router.get("/health", dependencies=[Depends(require_api_key)], operation_id="ollama_health")
    async def health():
        """Health check for the Ollama module."""
        module = _get_module()
        result = await module.health_check()
        return result.to_dict()

    @router.get("/info", dependencies=[Depends(require_api_key)], operation_id="ollama_info")
    async def info():
        """Information about the Ollama module."""
        module = _get_module()
        return module.get_info()

    return router
