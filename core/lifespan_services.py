"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_services.py
Description: Auto-start services (Qdrant, Ollama) during server startup.

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
QDRANT_HEALTH_TIMEOUT = float(os.getenv('NEXE_QDRANT_HEALTH_TIMEOUT', '2.0'))


async def _auto_start_services(config: Dict[str, Any], project_root: Path, server_state) -> None:
  """Auto-start required services (Qdrant, Ollama) if not running."""
  import httpx
  async with httpx.AsyncClient() as client:

    # === QDRANT (local binary, no Docker!) ===
    auto_start_qdrant = os.getenv("NEXE_AUTOSTART_QDRANT", "true").lower() == "true"
    qdrant_host = os.getenv('NEXE_QDRANT_HOST', os.getenv('QDRANT_HOST', 'localhost'))
    qdrant_port = os.getenv('NEXE_QDRANT_PORT', os.getenv('QDRANT_PORT', '6333'))
    qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
    qdrant_bin = Path(os.getenv("NEXE_QDRANT_BIN", str(project_root / "qdrant")))
    qdrant_storage = project_root / "storage" / "qdrant"

    try:
      await client.get(f"{qdrant_url}/health", timeout=QDRANT_HEALTH_TIMEOUT)
      logger.info("Qdrant: OK (already running)")
      server_state.qdrant_available = True
    except Exception:
      if not auto_start_qdrant:
        logger.info("Qdrant: Auto-start disabled (NEXE_AUTOSTART_QDRANT=false)")
      elif qdrant_bin.exists():
        logger.info(f"Qdrant: Starting from {qdrant_bin}...")
        try:
          qdrant_storage.mkdir(parents=True, exist_ok=True)
          env = os.environ.copy()
          env["QDRANT__STORAGE__STORAGE_PATH"] = str(qdrant_storage)
          env["QDRANT__SERVICE__HTTP_PORT"] = str(qdrant_port)
          env["QDRANT__SERVICE__DISABLE_TELEMETRY"] = "true"
          env["QDRANT__STORAGE__OPTIMIZERS__FLUSH_INTERVAL_SEC"] = "1"

          # Start Qdrant process
          process = subprocess.Popen(
            [str(qdrant_bin), "--disable-telemetry"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
          )
          server_state.qdrant_process = process

          # Wait for Qdrant to be ready (non-blocking)
          for i in range(30):  # 15 seconds max
            await asyncio.sleep(0.5)
            try:
              await client.get(f"{qdrant_url}/health", timeout=QDRANT_HEALTH_TIMEOUT)
              logger.info(f"Qdrant: OK (started on port {qdrant_port})")
              server_state.qdrant_available = True
              break
            except Exception:
              # Check if process died
              if process.poll() is not None:
                logger.error("Qdrant: Process died. Run './qdrant' manually to see logs.")
                break
          else:
            logger.warning("Qdrant: Failed to start (timeout 15s)")
        except Exception as e:
          logger.error(f"Qdrant: Failed to start: {e}")
      else:
        logger.warning(f"Qdrant: Binary not found at {qdrant_bin}")
        logger.info("  Run ./setup.sh to download Qdrant automatically")
        logger.info("  Or set NEXE_QDRANT_BIN=/path/to/qdrant in .env to use a custom location")

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
