"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/health.py
Description: Health check per mòdul Ollama (opció local per LLM). Verifica

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from typing import Dict, Any

try:
  import httpx
except ImportError:
  httpx = None

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")

# Configurable timeout via environment variable
OLLAMA_HEALTH_TIMEOUT = float(os.getenv('NEXE_OLLAMA_HEALTH_TIMEOUT', '5.0'))

def get_health() -> Dict[str, Any]:
  """
  Comprova la salut del mòdul Ollama.

  Returns:
    Dict amb status, connected, models_count
  """
  if httpx is None:
    return {
      "name": "ollama_module",
      "status": "DEGRADED",
      "connected": False,
      "error": "httpx not installed (pip install httpx)"
    }

  try:
    with httpx.Client(timeout=OLLAMA_HEALTH_TIMEOUT) as client:
      response = client.get(f"{OLLAMA_BASE_URL}/api/tags")
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
    logger.error(f"Ollama health check failed: {e}")
    return {
      "name": "ollama_module",
      "status": "ERROR",
      "connected": False,
      "error": str(e),
      "base_url": OLLAMA_BASE_URL
    }