"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/health.py
Description: Facade get_health() per al modul Ollama.
             F7 FIX: Async health check (no bloqueja event loop).

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
    httpx = None

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_HEALTH_TIMEOUT = float(os.getenv('NEXE_OLLAMA_HEALTH_TIMEOUT', '5.0'))


async def get_health_async() -> Dict[str, Any]:
    """
    Health check ASYNC del modul Ollama (F7 fix).
    No bloqueja l'event loop.
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
    Facade sincrona — delega a get_health_async.
    Si ja dins event loop, retorna resultat basic.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Dins event loop — retornem basic sense bloquejar
        return {
            "name": "ollama_module",
            "status": "unknown",
            "connected": None,
            "note": "Use get_health_async() from async context"
        }

    return asyncio.run(get_health_async())
