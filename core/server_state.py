"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/server_state.py
Description: The shared startup-state DTO + its process-wide singleton.

MC-102: extracted out of core/lifespan.py so that the lower layers
(memory / plugins) that only need to READ the shared state import a
DEPENDENCY-FREE leaf module instead of the heavy startup orchestrator.
core/lifespan.py imported memory.* (function-locally) while
memory/memory/module.py imported core.lifespan at import time — a latent
core↔memory cycle hidden behind a deferred edge. By depending on this leaf
(which imports nothing from memory/plugins/personality at runtime) the cycle
disappears WITHOUT relying on the deferred-import escape hatch.

This module must stay a leaf: import only the stdlib at runtime. Type-only
imports go under TYPE_CHECKING (annotations are lazy via `from __future__`).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:  # type-only — never imported at runtime, keeps this module a leaf
    from personality.integration import APIIntegrator


class ServerState:
  """Holds server global state.

  NOTE (finding #474): this is an intentional startup-state DTO/singleton, not a
  god-object. It carries no behaviour (data slots only), is populated on the
  sequential startup path, and the other layers (memory/plugins) only READ stable
  slots — so there is no observed race. The wide get_server_state() fan-out is
  logical coupling (P3 maintainability), not a functional defect.
  """
  def __init__(self) -> None:
    """Initialize all server-wide state slots to their defaults."""
    self.config: Dict[str, Any] = {}
    self.api_integrator: Optional[APIIntegrator] = None
    self.project_root: Optional[Path] = None
    self.i18n: Optional[Any] = None
    self.module_manager: Optional[Any] = None
    self.registry: Optional[Any] = None
    self.ollama_process: Optional[Any] = None
    self.qdrant_available: bool = False
    self.crypto_provider: Optional[Any] = None
    self._cleanup_task: Optional[asyncio.Task[Any]] = None
    self._prewarm_task: Optional[asyncio.Task[Any]] = None
    self._session_cleanup_task: Optional[asyncio.Task[Any]] = None
    self._knowledge_ingest_task: Optional[asyncio.Task[Any]] = None
    self.knowledge_ingest_complete: bool = False
    # flag set by _startup_init. If False, _startup does
    # early return abans de _startup_services + _startup_phases_and_tokens.
    self.has_onboarding: bool = False
    self.configure_modules_callback: Optional[Callable[..., None]] = None
    # MC-122: subsystems whose startup failed but was swallowed (fail-open).
    # Surfaced in the final banner so it doesn't claim READY when memory/RAG/
    # plugins are actually degraded.
    self.degraded_modules: list[str] = []


# Process-wide singleton. core.lifespan re-exports this same object for
# backward compatibility, so its identity is preserved everywhere.
server_state = ServerState()


def get_server_state() -> ServerState:
  """Get the global server state."""
  return server_state
