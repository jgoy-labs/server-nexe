"""
Base contracts system for NEXE 0.9

Protocols and dataclasses to define unified plugin contracts.
"""

from typing import Dict, List, Optional, Any, Protocol, runtime_checkable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime


# ============================================
# ENUMS
# ============================================

class ContractType(str, Enum):
    """Contract type."""
    MODULE = "module"
    CORE = "core"


class HealthStatus(str, Enum):
    """Contract health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ============================================
# DATACLASSES
# ============================================

@dataclass
class ContractMetadata:
    """
    Unified metadata for all contracts.

    Defines the basic information every contract (plugin) must provide.
    """
    # Identificació
    contract_id: str
    contract_type: ContractType
    name: str
    version: str
    description: str = ""

    # Autoria
    author: str = ""
    license: str = "AGPL-3.0"

    # Versió del sistema de contractes
    contract_version: str = "1.0"

    # Capabilities
    capabilities: Dict[str, bool] = field(default_factory=dict)

    # Dependencies
    dependencies: List[str] = field(default_factory=list)
    optional_dependencies: List[str] = field(default_factory=list)

    # Tags per categorització
    tags: List[str] = field(default_factory=list)

    # Custom metadata
    custom: Dict[str, Any] = field(default_factory=dict)

    def is_module(self) -> bool:
        """Return True if it is a module."""
        return self.contract_type == ContractType.MODULE

    def is_core(self) -> bool:
        """Return True if it is core."""
        return self.contract_type == ContractType.CORE

    def has_capability(self, capability: str) -> bool:
        """Check whether it has a specific capability."""
        return self.capabilities.get(capability, False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary."""
        return asdict(self)


@dataclass
class HealthResult:
    """Health check result."""
    status: HealthStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def is_healthy(self) -> bool:
        """Return True if healthy."""
        return self.status == HealthStatus.HEALTHY

    def is_degraded(self) -> bool:
        """Return True if degraded."""
        return self.status == HealthStatus.DEGRADED

    def is_unhealthy(self) -> bool:
        """Return True if unhealthy."""
        return self.status == HealthStatus.UNHEALTHY

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary."""
        return {
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat()
        }


# ============================================
# PROTOCOLS
# ============================================

@runtime_checkable
class BaseContract(Protocol):
    """
    Base protocol for all NEXE contracts.

    Defines the minimum common interface that every contract (plugin) must implement.
    """

    @property
    def metadata(self) -> ContractMetadata:
        """Return contract metadata."""
        ...

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """
        Initialize the contract.

        Args:
            context: Dictionary with configuration and dependencies

        Returns:
            True if initialization succeeds, False otherwise
        """
        ...

    async def shutdown(self) -> None:
        """Gracefully shut down the contract."""
        ...

    async def health_check(self) -> HealthResult:
        """
        Health check for the contract.

        Returns:
            HealthResult with current status
        """
        ...


@runtime_checkable
class ModuleContract(BaseContract, Protocol):
    """
    Protocol for modules (standard plugins).

    Extends BaseContract with plugin-specific functionality:
    - Provide a FastAPI router (if has_api=true)
    - Provide a routes prefix
    """

    def get_router(self) -> Optional[Any]:
        """
        Return the module's FastAPI router.

        Returns:
            APIRouter if the module has an API, None otherwise
        """
        ...

    def get_router_prefix(self) -> str:
        """
        Return the module routes prefix.

        Returns:
            Prefix (e.g., "/ollama", "/security")
        """
        ...


# ============================================
# HELPER FUNCTIONS
# ============================================

def validate_contract(obj: Any) -> bool:
    """
    Validate that an object implements BaseContract.

    Args:
        obj: Object to validate

    Returns:
        True if it implements BaseContract
    """
    return isinstance(obj, BaseContract)


def contract_is_module(obj: Any) -> bool:
    """
    Check whether an object is a ModuleContract.

    Args:
        obj: Object to check

    Returns:
        True if it implements ModuleContract
    """
    return isinstance(obj, ModuleContract)


def get_contract_info(contract: BaseContract) -> Dict[str, Any]:
    """
    Extract summary information about a contract.

    Args:
        contract: Contract to inspect

    Returns:
        Dictionary with contract info
    """
    meta = contract.metadata
    return {
        "id": meta.contract_id,
        "type": meta.contract_type.value,
        "name": meta.name,
        "version": meta.version,
        "description": meta.description,
        "capabilities": meta.capabilities
    }
