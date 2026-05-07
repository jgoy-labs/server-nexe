"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/health.py
Description: Facade get_health() for the Ollama module.
             F7 FIX: Async health check (does not block the event loop).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from typing import Dict, Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]  # Module|None, httpx absent in environments without the dependency

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_HEALTH_TIMEOUT = float(os.getenv('NEXE_OLLAMA_HEALTH_TIMEOUT', '5.0'))


async def get_health_async() -> Dict[str, Any]:
    """
    ASYNC health check for the Ollama module (F7 fix).
    Does not block the event loop.
    """
    if httpx is None:
        return {
            "name": "ollama_module",
            "status": "DEGRADED",
            "connected": False,
            "error": "httpx not installed (pip install httpx)"
        }

    try:
        async with httpx.AsyncClient(timeout=min(OLLAMA_HEALTH_TIMEOUT, 3.0)) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            return {
                "name": "ollama_module",
                "status": "HEALTHY",
                "connected": True,
                "models_count": len(models),
                "base_url": OLLAMA_BASE_URL
            }
    except httpx.ConnectError:
        logger.warning("Ollama not reachable at %s", OLLAMA_BASE_URL)
        return {
            "name": "ollama_module",
            "status": "UNHEALTHY",
            "connected": False,
            "error": "Cannot connect to Ollama (not running?)",
            "base_url": OLLAMA_BASE_URL
        }
    except Exception as e:
        logger.error("Ollama health check failed: %s", e)
        return {
            "name": "ollama_module",
            "status": "ERROR",
            "connected": False,
            "error": str(e),
            "base_url": OLLAMA_BASE_URL
        }


def get_health() -> Dict[str, Any]:
    """
    Synchronous facade — delegates to get_health_async.
    If already inside an event loop, returns a basic result.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Inside event loop — return basic result without blocking
        return {
            "name": "ollama_module",
            "status": "unknown",
            "connected": None,
            "note": "Use get_health_async() from async context"
        }

    return asyncio.run(get_health_async())
