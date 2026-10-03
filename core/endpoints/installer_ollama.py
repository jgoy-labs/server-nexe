"""The Ollama install path of the wizard.

Split out of ``core.endpoints.installer`` (finding #969). Locating the binary,
installing it when it is missing, and streaming the pull as SSE.

The install lock lives in ``installer_shared`` on purpose and is reached
through the module: two locks would be no lock, and two ``zip_extract`` runs
on /Applications/Ollama.app at once corrupt the app.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import shutil
from typing import AsyncIterator

from fastapi import Request

from core.endpoints import installer_shared
from core.proc_utils import no_window_kwargs

logger = logging.getLogger(__name__)

def _find_ollama_bin() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    # MC-028: the well-known install paths are the canonical list shared with
    # ollama_runtime (deferred import keeps the layering gate green: core must
    # not import-time depend on plugins). Here we LOCATE an executable binary
    # (X_OK) for model installs — a different concern from spawning `serve`.
    from plugins.ollama_module.core.ollama_runtime import OLLAMA_BIN_CANDIDATES

    for candidate in OLLAMA_BIN_CANDIDATES:
        candidate = os.path.expanduser(candidate)  # expand ~ at call time, honouring current $HOME
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None

async def _install_ollama_and_locate() -> str:
    """Run ensure_ollama_installed and return the Ollama binary path.

    Falls back to the bundled Ollama.app binary when the CLI is installed but
    not yet registered on PATH. Raises RuntimeError with a UX-friendly,
    platform-specific message on any failure. The caller MUST hold
    ``installer_shared._ollama_install_lock``.

    MC-031: single source of truth for the install→locate machine shared by
    _install_ollama_if_needed (RuntimeError path) and install_ollama_endpoint
    (SSE path), so the bundle fallback can never diverge between them again.
    """
    from installer.installer_ollama_install import ensure_ollama_installed
    loop = asyncio.get_event_loop()
    try:
        installed = await loop.run_in_executor(None, ensure_ollama_installed, True)
    except PermissionError:
        logger.exception("Ollama install: permission denied")
        _system = platform.system().lower()
        if _system == "darwin":
            raise RuntimeError(
                "No s'ha pogut instal.lar Ollama a /Applications/. "
                "Permis denegat. Instal.la'l manualment des d'ollama.com"
            ) from None
        if _system == "linux":
            raise RuntimeError(
                "Linux: l'instal.lador d'Ollama necessita sudo. "
                "Instal.la manualment des d'ollama.com/download/linux"
            ) from None
        raise RuntimeError("Ollama install permission denied") from None
    except Exception as exc:
        logger.exception("Ollama auto-install failed")
        raise RuntimeError(f"Ollama auto-install failed: {exc}") from exc
    if not installed:
        raise RuntimeError(
            "Ollama install did not complete. Restart the app or "
            "install manually from https://ollama.com"
        )
    ollama = _find_ollama_bin()
    if ollama:
        return ollama
    for _fallback in [
        "/Applications/Ollama.app/Contents/Resources/ollama",  # nosemgrep: absolute_path
        os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
    ]:
        if os.path.isfile(_fallback) and os.access(_fallback, os.X_OK):
            logger.info("ollama: CLI not yet registered; using bundle binary %s", _fallback)
            return _fallback
    raise RuntimeError(
        "Ollama installed but binary still not located. "
        "Open Ollama.app once to finish setup, then restart server-nexe."
    )

async def _install_ollama_if_needed(request: Request) -> str:
    """Auto-install Ollama and return its binary path. Raises RuntimeError on failure."""
    if await request.is_disconnected():
        raise RuntimeError("client disconnected before Ollama install")
    if not installer_shared._ollama_install_lock.acquire(blocking=False):
        raise RuntimeError("Ja s'esta instal.lant Ollama en un altre proces")
    try:
        return await _install_ollama_and_locate()
    finally:
        installer_shared._ollama_install_lock.release()

async def _stream_ollama(model_id: str, request: Request) -> AsyncIterator[dict]:
    """Download an Ollama model via ollama pull, streaming real progress.

    If Ollama is not present, install it automatically
    via ensure_ollama_installed(headless=True) abans del pull. Validat amb
    agentic audit 2026-05-20 (8 iters, 92K tokens, 4 correccions C1-C5).
    """
    ollama = _find_ollama_bin()
    if not ollama:
        yield {"type": "progress", "stage": "Instal.lant Ollama...", "percent": 0}
        ollama = await _install_ollama_if_needed(request)

    # In MINIMAL MODE (onboarding) the lifespan that auto-starts `ollama serve`
    # is skipped, and on Windows the standalone-zip install has no background
    # service — so `ollama pull` would hit a dead server (exit 1). Ensure the
    # server is up (spawn + wait for readiness) before pulling. Idempotent: it
    # returns early when Ollama is already running.
    from plugins.ollama_module.core.client import resolve_base_url
    from plugins.ollama_module.core.ollama_runtime import (
        ensure_ollama_running,
        is_ollama_running,
    )

    yield {"type": "progress", "stage": "Iniciant Ollama...", "percent": 0}
    _base = resolve_base_url()
    await ensure_ollama_running(_base, wait=True)
    # #833 (review): ensure_ollama_running returns the Popen even when the
    # wait burns its budget — without this gate, the pull ran anyway
    # against a dead daemon and died with the cryptic "ollama pull failed".
    if not await is_ollama_running(_base):
        raise RuntimeError(
            "Ollama API not ready (/api/tags) — cannot pull the model; "
            "start Ollama and retry the onboarding step"
        )

    proc = await asyncio.create_subprocess_exec(
        ollama, "pull", model_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        # Windows: CREATE_NO_WINDOW so the pull does not flash a console window
        # during onboarding (blocking: we read stdout=PIPE, so not detached).
        **no_window_kwargs(),
    )

    assert proc.stdout is not None  # noqa: S101  # nosec B101 — type guard: proc created with stdout=PIPE so stdout cannot be None by construction
    last_pct = -1
    async for raw in proc.stdout:
        if await request.is_disconnected():
            proc.kill()
            return
        line = raw.decode(errors="replace")
        m = re.search(r"(\d+)%", line)
        if m:
            pct = int(m.group(1))
            if pct != last_pct:
                last_pct = pct
                speed_m = re.search(r"([\d.]+\s*(?:MB|GB|KB)/s)", line)
                eta_m = re.search(r"(\d+[hm]\d*[ms]?|\d+s)", line)
                yield {
                    "type": "progress",
                    "percent": pct,
                    "speed": speed_m.group(1) if speed_m else "—",
                    "eta": eta_m.group(1) if eta_m else "—",
                }

    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ollama pull failed (exit {proc.returncode})")
