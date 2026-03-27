"""
────────────────────────────────────
Server Nexe
Version: 0.8.2
Author: Jordi Goy 
Location: core/container.py
Description: Dependency Injection Container for core services.
Avoids circular dependencies and centralizes core service access.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

# DEPRECATED: Container has not been used in production since v0.8.2.
# Services are accessed via app.state (FastAPI DI) or get_server_state().
# Kept for test compatibility. Scheduled for removal in v0.9.

import logging
import os
import warnings
from typing import Any, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Detect if running in a test context (pytest) to suppress the warning
_IN_TESTS = "PYTEST_CURRENT_TEST" in os.environ

_DEPRECATION_MSG = (
  "Container is DEPRECATED since v0.8.2 and will be removed in v0.9. "
  "For plugins: use 'from core.lifespan import get_server_state' to access "
  "services (rag, memory, modules...). For FastAPI endpoints: use 'request.app.state'."
)

class Container:
  """
  Central registry for dependency injection.

  DEPRECATED since v0.8.2 — only used for tests.
  New pattern for plugins: get_server_state().rag / get_server_state().memory_engine
  New pattern for endpoints: request.app.state.rag / request.app.state.memory_engine
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
    """[DEPRECATED] Register a service instance."""
    if not _IN_TESTS:
      warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
      logger.warning("Container.register('%s') — %s", name, _DEPRECATION_MSG)
    cls._services[name] = service
    logger.debug("Service registered: %s", name)

  @classmethod
  def register_factory(cls, name: str, factory: Any) -> None:
    """[DEPRECATED] Register a service factory."""
    if not _IN_TESTS:
      warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
      logger.warning("Container.register_factory('%s') — %s", name, _DEPRECATION_MSG)
    cls._factories[name] = factory
    logger.debug("Service factory registered: %s", name)

  @classmethod
  def get(cls, name: str, default: Any = None) -> Any:
    """[DEPRECATED] Retrieve a service by name."""
    if not _IN_TESTS:
      warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
      logger.warning("Container.get('%s') — %s", name, _DEPRECATION_MSG)
    if name in cls._services:
      return cls._services[name]

    if name in cls._factories:
      logger.debug("Initializing service from factory: %s", name)
      service = cls._factories[name]()
      cls._services[name] = service
      return service

    return default

  @classmethod
  def clear(cls):
    """Clear the container (useful for tests)."""
    cls._services.clear()
    cls._factories.clear()
    logger.info("DI Container cleared")

# Shortcut functions — DEPRECATED, kept for backward compatibility
def get_service(name: str, default: Any = None) -> Any:
  return Container.get(name, default)

def register_service(name: str, service: Any) -> None:
  Container.register(name, service)

__all__ = ['Container', 'get_service', 'register_service']
