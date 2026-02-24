"""
────────────────────────────────────
Server Nexe
Version: 0.8.2
Author: Jordi Goy 
Location: core/container.py
Description: Dependency Injection Container for core services.
Avoids circular dependencies and centralizes core service access.

www.jgoy.net
────────────────────────────────────
"""

# DEPRECATED: Container no s'usa en producció des de v0.8.2
# Els serveis s'obtenen via app.state (FastAPI DI) o get_server_state().
# Mantingut per compatibilitat amb tests. Planificat per eliminar en v0.9.

import logging
import os
import warnings
from typing import Any, Dict, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Detecta si estem en context de tests (pytest) per silenciar el warning
_IN_TESTS = "PYTEST_CURRENT_TEST" in os.environ

_DEPRECATION_MSG = (
  "Container està DEPRECATED des de v0.8.2 i s'eliminarà a v0.9. "
  "Per als plugins: usa 'from core.lifespan import get_server_state' per accedir "
  "als serveis (rag, memory, modules...). Per als endpoints FastAPI: usa 'request.app.state'."
)

class Container:
  """
  Central registry for dependency injection.

  DEPRECATED des de v0.8.2 — només per a tests.
  Patró nou per a plugins: get_server_state().rag / get_server_state().memory_engine
  Patró nou per a endpoints: request.app.state.rag / request.app.state.memory_engine
  """
  _instance: Optional['Container'] = None
  _services: Dict[str, Any] = {}
  _factories: Dict[str, Any] = {}

  def __new__(cls):
    if cls._instance is None:
      cls._instance = super().__new__(cls)
    return cls._instance

  @classmethod
  def register(cls, name: str, service: Any) -> None:
    """[DEPRECATED] Registra una instància de servei."""
    if not _IN_TESTS:
      warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
      logger.warning("Container.register('%s') — %s", name, _DEPRECATION_MSG)
    cls._services[name] = service
    logger.debug(f"Service registered: {name}")

  @classmethod
  def register_factory(cls, name: str, factory: Any) -> None:
    """[DEPRECATED] Registra una factory de servei."""
    if not _IN_TESTS:
      warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
      logger.warning("Container.register_factory('%s') — %s", name, _DEPRECATION_MSG)
    cls._factories[name] = factory
    logger.debug(f"Service factory registered: {name}")

  @classmethod
  def get(cls, name: str, default: Any = None) -> Any:
    """[DEPRECATED] Obté un servei pel nom."""
    if not _IN_TESTS:
      warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
      logger.warning("Container.get('%s') — %s", name, _DEPRECATION_MSG)
    if name in cls._services:
      return cls._services[name]

    if name in cls._factories:
      logger.debug(f"Initializing service from factory: {name}")
      service = cls._factories[name]()
      cls._services[name] = service
      return service

    return default

  @classmethod
  def clear(cls):
    """Buida el container (útil per a tests)."""
    cls._services.clear()
    cls._factories.clear()
    logger.info("DI Container cleared")

# Shortcut functions — DEPRECATED, mantingudes per compatibilitat
def get_service(name: str, default: Any = None) -> Any:
  return Container.get(name, default)

def register_service(name: str, service: Any) -> None:
  Container.register(name, service)

__all__ = ['Container', 'get_service', 'register_service']
