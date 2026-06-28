"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/ollama_utils.py
Description: Canonical Ollama base-URL resolver (MC-089). Every component that
    talks to Ollama (chat engine, memory ingestion/recall, plugin health) must
    resolve the host the SAME way the warmup/health/cleanup paths do, so a user
    who sets OLLAMA_HOST (or runs as a sidecar) is honoured everywhere instead
    of half the code falling back to localhost. Resolution is done at CALL time
    (not import time) so env/SidecarConfig changes are always picked up.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

logger = logging.getLogger(__name__)


def _ensure_scheme(url: str) -> str:
    """Prepend http:// when the host has no scheme.

    Ollama's own ``OLLAMA_HOST`` convention is bare ``host:port`` (e.g.
    ``127.0.0.1:11434``), but httpx needs a scheme — without this a bare host
    raises UnsupportedProtocol instead of a clean connection attempt.
    """
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = f"http://{url}"
    return url


def resolve_ollama_url() -> str:
    """Resolve the Ollama base URL (with scheme, no trailing slash).

    Precedence: SidecarConfig.ollama_host (sidecar mode) → NEXE_OLLAMA_HOST →
    OLLAMA_HOST → ``http://localhost:11434``. SidecarConfig is consulted
    defensively (it may not exist yet outside the server process). The result is
    always scheme-normalised (Ollama's OLLAMA_HOST is conventionally bare host:port).
    """
    try:
        from core.sidecar_config import get_sidecar_config
        cfg = get_sidecar_config()
        if cfg.is_sidecar and cfg.ollama_host:
            return _ensure_scheme(cfg.ollama_host)
    except Exception as exc:
        logger.debug("SidecarConfig unavailable in resolve_ollama_url: %s", exc)

    _nexe_ollama = os.getenv("NEXE_OLLAMA_HOST")
    if _nexe_ollama:
        return _ensure_scheme(_nexe_ollama)
    return _ensure_scheme(os.getenv("OLLAMA_HOST", "http://localhost:11434"))
