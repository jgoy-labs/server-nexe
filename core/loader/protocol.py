"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/protocol.py
Description: str = ""

www.jgoy.net
────────────────────────────────────
"""

from typing import Dict, Any, List, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

class ModuleStatus(Enum):
  """Module status."""
  DISCOVERED = "discovered"
  LOADING = "loading"
  INITIALIZED = "initialized"
  RUNNING = "running"
  DEGRADED = "degraded"
  FAILED = "failed"
  STOPPED = "stopped"

class HealthStatus(Enum):
  """Module health status."""
  HEALTHY = "healthy"
  DEGRADED = "degraded"
  UNHEALTHY = "unhealthy"
  UNKNOWN = "unknown"

@dataclass
class ModuleMetadata:
  """
  Module metadata - read from manifest.toml.

  The kernel only needs this data to manage the module.
  It does not know what the module does internally.
  """
  name: str
  version: str
  description: str = ""
  author: str = ""
  license: str = "AGPL-3.0"

  module_type: str = "module"

  quadrant: str = "core"

  dependencies: List[str] = field(default_factory=list)

  tags: List[str] = field(default_factory=list)

  manifest_path: Optional[str] = None

  module_path: Optional[str] = None

@dataclass
class HealthResult:
  """Health check result."""
  status: HealthStatus
  message: str = ""
  details: Dict[str, Any] = field(default_factory=dict)
  checks: List[Dict[str, Any]] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status.value,
      "message": self.message,
      "details": self.details,
      "checks": self.checks
    }

@dataclass
class SpecialistInfo:
  """
  Information about a specialist the module exposes or consumes.

  Specialists are specialized components that can be
  "sent" to other modules or "received" from other modules.
  """
  name: str
  specialist_type: str
  file_path: str
  target_module: Optional[str] = None

@runtime_checkable
class NexeModule(Protocol):
  """
  Protocol that defines the minimal interface of a Nexe module.

  The kernel loads modules that implement this protocol.
  It is "runtime_checkable" to allow isinstance() checks.

  Example implementation:

  ```python
  class MyModule:
    @property
    def metadata(self) -> ModuleMetadata:
      return ModuleMetadata(
        name="my_module",
        version="1.0.0",
        description="My module"
      )

    async def initialize(self, context: Dict[str, Any]) -> bool:
      return True

    async def shutdown(self) -> None:
      pass

    async def health_check(self) -> HealthResult:
      return HealthResult(
        status=HealthStatus.HEALTHY,
        message="All good"
      )
  ```
  """

  @property
  def metadata(self) -> ModuleMetadata:
    """
    Return the module metadata.

    This data is used to:
    - Register the module in the system
    - Check dependencies
    - Show information to the user
    """
    ...

  async def initialize(self, context: Dict[str, Any]) -> bool:
    """
    Initialize the module with the provided context.

    Args:
      context: Dictionary with services and configuration:
        - config: Global configuration
        - services: Shared services (logger, i18n, etc.)
        - modules: Reference to the module registry

    Returns:
      True if initialization succeeds, False otherwise
    """
    ...

  async def shutdown(self) -> None:
    """
    Stop the module and release resources.

    Executed when the server stops or the module is unloaded.
    Must be idempotent (can be called multiple times).
    """
    ...

  async def health_check(self) -> HealthResult:
    """
    Return the module health status.

    Runs periodically by the monitoring system.
    Must be fast (< 1 second).

    Returns:
      HealthResult with the current status
    """
    ...

@runtime_checkable
class NexeModuleWithRouter(NexeModule, Protocol):
  """
  Extension of NexeModule for modules that expose HTTP endpoints.

  Modules with a router are automatically registered in FastAPI.
  """

  def get_router(self) -> Any:
    """
    Return the module's FastAPI router.

    Returns:
      fastapi.APIRouter with the module endpoints
    """
    ...

  def get_router_prefix(self) -> str:
    """
    Return the URL prefix for the router.

    Example: "/security" -> endpoints at /security/*

    Returns:
      String with the prefix (must start with /)
    """
    ...

@runtime_checkable
class NexeModuleWithSpecialists(NexeModule, Protocol):
  """
  Extension of NexeModule for modules that manage specialists.

  Specialists are components that can be sent to other
  modules or received from other modules to perform checks or actions.
  """

  def get_outgoing_specialists(self) -> List[SpecialistInfo]:
    """
    Return the list of specialists this module sends.

    Example: The Security module can send a SecuritySpecialist
    to modules that offer security capabilities.
    """
    ...

  def get_incoming_specialist_types(self) -> List[str]:
    """
    Return the specialist types this module accepts.

    Example: The security module accepts specialists of type
    "security", "memory", "performance", etc.
    """
    ...

  async def register_specialist(self, specialist: Any) -> bool:
    """
    Register an incoming specialist with the module.

    Args:
      specialist: Specialist instance to register

    Returns:
      True if registration succeeds
    """
    ...

def validate_module(module: Any) -> bool:
  """
  Validate that an object implements the NexeModule protocol.

  Args:
    module: Object to validate

  Returns:
    True if it implements the protocol correctly
  """
  if not isinstance(module, NexeModule):
    return False

  try:
    meta = module.metadata
    if not isinstance(meta, ModuleMetadata):
      return False
  except Exception:
    return False

  return True

def module_has_router(module: Any) -> bool:
  """Check whether the module has an HTTP router."""
  return isinstance(module, NexeModuleWithRouter)

def module_has_specialists(module: Any) -> bool:
  """Check whether the module manages specialists."""
  return isinstance(module, NexeModuleWithSpecialists)
