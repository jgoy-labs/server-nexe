"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/client.py
Description: Ollama Client — connection, auto-start, base_url.
             Extracted from module.py during BUS normalisation 2026-04-06.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from urllib.parse import urlsplit, urlunsplit

from core.resilience import CircuitOpenError

logger = logging.getLogger(__name__)

# Configurable timeout via environment variable
OLLAMA_CONNECTION_TIMEOUT = float(os.getenv("NEXE_OLLAMA_CONNECTION_TIMEOUT", "10.0"))

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_PORT = 11434


def _parent():
    """Lazy import of the parent module to access httpx patchable by tests.

    Unit tests patch('plugins.ollama_module.module.httpx', ...) and
    patch('plugins.ollama_module.module.httpx.AsyncClient', ...). Therefore
    the extracted code must read httpx from the parent namespace rather than
    importing it directly.

    FIXME (post-release): Refactor tests to patch core/ instead of module/.
    This "parent binding pattern" is a technical debt introduced during the BUS
    normalisation pre-release (2026-04-06) to preserve backward compatibility
    with 30+ existing patches. When tests are migrated to patch
    'plugins.ollama_module.core.client.httpx' (and equivalents for chat.py /
    models.py), this helper can be removed and replaced with a normal httpx import.
    """
    from plugins.ollama_module import module as _m
    return _m


def _normalize_base_url(raw: str) -> str:
    """Normalise an Ollama host string into a connectable client URL.

    Handles the values users commonly set in ``OLLAMA_HOST``:
    - missing scheme (``localhost:11434``)        → prepend ``http://``
    - bind-all addresses (``0.0.0.0`` / ``::``)   → loopback (not connectable as-is)
    - missing port on plain ``http``              → default 11434
    Legitimate remote hosts and ``https://`` URLs are preserved untouched.
    """
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    parts = urlsplit(url)
    host = parts.hostname
    if not host:  # unparseable netloc → fall back to a safe default
        return DEFAULT_BASE_URL

    # Bind-all addresses mean "listen everywhere"; they are not a client target.
    if host in ("0.0.0.0", "::"):  # nosec B104 — rewrites a user-supplied bind-all OLLAMA_HOST to loopback; client target, never a server bind
        host = "127.0.0.1"  # nosemgrep: hardcode.ip_address — intentional loopback fallback when OLLAMA_HOST is a bind-all; local mono-user client target

    netloc_host = f"[{host}]" if ":" in host else host  # keep IPv6 bracketing

    port = parts.port
    if port is None and parts.scheme == "http":
        port = DEFAULT_OLLAMA_PORT  # https with no port → leave httpx to use 443
    netloc = f"{netloc_host}:{port}" if port is not None else netloc_host

    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), parts.query, parts.fragment))


def resolve_base_url() -> str:
    """Resolves the Ollama base_url from env vars, normalised for client use.

    Priority: ``NEXE_OLLAMA_HOST`` > ``OLLAMA_HOST`` > :data:`DEFAULT_BASE_URL`.
    """
    raw = (os.getenv("NEXE_OLLAMA_HOST") or os.getenv("OLLAMA_HOST") or "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    return _normalize_base_url(raw)


class OllamaClient:
    """Basic Ollama client — connection and auto-start."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._ollama_process = None  # Popen ref for reaping at shutdown (avoids zombies)

    async def check_connection(self) -> bool:
        """Checks if Ollama is reachable."""
        httpx = _parent().httpx
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except CircuitOpenError:
            logger.warning("Circuit breaker OPEN for Ollama - skipping connection check")
            return False

    async def is_model_loaded(self, model_name: str) -> bool:
        """Checks if a model is loaded in VRAM via /api/ps."""
        httpx = _parent().httpx
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/api/ps")
                if response.status_code == 200:
                    data = response.json()
                    loaded = data.get("models", [])
                    # Exact match: "qwen3.5:9b" != "qwen3.5:2b"
                    # Ollama returns names with tag (e.g. "qwen3.5:9b")
                    # If the user omits the tag, Ollama uses ":latest"
                    target = model_name if ":" in model_name else f"{model_name}:latest"
                    for m in loaded:
                        name = m.get("name", "")
                        if name == target:
                            return True
                return False
        except Exception:
            return False

    async def ensure_ollama_running(self):
        """Start Ollama if it is installed but not running. macOS + Linux."""
        import shutil
        import subprocess
        import platform

        httpx = _parent().httpx
        if httpx is None:
            return

        # Check if already running
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    logger.info("Ollama already running at %s", self.base_url)
                    return
        except Exception:  # nosec B110: best-effort connection probe; on failure fall through to start-Ollama path
            pass

        # Not running — attempt to start
        is_macos = platform.system() == "Darwin"

        # Bug Ollama GUI (2026-04-06) — we always prefer headless `ollama serve`.
        # Previously we used `open -a Ollama` which launches the full GUI (Dock + window)
        # and constantly bothers the user. The serve binary lives inside the
        # Ollama.app bundle and can be invoked directly without raising the GUI.
        macos_ollama_bin = "/Applications/Ollama.app/Contents/Resources/ollama"
        if is_macos and os.path.exists(macos_ollama_bin):
            try:
                self._ollama_process = subprocess.Popen(  # nosec B603: macos_ollama_bin is hardcoded absolute path "/Applications/Ollama.app/Contents/Resources/ollama"; literal `serve`
                    [macos_ollama_bin, "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,  # Don't die with the parent process
                )
                logger.info("ollama serve started headless from Ollama.app bundle (macOS)")
            except Exception as e:
                logger.warning("Could not start ollama serve from bundle: %s", e)
        elif shutil.which("ollama"):
            try:
                self._ollama_process = subprocess.Popen(  # nosec B603 B607: literal `ollama serve` argv; ollama via PATH (mono-user local — equivalent to running it manually)
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True  # Don't die with the parent process
                )
                logger.info("ollama serve started automatically")
            except Exception as e:
                logger.warning("Could not start ollama serve: %s", e)
        else:
            logger.info("Ollama not installed — skipping auto-start")
            return

        # Wait until ready (max 15s)
        import asyncio
        for i in range(15):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{self.base_url}/api/tags")
                    if resp.status_code == 200:
                        logger.info("Ollama ready after %ds", i + 1)
                        return
            except Exception:  # nosec B110: best-effort readiness retry loop; loop exit logs the warning below
                pass
        logger.warning("Ollama started but not responding after 15s")

    def reap_process(self) -> None:
        """Non-blocking reap of the Ollama process started by us.

        .poll() returns None if the process is still running (daemon, OK),
        or the exit code if it has already finished (reaping avoids the zombie).
        """
        if self._ollama_process is not None:
            self._ollama_process.poll()

    async def unload_all_models(self):
        """Unloads all Ollama models from VRAM (shutdown helper)."""
        httpx = _parent().httpx
        if httpx is None:
            return
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/api/ps")
                if resp.status_code == 200:
                    loaded = resp.json().get("models", [])
                    for loaded_model in loaded:
                        name = loaded_model.get("name", "")
                        if name:
                            await client.post(
                                f"{self.base_url}/api/generate",
                                json={"model": name, "keep_alive": 0}
                            )
                            logger.info("Model %s unloaded from VRAM (shutdown)", name)
        except Exception as e:
            logger.debug("Could not unload Ollama models on shutdown: %s", e)
