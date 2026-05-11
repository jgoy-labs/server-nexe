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
import signal as _signal
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Configurable timeouts via environment variables
OLLAMA_HEALTH_TIMEOUT = float(os.getenv('NEXE_OLLAMA_HEALTH_TIMEOUT', '5.0'))
OLLAMA_UNLOAD_TIMEOUT = float(os.getenv('NEXE_OLLAMA_UNLOAD_TIMEOUT', '10.0'))


def _setup_qdrant(project_root: Path, server_state) -> None:
    """Configure Qdrant storage (external override or embedded mode)."""
    qdrant_url = os.getenv("NEXE_QDRANT_URL")
    if qdrant_url:
        # External Qdrant override (Docker, cluster, Qdrant Cloud)
        logger.info("Qdrant: External mode via NEXE_QDRANT_URL=%s", qdrant_url)
    else:
        # Embedded mode (default): just ensure storage directory exists
        qdrant_path = Path(os.getenv("NEXE_QDRANT_PATH", str(project_root / "storage" / "vectors")))
        if not qdrant_path.is_absolute():
            qdrant_path = project_root / qdrant_path
        qdrant_path.mkdir(parents=True, exist_ok=True)
        logger.info("Qdrant: Embedded mode (path=%s)", qdrant_path)
    server_state.qdrant_available = True


def _resolve_ollama_url() -> str:
    """Resolve the Ollama base URL from environment variables."""
    _nexe_ollama = os.getenv("NEXE_OLLAMA_HOST")
    if _nexe_ollama:
        return _nexe_ollama.rstrip("/")
    return os.getenv("OLLAMA_HOST", "http://localhost:11434")


async def _check_ollama_running(client, ollama_url: str) -> bool:
    """Return True if Ollama is already responding, False otherwise."""
    try:
        await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
        logger.info("Ollama: OK (already running)")
        return True
    except Exception as e:
        logger.debug("Ollama health check failed during startup: %s", e)
        return False


async def _launch_ollama(client, ollama_url: str, server_state) -> None:
    """Spawn `ollama serve` and wait up to 15s for it to become ready."""
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        logger.warning("Ollama: Not installed. Install manually from https://ollama.com/download")
        logger.info("  Or run: curl -fsSL https://ollama.com/install.sh | sh")
        return

    logger.info("Ollama: Starting...")
    try:
        process = subprocess.Popen(  # nosec B603 B607: literal `ollama serve` argv; system tool resolved via PATH (mono-user local)
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


async def _auto_start_services(config: Dict[str, Any], project_root: Path, server_state) -> None:
    """Auto-start required services (Ollama) and ensure Qdrant embedded storage exists."""
    import httpx
    async with httpx.AsyncClient() as client:

        # === QDRANT (embedded mode — no process, no ports) ===
        _setup_qdrant(project_root, server_state)

        # === OLLAMA (fallback engine) ===
        auto_start_ollama = os.getenv("NEXE_AUTOSTART_OLLAMA", "true").lower() == "true"
        ollama_url = _resolve_ollama_url()

        ollama_running = await _check_ollama_running(client, ollama_url)

        if not ollama_running and not auto_start_ollama:
            logger.info("Ollama: Auto-start disabled (NEXE_AUTOSTART_OLLAMA=false)")
        if not ollama_running and auto_start_ollama:
            await _launch_ollama(client, ollama_url, server_state)


def _stop_process(process, name: str) -> None:
    """Send SIGINT → terminate → kill to a subprocess. Safe to call in finally blocks."""
    if not process:
        return
    if process.poll() is not None:
        return
    try:
        logger.info("Stopping %s process...", name)
        process.send_signal(_signal.SIGINT)
        process.wait(timeout=10)
    except Exception as e:
        logger.debug("SIGINT failed for %s: %s", name, e)
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception as e2:
            logger.debug("Terminate failed for %s: %s", name, e2)
            try:
                process.kill()
            except Exception:
                logger.debug("Failed to force-stop %s process", name)
