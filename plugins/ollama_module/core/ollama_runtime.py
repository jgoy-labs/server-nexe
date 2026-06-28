"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/ollama_runtime.py
Description: Single source of truth for starting a local `ollama serve`.

             MC-028 — before this module the "start Ollama" logic was copy-pasted
             across four call sites (ollama_module/core/client.py,
             core/lifespan_services.py, web_ui_module/api/routes_auth.py and,
             partially, core/endpoints/installer.py) and had drifted: only
             client.py honoured NEXE_OLLAMA_BIN / the macOS bundle, while the
             others were PATH-only. Centralising it here keeps NEXE_OLLAMA_BIN a
             single read point and makes every consumer honour the DMG override
             and the headless bundle binary.

             Composable primitives (not a monolith): the readiness wait is
             OPT-IN so routes_auth can keep its "fire-and-forget, do not wait"
             contract while client.py / lifespan keep waiting.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
import platform
import shutil
import subprocess

logger = logging.getLogger(__name__)

# macOS Ollama.app ships the `serve` binary inside its bundle; invoking it
# directly starts Ollama headless (no Dock/GUI window) — see "Bug Ollama GUI"
# (2026-04-06). The DMG sidecar points NEXE_OLLAMA_BIN at this same path.
OLLAMA_BUNDLE_BIN = "/Applications/Ollama.app/Contents/Resources/ollama"

# Well-known install locations of the Ollama CLI, in priority order, used by the
# installer to LOCATE an executable binary (with X_OK). Kept here so the paths
# live in one place instead of being repeated across modules. Stored RAW (with a
# leading ``~``): the consumer must expand them at call time via os.path.expanduser
# so a per-call $HOME (e.g. tests, alternate users) is honoured.
OLLAMA_BIN_CANDIDATES = (
    "/usr/local/bin/ollama",  # nosemgrep: absolute_path
    "/opt/homebrew/bin/ollama",  # nosemgrep: absolute_path
    "~/bin/ollama",
    OLLAMA_BUNDLE_BIN,
    "~/Applications/Ollama.app/Contents/Resources/ollama",
)

# Default readiness wait (used by consumers that DO wait).
READY_ATTEMPTS = 15
READY_INTERVAL = 1.0
READY_TIMEOUT = 2.0
PROBE_TIMEOUT = 3.0


def resolve_ollama_bin() -> "str | None":
    """Resolve which binary to spawn for `ollama serve`. SINGLE read of NEXE_OLLAMA_BIN.

    Priority (preserves the canonical client.py behaviour, now shared):
      1. ``NEXE_OLLAMA_BIN`` — explicit override (DMG sidecar), if it exists.
      2. macOS Ollama.app bundle binary, if present (headless, avoids the GUI).
      3. ``shutil.which("ollama")`` — the CLI on PATH (Linux / Homebrew / curl install).

    Returns ``None`` when Ollama cannot be located (caller skips auto-start).
    """
    override = os.getenv("NEXE_OLLAMA_BIN")
    if override and os.path.exists(override):
        return override
    if platform.system() == "Darwin" and os.path.exists(OLLAMA_BUNDLE_BIN):
        return OLLAMA_BUNDLE_BIN
    return shutil.which("ollama")


def spawn_ollama_serve() -> "subprocess.Popen | None":
    """Start a headless ``ollama serve`` from the resolved binary.

    Detached (own session/process group) so it survives the parent and so
    shutdown can signal the whole group. Returns the ``Popen`` handle (for
    reaping/shutdown) or ``None`` when Ollama is not installed or fails to start.
    """
    binary = resolve_ollama_bin()
    if not binary:
        logger.info("Ollama not installed — skipping auto-start")
        return None
    try:
        process = subprocess.Popen(  # nosec B603: binary from NEXE_OLLAMA_BIN (mono-user env) / hardcoded bundle / PATH; literal `serve`
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("ollama serve started headless (%s)", binary)
        return process
    except Exception as e:
        logger.warning("Could not start ollama serve (%s): %s", binary, e)
        return None


async def is_ollama_running(base_url: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """Best-effort single probe: True iff Ollama answers /api/tags with 200."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/api/tags")
            return resp.status_code == 200
    except Exception:  # nosec B110: best-effort probe; any failure means "not reachable"
        return False


async def wait_ollama_ready(
    base_url: str,
    *,
    attempts: int = READY_ATTEMPTS,
    interval: float = READY_INTERVAL,
    timeout: float = READY_TIMEOUT,
) -> bool:
    """Poll /api/tags until it returns 200 or ``attempts`` elapse. OPT-IN.

    Returns True once Ollama responds, False on timeout.
    """
    import httpx

    for i in range(attempts):
        await asyncio.sleep(interval)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    logger.info("Ollama ready after %ds", i + 1)
                    return True
        except Exception:  # nosec B110: best-effort readiness retry; timeout warning logged below
            pass
    logger.warning("Ollama started but not responding after %ds", attempts)
    return False


async def ensure_ollama_running(
    base_url: str,
    *,
    wait: bool = True,
    attempts: int = READY_ATTEMPTS,
    interval: float = READY_INTERVAL,
) -> "subprocess.Popen | None":
    """Start Ollama if it is installed but not already running.

    Returns the spawned ``Popen`` handle, or ``None`` if Ollama was already
    running, is not installed, or failed to start.

    ``wait``:
      * ``True``  (client.py): poll for readiness after spawning.
      * ``False`` (routes_auth): fire-and-forget — return as soon as it is
        spawned, never block on readiness. This preserves the long-standing
        "routes_auth does not wait for ready" contract.
    """
    if await is_ollama_running(base_url):
        logger.info("Ollama already running at %s", base_url)
        return None

    process = spawn_ollama_serve()
    if process is None:
        return None

    if wait:
        await wait_ollama_ready(base_url, attempts=attempts, interval=interval)
    return process
