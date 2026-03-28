"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_ollama.py
Description: Ollama model cleanup during startup and shutdown.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

logger = logging.getLogger(__name__)


async def cleanup_ollama_startup(server_state, _translate, health_timeout: float, unload_timeout: float) -> None:
  """Unload any Ollama models left from previous sessions during startup."""
  try:
    import httpx
    ollama_url = os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    async with httpx.AsyncClient() as client:
      try:
        health_response = await client.get(f"{ollama_url}/api/ps", timeout=health_timeout)
        if health_response.status_code == 200:
          loaded_models = health_response.json().get("models", [])

          if loaded_models:
            logger.info("Cleaning Ollama: %s model(s) loaded from previous sessions...", len(loaded_models))

            for model_info in loaded_models:
              model_name = model_info.get("name") or model_info.get("model")
              if model_name:
                try:
                  await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model_name, "keep_alive": 0},
                    timeout=unload_timeout
                  )
                  logger.debug("  - Unloaded: %s", model_name)
                except Exception as e:
                  msg = _translate(server_state.i18n, "core.server.ollama_unload_error",
                    "Error unloading {model}: {error}",
                    model=model_name, error=str(e))
                  logger.warning("  %s", msg)

            logger.info("Ollama cleaned successfully")
          else:
            logger.debug("Ollama is clean (no models loaded)")
        else:
          msg = _translate(server_state.i18n, "core.server.ollama_health_check_failed",
            "Ollama health check failed: HTTP {status_code}",
            status_code=health_response.status_code)
          logger.warning(msg)

      except Exception as e:
        if "ConnectError" in type(e).__name__:
          msg = _translate(server_state.i18n, "core.server.ollama_not_available",
            "Ollama not available ({url}). If using Ollama, start it manually.",
            url=ollama_url)
          logger.warning(msg)
        elif "TimeoutException" in type(e).__name__:
          msg = _translate(server_state.i18n, "core.server.ollama_timeout",
            "Ollama timeout. May be busy.")
          logger.warning(msg)
        else:
          raise

  except Exception as e:
    msg = _translate(server_state.i18n, "core.server.ollama_cleanup_error",
      "Error checking/cleaning Ollama: {error}", error=str(e))
    logger.warning(msg)


async def cleanup_ollama_shutdown(health_timeout: float, unload_timeout: float) -> None:
  """Unload Ollama models from RAM during server shutdown."""
  try:
    import httpx
    ollama_url = os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    async with httpx.AsyncClient() as client:
      ps_response = await client.get(f"{ollama_url}/api/ps", timeout=health_timeout)
      if ps_response.status_code == 200:
        loaded_models = ps_response.json().get("models", [])

        if loaded_models:
          logger.info("Unloading %s Ollama model(s) from RAM...", len(loaded_models))

          for model_info in loaded_models:
            model_name = model_info.get("name") or model_info.get("model")
            if model_name:
              await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=unload_timeout
              )
              logger.debug("  - Unloaded: %s", model_name)

          logger.info("Ollama models unloaded successfully")
        else:
          logger.debug("No Ollama models loaded")
  except Exception as e:
    logger.debug("Could not unload Ollama models: %s", e)
