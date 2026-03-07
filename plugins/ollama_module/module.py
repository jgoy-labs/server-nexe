"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/module.py
Description: Mòdul principal d'integració amb Ollama. Gestiona connexió amb API local,

www.jgoy.net
────────────────────────────────────
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional, AsyncIterator
from pathlib import Path

try:
  import httpx
except ImportError:
  httpx = None

from core.resilience import ollama_breaker, CircuitOpenError
from core.loader.protocol import HealthResult, HealthStatus

logger = logging.getLogger(__name__)

# Configurable timeout via environment variable
OLLAMA_CONNECTION_TIMEOUT = float(os.getenv('NEXE_OLLAMA_CONNECTION_TIMEOUT', '10.0'))

class OllamaModule:
  """
  Mòdul d'integració amb Ollama (opció local per LLM).

  Funcionalitats:
  - Llistar models locals disponibles
  - Descarregar nous models
  - Chat amb streaming
  - Info detallada de models

  Una de les moltes opcions de LLM que Nexe suportarà.
  """

  DEFAULT_BASE_URL = "http://localhost:11434"

  def __init__(self, base_url: Optional[str] = None, i18n=None):
    """
    Inicialitza el mòdul Ollama.

    Args:
      base_url: URL base d'Ollama API (default: localhost:11434)
      i18n: Servei d'internacionalització (opcional)
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

    logger.info("OllamaModule initialized - base_url=%s", self.base_url)

  def _t(self, key: str, fallback: str, **kwargs) -> str:
    """
    Helper per traduir amb fallback.

    Args:
      key: Clau de traducció
      fallback: Text per defecte
      **kwargs: Paràmetres de format

    Returns:
      Text traduït o fallback
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
    Verifica si Ollama està accessible.

    Returns:
      True si connectat, False altrament
    """
    try:
      async with httpx.AsyncClient(timeout=OLLAMA_CONNECTION_TIMEOUT) as client:
        response = await client.get(f"{self.base_url}/api/tags")
        return response.status_code == 200
    except CircuitOpenError:
      logger.warning("Circuit breaker OPEN for Ollama - skipping connection check")
      return False

  async def health_check(self) -> HealthResult:
    """Health check del mòdul Ollama."""
    if httpx is None:
      return HealthResult(
        status=HealthStatus.UNKNOWN,
        message="httpx not installed"
      )

    try:
      connected = await self.check_connection()
      if connected:
        return HealthResult(
          status=HealthStatus.HEALTHY,
          message="Ollama reachable"
        )
      return HealthResult(
        status=HealthStatus.UNHEALTHY,
        message="Ollama not reachable"
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
    Llista tots els models locals disponibles.
    Protected by Circuit Breaker.

    Returns:
      Llista de models amb metadata

    Raises:
      httpx.HTTPError: Si Ollama no esta disponible
      CircuitOpenError: Si el circuit breaker esta obert
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
    Descarrega un model d'Ollama (streaming de progres).
    Protected by Circuit Breaker via guard_streaming.

    Args:
      model_name: Nom del model a descarregar (ex: "mistral:latest")

    Yields:
      Diccionaris amb status de la descarrega

    Raises:
      httpx.HTTPError: Si falla la descarrega
      CircuitOpenError: Si el circuit breaker esta obert
    """
    if not await ollama_breaker.check_circuit():
      raise CircuitOpenError(
        f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
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
    Obte informacio detallada d'un model.
    Protected by Circuit Breaker.

    Args:
      model_name: Nom del model

    Returns:
      Dict amb info del model (modelfile, parameters, template, etc.)

    Raises:
      httpx.HTTPError: Si model no existeix o error d'API
      CircuitOpenError: Si el circuit breaker esta obert
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
    Envia missatges al model i rep respostes (amb streaming opcional).
    Protected by Circuit Breaker via public methods.

    Args:
      model: Nom del model a usar
      messages: Llista de missatges [{"role": "user", "content": "..."}]
      stream: Si True, fa streaming de la resposta

    Yields:
      Diccionaris amb chunks de resposta si stream=True
      O un sol dict amb resposta completa si stream=False

    Raises:
      httpx.HTTPError: Si falla la peticio
      CircuitOpenError: Si el circuit breaker esta obert
    """
    if not await ollama_breaker.check_circuit():
      raise CircuitOpenError(
        f"Circuit [ollama] is OPEN. Will retry in {ollama_breaker.config.timeout_seconds}s"
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
    Elimina un model local.
    Protected by Circuit Breaker.

    Args:
      model_name: Nom del model a eliminar

    Returns:
      True si eliminat correctament

    Raises:
      httpx.HTTPError: Si falla l'eliminacio
      CircuitOpenError: Si el circuit breaker esta obert
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
    """Retorna informació del mòdul"""
    return {
      "name": self.name,
      "version": self.version,
      "description": self._t("info.description", "Integració amb Ollama per gestió de models LLM locals"),
      "base_url": self.base_url,
      "features": [
        "Llistar models locals",
        "Descarregar nous models amb progrés",
        "Chat amb streaming de respostes",
        "Info detallada de models",
        "Eliminació de models"
      ],
      "location": "core/tools/ollama_module/",
      "type": "local_llm_option",
      "note": "Una de les moltes opcions de LLM que Nexe suportarà"
    }

def _load_i18n_for_cli():
  """Helper per carregar i18n per la funció main() de CLI"""
  try:
    from personality.i18n import I18nService
    i18n_service = I18nService()
    i18n_service.load_translations_from_dir(Path(__file__).parent / "languages")
    return i18n_service
  except Exception:
    return None

async def main():
  """Funció principal per executar el mòdul"""
  print("""
  ╔═══════════════════════════════════════════════════════════╗
  ║                              ║
  ║  🤖 Nexe OLLAMA MODULE v1.0               ║
  ║                              ║
  ║  Integració amb Ollama (opció local per LLM)     ║
  ║  Gestió de models LLM locals              ║
  ║                              ║
  ╚═══════════════════════════════════════════════════════════╝
  """)

  i18n = _load_i18n_for_cli()
  ollama = OllamaModule(i18n=i18n)

  def _t(key: str, fallback: str, **kwargs) -> str:
    """Helper local per traduir"""
    if not i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    try:
      value = i18n.t(key, **kwargs)
      if value == key:
        return fallback.format(**kwargs) if kwargs else fallback
      return value
    except Exception:
      return fallback.format(**kwargs) if kwargs else fallback

  print(_t("cli.checking_connection", "🔌 Comprovant connexió amb Ollama..."))
  connected = await ollama.check_connection()

  if not connected:
    print(_t("cli.not_available", "❌ Ollama no està disponible a {url}", url=ollama.base_url))
    print(_t("cli.ensure_running", "  Assegura't que Ollama està en marxa: ollama serve"))
    return 1

  print(_t("cli.connected", "✅ Connectat a Ollama!"))

  print(_t("cli.available_models", "\n📦 Models disponibles:"))
  try:
    models = await ollama.list_models()
    if not models:
      print(_t("cli.no_models", "  → Cap model instal·lat"))
      print(_t("cli.download_hint", "  → Descarrega un model: ollama pull mistral"))
    else:
      for model in models:
        name = model.get("name", "unknown")
        size = model.get("size", 0) / (1024**3)
        print(_t("cli.model_item", "  • {name} ({size:.2f} GB)", name=name, size=size))
  except Exception as e:
    print(_t("cli.error", "  ❌ Error: {error}", error=str(e)))
    return 1

  print(_t("cli.total_models", "\n📊 Total: {count} models", count=len(models)))
  print(_t("cli.web_chat_info", "\nPer usar el chatbot web:"))
  print(_t("cli.start_server", " → Inicia el servidor Nexe"))
  _nexe_url = os.environ.get("NEXE_API_BASE_URL", "http://localhost:9119")
  print(_t("cli.visit_url", f" → Visita: {_nexe_url}/ui-control/ollama/"))

  return 0

if __name__ == "__main__":
  import asyncio
  import sys
  sys.exit(asyncio.run(main()))
