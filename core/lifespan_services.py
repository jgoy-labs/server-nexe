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
    """Configure Qdrant storage (external override or embedded mode).

    In sidecar mode consult SidecarConfig.qdrant_url and
    SidecarConfig.vectors_dir; fallback al comportament previ via env vars
    directes amb logger.debug si SidecarConfig no disponible.
    """
    qdrant_url = None
    qdrant_path_str = None
    try:
        from core.sidecar_config import get_sidecar_config
        cfg = get_sidecar_config()
        if cfg.is_sidecar:
            qdrant_url = cfg.qdrant_url
            qdrant_path_str = str(cfg.vectors_dir)
    except Exception as exc:
        logger.debug("SidecarConfig unavailable in _setup_qdrant: %s", exc)

    if qdrant_url is None:
        qdrant_url = os.getenv("NEXE_QDRANT_URL")
    if qdrant_url:
        # External Qdrant override (Docker, cluster, Qdrant Cloud)
        logger.info("Qdrant: External mode via URL=%s", qdrant_url)
    else:
        # Embedded mode (default): just ensure storage directory exists
        if qdrant_path_str is None:
            qdrant_path_str = os.getenv("NEXE_QDRANT_PATH", str(project_root / "storage" / "vectors"))
        qdrant_path = Path(qdrant_path_str)
        if not qdrant_path.is_absolute():
            qdrant_path = project_root / qdrant_path
        qdrant_path.mkdir(parents=True, exist_ok=True)
        logger.info("Qdrant: Embedded mode (path=%s)", qdrant_path)
    server_state.qdrant_available = True


def _resolve_ollama_url() -> str:
    """Resolve the Ollama base URL from environment variables.

    In sidecar mode use SidecarConfig.ollama_host;
    fallback NEXE_OLLAMA_HOST → OLLAMA_HOST → default.
    """
    try:
        from core.sidecar_config import get_sidecar_config
        cfg = get_sidecar_config()
        if cfg.is_sidecar and cfg.ollama_host:
            return cfg.ollama_host.rstrip("/")
    except Exception as exc:
        logger.debug("SidecarConfig unavailable in _resolve_ollama_url: %s", exc)

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
            stderr=subprocess.DEVNULL,
            # nova sessió/grup de procés perquè el shutdown pugui
            # senyalar el grup sencer (os.killpg) i propagar als runners-fills.
            start_new_session=True,
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


def _signal_process(process, sig: int, direct) -> None:
    """Senyala el grup de procés (os.killpg) amb fallback al procés directe.

    si el procés es va llançar amb start_new_session=True, el seu
    PID és líder de grup; senyalar el grup propaga als runners-fills. Si el
    grup no es pot resoldre (ProcessLookupError/OSError), recau al senyal
    directe sobre el procés pare per no trencar el shutdown actual.
    """
    try:
        os.killpg(os.getpgid(process.pid), sig)
    except (ProcessLookupError, OSError) as e:
        logger.debug("killpg(%s) failed, falling back to direct signal: %s", sig, e)
        direct()


def _stop_process(process, name: str) -> None:
    """Send SIGINT → terminate → kill to a subprocess. Safe to call in finally blocks."""
    if not process:
        return
    if process.poll() is not None:
        return
    try:
        logger.info("Stopping %s process...", name)
        _signal_process(process, _signal.SIGINT, lambda: process.send_signal(_signal.SIGINT))
        process.wait(timeout=10)
    except Exception as e:
        logger.debug("SIGINT failed for %s: %s", name, e)
        try:
            _signal_process(process, _signal.SIGTERM, process.terminate)
            process.wait(timeout=3)
        except Exception as e2:
            logger.debug("Terminate failed for %s: %s", name, e2)
            try:
                _signal_process(process, _signal.SIGKILL, process.kill)
            except Exception:
                # AP-G01: log diagnòstic sense canviar el flux (force-stop best-effort)
                logger.debug("Failed to force-stop %s process", name, exc_info=True)
