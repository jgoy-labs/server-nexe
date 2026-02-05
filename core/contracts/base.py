"""
Base contracts system for NEXE 0.9

Protocols i dataclasses per definir contractes unificats de plugins.
"""

from typing import Dict, List, Optional, Any, Protocol, runtime_checkable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime


# ============================================
# ENUMS
# ============================================

class ContractType(str, Enum):
    """Tipus de contracte"""
    MODULE = "module"
    CORE = "core"


class HealthStatus(str, Enum):
    """Estat de salut d'un contracte"""
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
    Metadata unificada per tots els contractes.

    Defineix informació bàsica que tot contracte (plugin) ha de proporcionar.
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
        """Retorna True si és un module"""
        return self.contract_type == ContractType.MODULE

    def is_core(self) -> bool:
        """Retorna True si és core"""
        return self.contract_type == ContractType.CORE

    def has_capability(self, capability: str) -> bool:
        """Check si té una capability específica"""
        return self.capabilities.get(capability, False)

    def to_dict(self) -> Dict[str, Any]:
        """Converteix a diccionari"""
        return asdict(self)


@dataclass
class HealthResult:
    """Resultat d'un health check"""
    status: HealthStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def is_healthy(self) -> bool:
        """Retorna True si està healthy"""
        return self.status == HealthStatus.HEALTHY

    def is_degraded(self) -> bool:
        """Retorna True si està degraded"""
        return self.status == HealthStatus.DEGRADED

    def is_unhealthy(self) -> bool:
        """Retorna True si està unhealthy"""
        return self.status == HealthStatus.UNHEALTHY

    def to_dict(self) -> Dict[str, Any]:
        """Converteix a diccionari"""
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
    Protocol base per tots els contractes NEXE.

    Defineix el mínim comú que tot contracte (plugin) ha d'implementar.
    """

    @property
    def metadata(self) -> ContractMetadata:
        """Retorna metadata del contracte"""
        ...

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """
        Inicialitza el contracte.

        Args:
            context: Diccionari amb configuració i dependències

        Returns:
            True si inicialització OK, False altrament
        """
        ...

    async def shutdown(self) -> None:
        """Shutdown graceful del contracte"""
        ...

    async def health_check(self) -> HealthResult:
        """
        Health check del contracte.

        Returns:
            HealthResult amb estat actual
        """
        ...


@runtime_checkable
class ModuleContract(BaseContract, Protocol):
    """
    Protocol per modules (plugins estàndard).

    Extends BaseContract amb funcionalitat específica de plugins:
    - Proporcionar router FastAPI (si has_api=true)
    - Proporcionar prefix de rutes
    """

    def get_router(self) -> Optional[Any]:
        """
        Retorna el router FastAPI del module.

        Returns:
            APIRouter si el module té API, None altrament
        """
        ...

    def get_router_prefix(self) -> str:
        """
        Retorna el prefix de rutes del module.

        Returns:
            Prefix (e.g., "/ollama", "/security")
        """
        ...


# ============================================
# HELPER FUNCTIONS
# ============================================

def validate_contract(obj: Any) -> bool:
    """
    Valida que un objecte implementa BaseContract.

    Args:
        obj: Objecte a validar

    Returns:
        True si implementa BaseContract
    """
    return isinstance(obj, BaseContract)


def contract_is_module(obj: Any) -> bool:
    """
    Check si un objecte és un ModuleContract.

    Args:
        obj: Objecte a verificar

    Returns:
        True si implementa ModuleContract
    """
    return isinstance(obj, ModuleContract)


def get_contract_info(contract: BaseContract) -> Dict[str, Any]:
    """
    Extreu informació resumida d'un contracte.

    Args:
        contract: Contracte a inspeccionar

    Returns:
        Diccionari amb info del contracte
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
