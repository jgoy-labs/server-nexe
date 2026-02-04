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

import logging
from typing import Any, Dict, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')

class Container:
  """
  Central registry for dependency injection.

  Eliminates sys.modules hacks and lazy imports.
  Allows tracking of each component's lifecycle.
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
    """Registers an already created service instance."""
    cls._services[name] = service
    logger.debug(f"Service registered: {name}")

  @classmethod
  def register_factory(cls, name: str, factory: Any) -> None:
    """Registers a function that creates the service on demand (Lazy)."""
    cls._factories[name] = factory
    logger.debug(f"Service factory registered: {name}")

  @classmethod
  def get(cls, name: str, default: Any = None) -> Any:
    """Gets a service by its name."""
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
    """Clears the container (useful for tests)."""
    cls._services.clear()
    cls._factories.clear()
    logger.info("DI Container cleared")

# Shortcut functions
def get_service(name: str, default: Any = None) -> Any:
  return Container.get(name, default)

def register_service(name: str, service: Any) -> None:
  Container.register(name, service)

__all__ = ['Container', 'get_service', 'register_service']
