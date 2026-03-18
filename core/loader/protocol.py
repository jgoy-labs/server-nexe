"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/protocol.py
Description: str = ""

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any, List, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

class ModuleStatus(Enum):
  """Estat d'un mòdul"""
  DISCOVERED = "discovered"
  LOADING = "loading"
  INITIALIZED = "initialized"
  RUNNING = "running"
  DEGRADED = "degraded"
  FAILED = "failed"
  STOPPED = "stopped"

class HealthStatus(Enum):
  """Estat de salut d'un mòdul"""
  HEALTHY = "healthy"
  DEGRADED = "degraded"
  UNHEALTHY = "unhealthy"
  UNKNOWN = "unknown"

@dataclass
class ModuleMetadata:
  """
  Metadades d'un mòdul - llegides del manifest.toml

  El kernel només necessita aquestes dades per gestionar el mòdul.
  No sap què fa el mòdul internament.
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
  """Resultat d'un health check"""
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
  Informació d'un specialist que el mòdul exposa o consumeix.

  Els specialists són components especialitzats que poden ser
  "enviats" a altres mòduls o "rebuts" d'altres mòduls.
  """
  name: str
  specialist_type: str
  file_path: str
  target_module: Optional[str] = None

@runtime_checkable
class NexeModule(Protocol):
  """
  Protocol que defineix la interfície mínima d'un mòdul Nexe.

  El kernel carrega mòduls que implementen aquest protocol.
  És "runtime_checkable" per permetre isinstance() checks.

  Exemple d'implementació:

  ```python
  class MyModule:
    @property
    def metadata(self) -> ModuleMetadata:
      return ModuleMetadata(
        name="my_module",
        version="1.0.0",
        description="El meu mòdul"
      )

    async def initialize(self, context: Dict[str, Any]) -> bool:
      return True

    async def shutdown(self) -> None:
      pass

    async def health_check(self) -> HealthResult:
      return HealthResult(
        status=HealthStatus.HEALTHY,
        message="Tot bé"
      )
  ```
  """

  @property
  def metadata(self) -> ModuleMetadata:
    """
    Retorna les metadades del mòdul.

    Aquestes dades s'utilitzen per:
    - Registrar el mòdul al sistema
    - Comprovar dependències
    - Mostrar informació a l'usuari
    """
    ...

  async def initialize(self, context: Dict[str, Any]) -> bool:
    """
    Inicialitza el mòdul amb el context proporcionat.

    Args:
      context: Diccionari amb serveis i configuració:
        - config: Configuració global
        - services: Serveis compartits (logger, i18n, etc.)
        - modules: Referència al registry de mòduls

    Returns:
      True si la inicialització és correcta, False si falla
    """
    ...

  async def shutdown(self) -> None:
    """
    Atura el mòdul i allibera recursos.

    S'executa quan el servidor s'atura o el mòdul es descarrega.
    Ha de ser idempotent (es pot cridar múltiples vegades).
    """
    ...

  async def health_check(self) -> HealthResult:
    """
    Retorna l'estat de salut del mòdul.

    S'executa periòdicament pel sistema de monitoring.
    Ha de ser ràpid (< 1 segon).

    Returns:
      HealthResult amb l'estat actual
    """
    ...

@runtime_checkable
class NexeModuleWithRouter(NexeModule, Protocol):
  """
  Extensió de NexeModule per mòduls que exposen endpoints HTTP.

  Els mòduls amb router es registren automàticament a FastAPI.
  """

  def get_router(self) -> Any:
    """
    Retorna el router FastAPI del mòdul.

    Returns:
      fastapi.APIRouter amb els endpoints del mòdul
    """
    ...

  def get_router_prefix(self) -> str:
    """
    Retorna el prefix URL pel router.

    Exemple: "/security" -> endpoints a /security/*

    Returns:
      String amb el prefix (ha de començar amb /)
    """
    ...

@runtime_checkable
class NexeModuleWithSpecialists(NexeModule, Protocol):
  """
  Extensió de NexeModule per mòduls que gestionen specialists.

  Els specialists són components que poden ser enviats a altres
  mòduls o rebuts d'altres mòduls per fer checks o accions.
  """

  def get_outgoing_specialists(self) -> List[SpecialistInfo]:
    """
    Retorna la llista de specialists que aquest mòdul envia.

    Exemple: El mòdul Security pot enviar un SecuritySpecialist
    Mòduls que ofereixen capacitats de seguretat.
    """
    ...

  def get_incoming_specialist_types(self) -> List[str]:
    """
    Retorna els tipus de specialists que aquest mòdul accepta.

    Exemple: El mòdul de seguretat accepta specialists de tipus
    "security", "memory", "performance", etc.
    """
    ...

  async def register_specialist(self, specialist: Any) -> bool:
    """
    Registra un specialist entrant al mòdul.

    Args:
      specialist: Instància del specialist a registrar

    Returns:
      True si el registre és correcte
    """
    ...

def validate_module(module: Any) -> bool:
  """
  Valida que un objecte implementa el protocol NexeModule.

  Args:
    module: Objecte a validar

  Returns:
    True si implementa el protocol correctament
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
  """Comprova si el mòdul té router HTTP"""
  return isinstance(module, NexeModuleWithRouter)

def module_has_specialists(module: Any) -> bool:
  """Comprova si el mòdul gestiona specialists"""
  return isinstance(module, NexeModuleWithSpecialists)