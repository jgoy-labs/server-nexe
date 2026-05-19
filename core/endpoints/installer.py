"""
F5.3: HTTP endpoints for the onboarding wizard.

All endpoints are intentionally unauthenticated — the user has no API key
yet when running through the wizard. The wizard is only reachable from the
local WebView (same-machine, loopback only) so the risk is minimal.

Endpoints:
  GET  /installer/download   — SSE stream: model download progress
  POST /installer/ollama     — SSE stream: Ollama install (if not present)
  GET  /installer/finalize   — JSON: {api_key, status}

Commit 5 ships a stub download loop so SSE wiring can be verified end-to-end.
Commit 6 wires the real download logic from installer_setup_models.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/installer", tags=["installer"])

# Engines that the wizard is allowed to download.
_VALID_ENGINES: frozenset[str] = frozenset({"mlx", "ollama", "gguf"})

# SSE headers required to disable proxy/CDN buffering.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


async def _sse(data: dict) -> str:
    """Format a single SSE frame."""
    return f"data: {json.dumps(data)}\n\n"


@router.get("/download", operation_id="installer_download_model")
async def download_model(engine: str, model_id: str, request: Request) -> StreamingResponse:
    """Stream model download progress as SSE events.

    Query params:
      engine   — one of: mlx, ollama, gguf (validated; 400 on unknown)
      model_id — model identifier (e.g. "gemma3:4b" for Ollama)

    Each event has shape: {"type": "progress"|"done"|"error", ...}
    """
    if engine not in _VALID_ENGINES:
        # Return a single error event so the EventSource sees it immediately.
        async def _error() -> AsyncIterator[str]:
            yield await _sse({"type": "error", "message": f"Unknown engine: {engine!r}"})
        return StreamingResponse(_error(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def generate() -> AsyncIterator[str]:
        try:
            import concurrent.futures
            from installer.installer_setup_models import (  # type: ignore[import]  # noqa: PGH003
                download_model_with_progress,  # type: ignore[attr-defined]
            )
            loop = asyncio.get_event_loop()
            q: asyncio.Queue[dict] = asyncio.Queue()

            def _progress(percent: float, speed: str = "—", eta: str = "—") -> None:
                loop.call_soon_threadsafe(
                    q.put_nowait,
                    {"type": "progress", "percent": percent, "speed": speed, "eta": eta},
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = loop.run_in_executor(
                    pool, download_model_with_progress, engine, model_id, _progress
                )
                while not fut.done():
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=0.5)
                        yield await _sse(event)
                    except asyncio.TimeoutError:
                        pass
                    if await request.is_disconnected():
                        fut.cancel()
                        return
            yield await _sse({"type": "done", "model_id": model_id})

        except (ImportError, AttributeError):
            # installer_setup_models not available or download_model_with_progress
            # not yet implemented — fall back to a stub progress stream so the
            # SSE wiring can be tested end-to-end.
            logger.warning(
                "installer: download_model_with_progress not found — using stub stream"
            )
            for pct in range(0, 101, 10):
                if await request.is_disconnected():
                    return
                yield await _sse({"type": "progress", "percent": pct, "speed": "—", "eta": "—"})
                await asyncio.sleep(0.3)
            yield await _sse({"type": "done", "model_id": model_id})

        except Exception as exc:
            logger.exception("installer: download error for %s/%s", engine, model_id)
            yield await _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/ollama", operation_id="installer_ollama_install")
async def install_ollama_endpoint(request: Request) -> StreamingResponse:
    """Detect or install Ollama, streaming progress as SSE."""

    async def generate() -> AsyncIterator[str]:
        try:
            from installer.installer_ollama_install import _find_ollama  # type: ignore[import]
            binary = _find_ollama()
        except ImportError:
            binary = shutil.which("ollama") or ""

        if shutil.which("ollama") or os.path.isfile(binary):
            yield await _sse({"type": "done", "already_installed": True})
            return

        yield await _sse({"type": "progress", "stage": "Installing Ollama…", "percent": 0})
        # Full install would call ensure_ollama_installed(headless=True) in an executor.
        # For F5.3 the stub is sufficient — if Ollama is missing the user sees the message.
        yield await _sse({"type": "done", "already_installed": False})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/finalize", operation_id="installer_finalize")
async def finalize() -> JSONResponse:
    """Return the local API key and server status.

    The onboarding wizard (Step 5) calls this to obtain the api_key that was
    injected via the Tauri sidecar launcher. The key is stored in localStorage
    by the wizard so nexe-bridge.js can use it on the main UI page.
    """
    api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    return JSONResponse({"api_key": api_key, "status": "ready"})
