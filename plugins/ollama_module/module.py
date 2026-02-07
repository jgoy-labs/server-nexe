"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/module.py
Description: Main integration module for Ollama. Manages connection to the local API,

www.jgoy.net
────────────────────────────────────
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional, AsyncIterator

try:
  import httpx
except ImportError:
  httpx = None

from core.resilience import ollama_breaker, CircuitOpenError
from core.loader.protocol import HealthResult, HealthStatus
from .i18n import get_i18n

logger = logging.getLogger(__name__)

# Configurable timeout via environment variable
OLLAMA_CONNECTION_TIMEOUT = float(os.getenv('NEXE_OLLAMA_CONNECTION_TIMEOUT', '10.0'))

class OllamaModule:
  """
  Ollama integration module (local LLM option).

  Features:
  - List available local models
  - Download new models
  - Chat with streaming
  - Detailed model info

  One of the many LLM options that Nexe will support.
  """

  DEFAULT_BASE_URL = "http://localhost:11434"

  def __init__(self, base_url: Optional[str] = None, i18n=None):
    """
    Initialize the Ollama module.

    Args:
      base_url: Ollama API base URL (default: localhost:11434)
      i18n: Internationalization service (optional)
    """
    if base_url is None:
      base_url = (
        os.getenv("NEXE_OLLAMA_HOST")
        or os.getenv("OLLAMA_HOST")
        or self.DEFAULT_BASE_URL
      )

    self.base_url = base_url.rstrip("/")
    self.i18n = i18n
    self.name = "ollama_module"
    self.version = "1.0.0"
    self.timeout = 30.0
    self.pull_timeout = 600.0

    logger.info(
      self._t(
        "logs.module_initialized",
        "OllamaModule initialized - base_url={base_url}",
        base_url=self.base_url,
      )
    )

  def _t(self, key: str, fallback: str, **kwargs) -> str:
    """
    Helper to translate with fallback.

    Args:
      key: Translation key
      fallback: Default text
      **kwargs: Format parameters

    Returns:
      Translated text or fallback
    """
    if not self.i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    try:
      value = self.i18n.t(key, **kwargs)
      if value == key:
        return fallback.format(**kwargs) if kwargs else fallback
      return value
    except Exception:
      return fallback.format(**kwargs) if kwargs else fallback

  async def check_connection(self) -> bool:
    """
    Check whether Ollama is reachable.

    Returns:
      True if connected, False otherwise
    """
    try:
      async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
        response = await client.get(f"{self.base_url}/api/tags")
        return response.status_code == 200
    except CircuitOpenError:
      logger.warning(
        self._t(
          "logs.circuit_open",
          "Circuit breaker OPEN for Ollama - skipping connection check"
        )
      )
      return False

  async def health_check(self) -> HealthResult:
    """Health check for the Ollama module."""
    if httpx is None:
      return HealthResult(
        status=HealthStatus.UNKNOWN,
        message=self._t(
          "logs.httpx_missing",
          "httpx not installed"
        )
      )

    try:
      connected = await self.check_connection()
      if connected:
        return HealthResult(
          status=HealthStatus.HEALTHY,
          message=self._t(
            "logs.ollama_reachable",
            "Ollama reachable"
          )
        )
      return HealthResult(
        status=HealthStatus.UNHEALTHY,
        message=self._t(
          "logs.ollama_unreachable",
          "Ollama not reachable"
        )
      )
    except Exception as e:
      return HealthResult(
        status=HealthStatus.DEGRADED,
        message=str(e)
      )
    except Exception as e:
      msg = self._t("logs.connection_check_failed", "Comprovacio de connexio amb Ollama fallida: {error}", error=str(e))
      logger.warning(msg)
      return False

  @ollama_breaker.protect
  async def list_models(self) -> List[Dict[str, Any]]:
    """
    List all available local models.
    Protected by Circuit Breaker.

    Returns:
      List of models with metadata

    Raises:
      httpx.HTTPError: If Ollama is not available
      CircuitOpenError: If the circuit breaker is open
    """
    async with httpx.AsyncClient(timeout=self.timeout) as client:
      response = await client.get(f"{self.base_url}/api/tags")
      response.raise_for_status()

      data = response.json()
      models = data.get("models", [])

      msg = self._t("logs.models_found", "Trobats {count} models d'Ollama", count=len(models))
      logger.info(msg)
      return models

  async def pull_model(self, model_name: str) -> AsyncIterator[Dict[str, Any]]:
    """
    Download an Ollama model (streaming progress).
    Protected by Circuit Breaker via guard_streaming.

    Args:
      model_name: Model name to download (ex: "mistral:latest")

    Yields:
      Dicts with download status

    Raises:
      httpx.HTTPError: If the download fails
      CircuitOpenError: If the circuit breaker is open
    """
    if not await ollama_breaker.check_circuit():
      raise CircuitOpenError(
        self._t(
          "logs.circuit_open_error",
          "Circuit [ollama] is OPEN. Will retry in {timeout}s",
          timeout=ollama_breaker.config.timeout_seconds,
        )
      )

    try:
      async with httpx.AsyncClient(timeout=self.pull_timeout) as client:
        async with client.stream(
          "POST",
          f"{self.base_url}/api/pull",
          json={"name": model_name}
        ) as response:
          response.raise_for_status()
          await ollama_breaker.record_success()

          async for line in response.aiter_lines():
            if line.strip():
              try:
                data = json.loads(line)
                yield data
              except json.JSONDecodeError:
                msg = self._t("logs.invalid_json_pull", "JSON invalid a la resposta de pull: {line}", line=line)
                logger.warning(msg)

    except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
      await ollama_breaker.record_failure(e)
      msg = self._t("logs.pull_failed", "Error descarregant model {model}: {error}", model=model_name, error=str(e))
      logger.error(msg)
      raise

  @ollama_breaker.protect
  async def get_model_info(self, model_name: str) -> Dict[str, Any]:
    """
    Get detailed model information.
    Protected by Circuit Breaker.

    Args:
      model_name: Model name

    Returns:
      Dict with model info (modelfile, parameters, template, etc.)

    Raises:
      httpx.HTTPError: If the model does not exist or API error
      CircuitOpenError: If the circuit breaker is open
    """
    async with httpx.AsyncClient(timeout=self.timeout) as client:
      response = await client.post(
        f"{self.base_url}/api/show",
        json={"name": model_name}
      )
      response.raise_for_status()

      return response.json()

  async def chat(
    self,
    model: str,
    messages: List[Dict[str, str]],
    stream: bool = True
  ) -> AsyncIterator[Dict[str, Any]]:
    """
    Send messages to a model and receive responses (optional streaming).
    Protected by Circuit Breaker via public methods.

    Args:
      model: Model name to use
      messages: List of messages [{"role": "user", "content": "..."}]
      stream: If True, stream the response

    Yields:
      Dicts with response chunks if stream=True
      Or a single dict with the full response if stream=False

    Raises:
      httpx.HTTPError: If the request fails
      CircuitOpenError: If the circuit breaker is open
    """
    if not await ollama_breaker.check_circuit():
      raise CircuitOpenError(
        self._t(
          "logs.circuit_open_error",
          "Circuit [ollama] is OPEN. Will retry in {timeout}s",
          timeout=ollama_breaker.config.timeout_seconds,
        )
      )

    try:
      # Stop sequences per diferents models
      stop_sequences = [
        "<|end|>", "<|endoftext|>", "<|assistant|>",  # Phi-3.5, GPT
        "</s>",  # Llama
        "<end_of_turn>",  # Gemma
        "<|im_end|>",  # ChatML format
      ]

      payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "stop": stop_sequences
      }

      async with httpx.AsyncClient(timeout=120.0) as client:
        if stream:
          async with client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload
          ) as response:
            response.raise_for_status()
            await ollama_breaker.record_success()

            async for line in response.aiter_lines():
              if line.strip():
                try:
                  data = json.loads(line)
                  yield data
                except json.JSONDecodeError:
                  msg = self._t("logs.invalid_json_chat", "JSON invalid a la resposta de xat: {line}", line=line)
                  logger.warning(msg)
        else:
          response = await client.post(
            f"{self.base_url}/api/chat",
            json=payload
          )
          response.raise_for_status()
          await ollama_breaker.record_success()
          yield response.json()

    except (httpx.HTTPError, ConnectionError, TimeoutError) as e:
      await ollama_breaker.record_failure(e)
      msg = self._t("logs.chat_failed", "Peticio de xat fallida amb model {model}: {error}", model=model, error=str(e))
      logger.error(msg)
      raise

  @ollama_breaker.protect
  async def delete_model(self, model_name: str) -> bool:
    """
    Delete a local model.
    Protected by Circuit Breaker.

    Args:
      model_name: Model name to delete

    Returns:
      True if deleted successfully

    Raises:
      httpx.HTTPError: If deletion fails
      CircuitOpenError: If the circuit breaker is open
    """
    async with httpx.AsyncClient(timeout=self.timeout) as client:
      response = await client.delete(
        f"{self.base_url}/api/delete",
        json={"name": model_name}
      )
      response.raise_for_status()

      msg = self._t("logs.model_deleted", "Model {model} eliminat correctament", model=model_name)
      logger.info(msg)
      return True

  def get_info(self) -> Dict[str, Any]:
    """Return module information."""
    return {
      "name": self.name,
      "version": self.version,
      "description": self._t("info.description", "Ollama integration for local LLM model management"),
      "base_url": self.base_url,
      "features": [
        self._t("info.features.list_models", "List local models"),
        self._t("info.features.pull_models", "Download new models with progress"),
        self._t("info.features.stream_chat", "Chat with streaming responses"),
        self._t("info.features.model_info", "Detailed model info"),
        self._t("info.features.delete_models", "Delete models")
      ],
      "location": "core/tools/ollama_module/",
      "type": "local_llm_option",
      "note": self._t("info.note", "One of the many LLM options Nexe will support")
    }

def _load_i18n_for_cli():
  """Helper to load i18n for the CLI main() function."""
  try:
    return get_i18n()
  except Exception:
    return None

async def main():
  """Main function to run the module."""
  i18n = _load_i18n_for_cli()

  def _t(key: str, fallback: str, **kwargs) -> str:
    """Local translation helper."""
    if not i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    try:
      value = i18n.t(key, **kwargs)
      if value == key:
        return fallback.format(**kwargs) if kwargs else fallback
      return value
    except Exception:
      return fallback.format(**kwargs) if kwargs else fallback

  def _print_banner(lines: List[str]) -> None:
    content_width = 59
    top = "  ╔" + ("═" * content_width) + "╗"
    empty = "  ║" + (" " * content_width) + "║"
    print(top)
    print(empty)
    for line in lines:
      text = line.strip()
      if len(text) > content_width:
        text = text[:content_width]
      print("  ║" + text.center(content_width) + "║")
    print(empty)
    print("  ╚" + ("═" * content_width) + "╝")

  _print_banner([
    _t("cli.banner.title", "🤖 Nexe OLLAMA MODULE v1.0"),
    _t("cli.banner.line1", "Ollama integration (local LLM option)"),
    _t("cli.banner.line2", "Local LLM model management")
  ])

  ollama = OllamaModule(i18n=i18n)

  print(_t("cli.checking_connection", "🔌 Checking connection to Ollama..."))
  connected = await ollama.check_connection()

  if not connected:
    print(_t("cli.not_available", "❌ Ollama is not available at {url}", url=ollama.base_url))
    print(_t("cli.ensure_running", "  Make sure Ollama is running: ollama serve"))
    return 1

  print(_t("cli.connected", "✅ Connected to Ollama!"))

  print(_t("cli.available_models", "\n📦 Available models:"))
  try:
    models = await ollama.list_models()
    if not models:
      print(_t("cli.no_models", "  → No models installed"))
      print(_t("cli.download_hint", "  → Download a model: ollama pull mistral"))
    else:
      for model in models:
        name = model.get("name", "unknown")
        size = model.get("size", 0) / (1024**3)
        print(_t("cli.model_item", "  • {name} ({size:.2f} GB)", name=name, size=size))
  except Exception as e:
    print(_t("cli.error", "  ❌ Error: {error}", error=str(e)))
    return 1

  print(_t("cli.total_models", "\n📊 Total: {count} models", count=len(models)))
  print(_t("cli.web_chat_info", "\nTo use the web chatbot:"))
  print(_t("cli.start_server", " → Start the Nexe server"))
  print(_t("cli.visit_url", " → Visit: http://localhost:9119/ui-control/ollama/"))

  return 0

if __name__ == "__main__":
  import asyncio
  import sys
  sys.exit(asyncio.run(main()))
