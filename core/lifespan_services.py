"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_services.py
Description: Auto-start services (Ollama) and configure Qdrant embedded storage during server startup.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Configurable timeouts via environment variables
OLLAMA_HEALTH_TIMEOUT = float(os.getenv('NEXE_OLLAMA_HEALTH_TIMEOUT', '5.0'))
OLLAMA_UNLOAD_TIMEOUT = float(os.getenv('NEXE_OLLAMA_UNLOAD_TIMEOUT', '10.0'))


async def _auto_start_services(config: Dict[str, Any], project_root: Path, server_state) -> None:
  """Auto-start required services (Ollama) and ensure Qdrant embedded storage exists."""
  import httpx
  async with httpx.AsyncClient() as client:

    # === QDRANT (embedded mode — no process, no ports) ===
    qdrant_url = os.getenv("NEXE_QDRANT_URL")
    if qdrant_url:
      # External Qdrant override (Docker, cluster, Qdrant Cloud)
      logger.info("Qdrant: External mode via NEXE_QDRANT_URL=%s", qdrant_url)
      server_state.qdrant_available = True
    else:
      # Embedded mode (default): just ensure storage directory exists
      qdrant_path = Path(os.getenv("NEXE_QDRANT_PATH", str(project_root / "storage" / "vectors")))
      if not qdrant_path.is_absolute():
        qdrant_path = project_root / qdrant_path
      qdrant_path.mkdir(parents=True, exist_ok=True)
      logger.info("Qdrant: Embedded mode (path=%s)", qdrant_path)
      server_state.qdrant_available = True

    # === OLLAMA (fallback engine) ===
    auto_start_ollama = os.getenv("NEXE_AUTOSTART_OLLAMA", "true").lower() == "true"
    _nexe_ollama = os.getenv("NEXE_OLLAMA_HOST")
    if _nexe_ollama:
      ollama_url = _nexe_ollama.rstrip("/")
    else:
      ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # Check if Ollama is running
    ollama_running = False
    try:
      await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
      logger.info("Ollama: OK (already running)")
      ollama_running = True
    except Exception as e:
      logger.debug("Ollama health check failed during startup: %s", e)

    if not ollama_running and not auto_start_ollama:
      logger.info("Ollama: Auto-start disabled (NEXE_AUTOSTART_OLLAMA=false)")
    if not ollama_running and auto_start_ollama:
      # Check if Ollama is installed
      ollama_path = shutil.which("ollama")

      if not ollama_path:
        logger.warning("Ollama: Not installed. Install manually from https://ollama.com/download")
        logger.info("  Or run: curl -fsSL https://ollama.com/install.sh | sh")

      # Start Ollama if installed
      if ollama_path or shutil.which("ollama"):
        logger.info("Ollama: Starting...")
        try:
          process = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
          )
          server_state.ollama_process = process
          # Wait for Ollama to be ready (non-blocking)
          for _ in range(30):  # 15 seconds max
            await asyncio.sleep(0.5)
            try:
              await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
              logger.info("Ollama: OK (started)")
              break
            except Exception as e:
              logger.debug("Ollama not ready yet during startup wait: %s", e)
          else:
            logger.warning("Ollama: Failed to start (timeout 15s)")
        except Exception as e:
          logger.warning(f"Ollama: Failed to start: {e}")
