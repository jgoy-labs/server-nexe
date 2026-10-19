"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/api_module/module.py
Description: The API engine: chat with an external OpenAI-compatible provider.

             It follows the engine contract by duck typing, Ollama's style:
             `chat(model, messages, stream, images, thinking_enabled, top_p,
             cancel_event)` (the `model` parameter is what makes
             `core/turn/engine_start.py` call it that way), plus
             `can_see_images` and `get_context_window`. It declares neither
             `can_continue` (a provider cannot resume mid-sentence) nor
             `is_model_loaded` (nothing loads).

             The module holds NO model. The questions the turn asks of an engine
             (its window, whether it sees) carry no model argument, and phase 2
             answered them from a model remembered on the module — state shared by
             every turn. Phase 3: the turn is handed `for_model(model)`, a view of
             the module for ONE model (`ApiTurnEngine`), and asks that; the module's
             own `can_see_images(model)` / `get_context_window(model)` are stateless.

             It is opt-in by construction: it is not in the engine cascade, and
             the web door only reaches it after the cloud gate
             (`core/providers/cloud.py`: global switch + consent per session).
             The module itself holds no key: `chat` asks the registry for it at
             the moment of the request.

             Core imports are deferred (layering gate, #471).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import contextlib
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import APIRouter

from .chat import run_chat, where_you_run

logger = logging.getLogger(__name__)


class ApiModule:
    """External API engine (NexeModule + NexeModuleWithRouter, no routes)."""

    #: What this engine is sent leaves the machine. The core asks it by this
    #: attribute (exactly `True`), never by the engine's name alone.
    runs_in_the_cloud = True

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        #: Tests inject a fake endpoint here; production passes nothing.
        self._transport = transport
        self._initialized = False
        self._router: Optional[APIRouter] = None

    # --- NexeModule Protocol ---

    @property
    def metadata(self):
        from core.modules.protocol import ModuleMetadata  # deferred (layering gate)

        return ModuleMetadata(
            name="api_module",
            version="0.1.0",
            description="Engine for external OpenAI-compatible API providers (opt-in)",
            author="Jordi Goy",
            module_type="cloud_llm_option",
            quadrant="core",
            dependencies=[],
            tags=["api", "llm", "chat", "cloud"],
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        self._initialized = True
        return True

    async def shutdown(self) -> None:
        self._initialized = False

    async def health_check(self):
        """Presence only: no request, no key read beyond "is there one"."""
        from core.modules.protocol import HealthResult, HealthStatus  # deferred
        from core.providers import provider_status

        configured = [p["key"] for p in provider_status()["providers"] if p["configured"]]
        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="API engine ready (opt-in)",
            details={"configured_providers": configured},
        )

    # --- NexeModuleWithRouter (no routes of its own) ---

    def get_router(self) -> APIRouter:
        return self._router if self._router is not None else APIRouter()

    def get_router_prefix(self) -> str:
        return "/api-engine"

    def _init_router(self) -> None:
        self._router = APIRouter()

    # --- Engine contract ---

    def for_model(self, model: Optional[str]) -> "ApiTurnEngine":
        """This engine as ONE turn sees it: bound to the model the turn chose."""
        return ApiTurnEngine(self, model)

    def can_see_images(self, model: Optional[str] = None) -> bool:
        """Per model, as the registry entry declares it; no model, no sight."""
        from core.providers.registry import model_can_see_images, provider_for_model  # deferred

        provider = provider_for_model(model)
        return provider is not None and model_can_see_images(provider, model)

    def get_context_window(self, model: Optional[str] = None) -> Optional[int]:
        """Per model, from the registry entry; None for a model nobody owns."""
        from core.providers.registry import model_context_window, provider_for_model  # deferred

        provider = provider_for_model(model)
        return model_context_window(provider, model) if provider is not None else None

    def chat(
        self, model: str, messages: List[Dict[str, Any]], stream: bool = True,
        images: Optional[List[str]] = None, thinking_enabled: bool = False,
        top_p: Optional[float] = None, cancel_event: Optional[Any] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Chat with `model` at its provider. Raises ValueError (a bad request,
        terminal) when the global switch is off, for a model no provider owns, a
        missing or unusable key, or an image sent to a model that cannot read one.

        `thinking_enabled` is accepted and unused: whether a provider's model
        reasons is the model's own nature (deepseek-reasoner always does), and
        the reasoning it streams is mapped to `message.thinking` either way.

        `cancel_event` (a `threading.Event`, the turn's: the client left or the
        deadline ran out) stops the HTTP read and closes the connection — a
        deadline only sets it, nothing cancels the asyncio task.
        """
        return self._chat(model, messages, stream, images, top_p, cancel_event)

    async def _chat(self, model, messages, stream, images, top_p, cancel_event) -> AsyncIterator[Dict[str, Any]]:
        from core.providers.cloud import cloud_engines_allowed  # deferred (layering gate)
        from core.providers.connection import is_header_safe
        from core.providers.registry import model_can_see_images, provider_for_model, read_api_key

        # The last line of defence, and the one every path shares (a turn, its compaction, an image
        # description, the re-prompt): the global switch is read at the moment of EACH request, so
        # turning it off stops the next call even of a turn that was already running.
        # Each refusal is on purpose: final, and said with a curated sentence (C4.8 P2-7).
        from core.turn.errors import BadRequest  # deferred: a plugin pulls no core at import time (#471)
        if not cloud_engines_allowed():
            raise BadRequest("Cloud engines are turned off")
        provider = provider_for_model(model)
        if provider is None:
            raise BadRequest("That model does not belong to any API provider")
        if images and not model_can_see_images(provider, model):
            raise BadRequest(f"{model} cannot read images")
        api_key = read_api_key(provider)
        if not api_key:
            raise BadRequest(f"{provider.name} has no key configured")
        if not is_header_safe(api_key):
            raise BadRequest(f"The {provider.name} key cannot be sent as a header")
        # `aclosing`: closing this generator must close the exchange under it now, not when the garbage
        # collector gets to it (an `async for` does not close what it iterates, PEP 525).
        messages = where_you_run(messages, provider.name, model)
        async with contextlib.aclosing(run_chat(provider, api_key, model, messages, stream, images, top_p,
                                                self._transport, cancel_event)) as chunks:
            async for chunk in chunks:
                yield chunk


class ApiTurnEngine:
    """The API engine for one turn: the module, and the model the turn chose.

    Built by `ApiModule.for_model` where the turn's candidates are made, so
    everything downstream — the window the prompt is fitted to, whether an image
    may be sent, the model a compaction asks for — answers for THIS turn's model,
    and two turns on two models cannot read each other's. Holds no key and makes
    no request: `chat` is the module's.
    """

    runs_in_the_cloud = True

    def __init__(self, module: ApiModule, model: Optional[str]) -> None:
        self._module = module
        self._model = model

    @property
    def model_in_use(self) -> Optional[str]:
        """The model of this turn (internal steps — compaction — carry none of their own)."""
        return self._model

    def can_see_images(self) -> bool:
        return self._module.can_see_images(self._model)

    def get_context_window(self) -> Optional[int]:
        return self._module.get_context_window(self._model)

    def chat(
        self, model: str, messages: List[Dict[str, Any]], stream: bool = True,
        images: Optional[List[str]] = None, thinking_enabled: bool = False,
        top_p: Optional[float] = None, cancel_event: Optional[Any] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """The module's `chat`, under the same signature (the core reads it)."""
        return self._module.chat(model, messages, stream, images, thinking_enabled, top_p, cancel_event)
