"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/client.py
Description: Client Ollama — connexio, auto-start, base_url.
             Extret de module.py durant normalitzacio BUS 2026-04-06.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

from core.resilience import CircuitOpenError

logger = logging.getLogger(__name__)

# Configurable timeout via environment variable
OLLAMA_CONNECTION_TIMEOUT = float(os.getenv("NEXE_OLLAMA_CONNECTION_TIMEOUT", "10.0"))

DEFAULT_BASE_URL = "http://localhost:11434"


def _parent():
    """Lazy import del modul parent per accedir a httpx patchable pels tests.

    Els tests unit fan patch('plugins.ollama_module.module.httpx', ...) i
    patch('plugins.ollama_module.module.httpx.AsyncClient', ...). Per tant
    el codi extret ha de llegir httpx desde el namespace del parent i no pas
    importar-lo directament.

    FIXME (post-release): Refactor tests to patch core/ instead of module/.
    Aquest "parent binding pattern" és un deute tècnic introduit durant el BUS
    de normalització pre-release (2026-04-06) per preservar la retrocompat amb
    30+ patches existents. Quan els tests es migrin a patch
    'plugins.ollama_module.core.client.httpx' (i equivalents per chat.py /
    models.py), aquest helper es pot eliminar i fer un import normal d'httpx.
    """
    from plugins.ollama_module import module as _m
    return _m


def resolve_base_url() -> str:
    """Resol la base_url d'Ollama desde env vars."""
    base_url = (
        os.getenv("NEXE_OLLAMA_HOST")
        or os.getenv("OLLAMA_HOST")
        or DEFAULT_BASE_URL
    )
    return base_url.rstrip("/")


class OllamaClient:
    """Client Ollama basic — connexio i auto-start."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    async def check_connection(self) -> bool:
        """Verifica si Ollama esta accessible."""
        httpx = _parent().httpx
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except CircuitOpenError:
            logger.warning("Circuit breaker OPEN for Ollama - skipping connection check")
            return False

    async def is_model_loaded(self, model_name: str) -> bool:
        """Comprova si un model esta carregat a VRAM via /api/ps."""
        httpx = _parent().httpx
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
                response = await client.get(f"{self.base_url}/api/ps")
                if response.status_code == 200:
                    data = response.json()
                    loaded = data.get("models", [])
                    # Match exacte: "qwen3.5:9b" != "qwen3.5:2b"
                    # Ollama retorna noms amb tag (e.g. "qwen3.5:9b")
                    # Si l'usuari no posa tag, Ollama usa ":latest"
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

        # Comprovar si ja corre
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    logger.info("Ollama already running at %s", self.base_url)
                    return
        except Exception:
            pass

        # No corre — intentar arrencar
        is_macos = platform.system() == "Darwin"

        # Bug Ollama GUI (2026-04-06) — preferim sempre `ollama serve` headless.
        # Abans feiem `open -a Ollama` que llança la GUI completa (Dock + finestra)
        # i molesta l'usuari constantment. El binari serve viu dins el bundle de
        # Ollama.app i el podem invocar directament sense aixecar la GUI.
        macos_ollama_bin = "/Applications/Ollama.app/Contents/Resources/ollama"
        if is_macos and os.path.exists(macos_ollama_bin):
            try:
                subprocess.Popen(
                    [macos_ollama_bin, "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,  # No morir amb el parent process
                )
                logger.info("ollama serve started headless from Ollama.app bundle (macOS)")
            except Exception as e:
                logger.warning("Could not start ollama serve from bundle: %s", e)
        elif shutil.which("ollama"):
            try:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True  # No morir amb el parent process
                )
                logger.info("ollama serve started automatically")
            except Exception as e:
                logger.warning("Could not start ollama serve: %s", e)
        else:
            logger.info("Ollama not installed — skipping auto-start")
            return

        # Esperar que estigui llest (max 15s)
        import asyncio
        for i in range(15):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{self.base_url}/api/tags")
                    if resp.status_code == 200:
                        logger.info("Ollama ready after %ds", i + 1)
                        return
            except Exception:
                pass
        logger.warning("Ollama started but not responding after 15s")

    async def unload_all_models(self):
        """Descarrega tots els models d'Ollama de la VRAM (shutdown helper)."""
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
