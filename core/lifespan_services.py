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
import signal as _signal
from pathlib import Path
from typing import Any, Dict

from core.env_utils import parse_truthy
from core.ollama_utils import resolve_ollama_url as _resolve_ollama_url

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


async def _check_ollama_running(client, ollama_url: str) -> bool:
    """Return True if Ollama is already responding, False otherwise."""
    try:
        # MC-120: httpx .get() does not raise on 4xx/5xx; check the status so a
        # non-200 responder on the Ollama host isn't mistaken for a healthy Ollama
        # (cleanup_ollama_* already validates status_code==200).
        resp = await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
        if resp.status_code == 200:
            logger.info("Ollama: OK (already running)")
            return True
        logger.debug("Ollama health check: unexpected status %s", resp.status_code)
        return False
    except Exception as e:
        logger.debug("Ollama health check failed during startup: %s", e)
        return False


async def _launch_ollama(client, ollama_url: str, server_state) -> None:
    """Spawn `ollama serve` and wait up to 15s for it to become ready.

    MC-028: the binary selection + headless detached spawn are centralised in
    :func:`ollama_runtime.spawn_ollama_serve` (so this call site now also
    honours NEXE_OLLAMA_BIN and the macOS Ollama.app bundle, not just PATH).
    The readiness wait stays here, reusing the shared startup ``client``.
    """
    from plugins.ollama_module.core.ollama_runtime import spawn_ollama_serve

    process = spawn_ollama_serve()
    if process is None:
        # spawn_ollama_serve already logged the PRECISE cause just above:
        #   - not installed  → INFO  "Ollama not installed — skipping auto-start"
        #   - spawn failure   → WARNING "Could not start ollama serve (<bin>): <err>"
        # Don't assert "not installed" here (the binary may exist but have failed
        # to spawn); keep the operator hint generic and point at the cause above.
        logger.warning("Ollama: auto-start skipped (see cause above). Install: https://ollama.com/download")
        return

    logger.info("Ollama: Starting...")
    server_state.ollama_process = process
    # Wait for Ollama to be ready (non-blocking)
    for _ in range(30):  # 15 seconds max
        await asyncio.sleep(0.5)
        try:
            resp = await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
            if resp.status_code == 200:  # MC-120: only ready on 200, keep polling otherwise
                logger.info("Ollama: OK (started)")
                break
            logger.debug("Ollama not ready yet (status %s)", resp.status_code)
        except Exception as e:
            logger.debug("Ollama not ready yet during startup wait: %s", e)
    else:
        logger.warning("Ollama: Failed to start (timeout 15s)")


async def _auto_start_services(config: Dict[str, Any], project_root: Path, server_state) -> None:
    """Auto-start required services (Ollama) and ensure Qdrant embedded storage exists."""
    import httpx
    async with httpx.AsyncClient() as client:

        # === QDRANT (embedded mode — no process, no ports) ===
        _setup_qdrant(project_root, server_state)

        # === OLLAMA (fallback engine) ===
        auto_start_ollama = parse_truthy(os.getenv("NEXE_AUTOSTART_OLLAMA", "true"))
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
    # Windows has no process groups: os.killpg/os.getpgid don't exist and would
    # raise AttributeError — which would ESCAPE the (ProcessLookupError, OSError)
    # except below and skip direct(), leaving Ollama (and its model runners)
    # orphaned on every shutdown. Fall straight to the direct per-process signal.
    if not hasattr(os, "killpg") or not hasattr(os, "getpgid"):
        direct()
        return
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
                # SIGKILL doesn't exist on Windows (AttributeError evaluated at
                # the call-site before _signal_process runs); fall back to
                # SIGTERM there. On Windows the sig is unused anyway (the gate
                # above routes to direct() = process.kill() = TerminateProcess).
                _signal_process(
                    process, getattr(_signal, "SIGKILL", _signal.SIGTERM), process.kill
                )
            except Exception:
                # AP-G01: log diagnòstic sense canviar el flux (force-stop best-effort)
                logger.debug("Failed to force-stop %s process", name, exc_info=True)
