# Pla Unificat de Contractes NEXE 0.9 - FINAL

**Versió:** 1.0
**Data:** 2026-02-05
**Autor:** Jordi Goy
**Basat en:** Anàlisi de NAT7-DEV (demo_module, module_manager, specialists)

---

## Resum Executiu

Sistema unificat de contractes per NEXE que suporta **3 tipus de components**:

1. **Modules** (plugins estàndard: ollama, mlx, security, etc.)
2. **Managers** (gestors recursivos: ModuleManager, SecurityManager, DoctorManager)
3. **Specialists** (components de diagnòstic/check: demo_specialist, security_specialist)

**Clau:** Els **Managers reben contractes dels Specialists** per gestionar health checks i diagnòstics.

---

## Arquitectura dels 3 Tipus de Contractes

### Jerarquia Completa

```
BaseContract (protocol base per TOTS)
│
├─ ModuleContract (plugins estàndard)
│  │  Exemples: ollama_module, mlx_module, security, web_ui
│  │
│  └─ Capabilities: has_api, has_ui, has_cli
│
├─ ManagerContract (gestors recursivos) ← GESTIONA ALTRES CONTRACTES
│  │  Exemples: ModuleManager, SecurityManager, DoctorManager
│  │
│  │  + register_contract(contract: BaseContract)  ← Rep Modules i Specialists!
│  │  + list_managed_contracts()
│  │  + get_managed_contract(id)
│  │
│  └─ Pot gestionar: Modules, Specialists, altres Managers
│
└─ SpecialistContract (diagnòstic i health checks)
   │  Exemples: demo_specialist, security_specialist, memory_specialist
   │
   │  + run_checks() -> List[CheckResult]
   │  + get_health_summary() -> HealthSummary
   │  + get_specialist_type() -> str (e.g., "security", "memory")
   │
   └─ Gestionats per: Managers (DoctorManager, SecurityManager)
```

### Exemple Jerarquia Real

```
ModuleManager (ManagerContract)
├── ollama_module (ModuleContract)
├── SecurityManager (ManagerContract) ← Manager dins Manager!
│   ├── security (ModuleContract)
│   ├── security_specialist (SpecialistContract) ← Specialist!
│   └── sanitizer_specialist (SpecialistContract)
└── DoctorManager (ManagerContract)
    ├── demo_specialist (SpecialistContract)
    ├── memory_specialist (SpecialistContract)
    └── system_testing_specialist (SpecialistContract)
```

---

## Manifest Unificat (UnifiedManifest)

### Schema Base per TOTS els Tipus

```toml
manifest_version = "1.0"

[module]
name = "component_name"
version = "1.0.0"
type = "module"  # o "manager", "specialist"
description = "Descripció"
author = "Autor"
enabled = true
auto_start = false
priority = 10

# Només per MANAGERS:
can_manage_types = ["module", "specialist"]
parent_manager = "module_manager"

# Només per SPECIALISTS:
specialist_type = "security"  # o "memory", "health", etc.
target_modules = ["security", "security_logger"]

[capabilities]
has_api = true
has_ui = false
has_cli = true
has_tests = true

# Per specialists:
provides_health_checks = true
provides_diagnostics = true

[dependencies]
modules = []
specialists = []  # Specialists que necessita
managers = []     # Managers que el gestionen
external_services = []

[api]  # Si has_api = true
enabled = true
prefix = "/component"
public_routes = []
protected_routes = []

[ui]   # Si has_ui = true
[cli]  # Si has_cli = true
[specialist]  # Si type = "specialist"
```

---

## Comparativa: NAT7-DEV vs NEXE Unificat

### 1. Module Manifest

**NAT7-DEV (demo_module/manifest.toml):**
```toml
[module]
name = "demo_module"
type = "demo"
permanent = false
example = true

[module.capabilities]  # ← Dins de [module]
has_api = true

[module.endpoints]  # ← Format antic
router_prefix = "/demo"
ui_path = "/demo/ui"

[module.integration]  # ← Específic NAT
workflow_engine = true
doctor = true

[module.cli]  # ← Dins de [module]
main_command = "demo-module"
```

**NEXE Unificat:**
```toml
manifest_version = "1.0"

[module]
name = "demo_module"
type = "module"  # Més genèric
enabled = true
auto_start = false

[capabilities]  # ← Secció independent
has_api = true
has_ui = true
has_cli = true
has_workflow = true  # Integration inclosa aquí

[api]  # ← Secció independent
enabled = true
prefix = "/demo"

[ui]   # ← Secció independent
enabled = true
path = "ui"

[cli]  # ← Secció independent
enabled = true
command_name = "demo-module"
```

**Canvis necessaris:**
- ✅ Extreure `[module.capabilities]` → `[capabilities]`
- ✅ Extreure `[module.endpoints]` → `[api]`
- ✅ Extreure `[module.cli]` → `[cli]`
- ✅ Eliminar `[module.integration]` → moure a `[capabilities]`
- ✅ Afegir `manifest_version = "1.0"`

---

### 2. Manager Manifest

**NAT7-DEV (module_manager/manifest.toml):**
```toml
[module]
id_ressonant = "{{NAT_MODULE_MANAGER}}"
name = "module_manager"
type = "core"
permanent = true
category = "ressonancia.core"

[module.status]
enabled = true
priority = 1
auto_start = true

[module.endpoints]
router_prefix = "/modules"
```

**NEXE Unificat:**
```toml
manifest_version = "1.0"

[module]
name = "module_manager"
version = "7.0.0"
type = "manager"  # ← Important!
enabled = true
auto_start = true
priority = 1

# Manager specifics
can_manage_types = ["module", "manager", "specialist"]
parent_manager = null  # Top-level manager

[capabilities]
has_api = true
has_ui = true

[api]
enabled = true
prefix = "/modules"
```

**Canvis necessaris:**
- ✅ Afegir `type = "manager"`
- ✅ Afegir `can_manage_types = ["module", "manager", "specialist"]`
- ✅ Normalitzar estructura com altres manifests

---

### 3. Specialist Manifest

**NAT7-DEV (demo_module/specialists/manifest.toml):**
```toml
[specialist]
name = "demo_module"
version = "1.0.0"
priority = 90
description = "..."

[requirements]
modules = []
checks = ["module_structure", "basic_functionality"]

[metadata]
author = "NAT Team"
example = true
```

**NEXE Unificat:**
```toml
manifest_version = "1.0"

[module]
name = "demo_specialist"
version = "1.0.0"
type = "specialist"  # ← Tipus específic
description = "Health specialist per demo_module"
enabled = true
priority = 90

# Specialist specifics
specialist_type = "health"
target_modules = ["demo_module"]

[capabilities]
provides_health_checks = true
provides_diagnostics = true
has_tests = true

[dependencies]
modules = ["demo_module"]  # Depèn del mòdul que diagnostica
managers = ["doctor_manager"]  # Gestionat per DoctorManager

[specialist]
checks = ["module_structure", "basic_functionality"]
check_interval = 300  # Segons
auto_run = true
```

**Canvis necessaris:**
- ✅ Canviar `[specialist]` → `[module]` amb `type = "specialist"`
- ✅ Afegir `specialist_type` per identificar tipus de specialist
- ✅ Afegir `target_modules` per indicar què diagnostica
- ✅ Afegir `[dependencies.managers]` per indicar qui el gestiona
- ✅ Moure checks a secció `[specialist]` específica

---

## Protocols Python (BaseContract)

### BaseContract (tots ho implementen)

```python
from typing import Protocol, runtime_checkable, Dict, Any
from dataclasses import dataclass
from enum import Enum

class ContractType(Enum):
    MODULE = "module"
    MANAGER = "manager"
    SPECIALIST = "specialist"
    CORE = "core"

@dataclass
class ContractMetadata:
    contract_id: str
    contract_type: ContractType
    name: str
    version: str
    description: str

    # Capabilities
    capabilities: Dict[str, bool]

    # Dependencies
    dependencies: List[str]
    optional_dependencies: List[str]

    # Manager specifics
    can_manage_types: List[ContractType] = field(default_factory=list)
    parent_manager: Optional[str] = None

    # Specialist specifics
    specialist_type: Optional[str] = None
    target_modules: List[str] = field(default_factory=list)

@runtime_checkable
class BaseContract(Protocol):
    """Protocol base per TOTS els contractes"""

    @property
    def metadata(self) -> ContractMetadata: ...

    async def initialize(self, context: Dict[str, Any]) -> bool: ...
    async def shutdown(self) -> None: ...
    async def health_check(self) -> HealthResult: ...
```

### ModuleContract (plugins)

```python
@runtime_checkable
class ModuleContract(BaseContract, Protocol):
    """Contract per plugins estàndard"""

    def get_router(self) -> Optional[Any]: ...
    def get_router_prefix(self) -> str: ...
```

### ManagerContract (gestors recursivos)

```python
@runtime_checkable
class ManagerContract(BaseContract, Protocol):
    """Contract per managers que gestionen altres contractes"""

    async def register_contract(self, contract: BaseContract) -> bool:
        """
        Registra qualsevol BaseContract:
        - Modules (ModuleContract)
        - Specialists (SpecialistContract) ← IMPORTANT!
        - Altres Managers (ManagerContract)
        """
        ...

    async def unregister_contract(self, contract_id: str) -> bool: ...

    def list_managed_contracts(self) -> List[ContractMetadata]: ...
    def get_managed_contract(self, contract_id: str) -> Optional[BaseContract]: ...

    # Específic per gestionar specialists
    def list_specialists(self) -> List[ContractMetadata]:
        """Llista només els specialists gestionats"""
        ...

    async def run_all_specialist_checks(self) -> Dict[str, HealthResult]:
        """Executa health checks de tots els specialists"""
        ...
```

### SpecialistContract (diagnòstic)

```python
@dataclass
class CheckResult:
    """Resultat d'un check individual"""
    name: str
    status: HealthStatus  # HEALTHY, DEGRADED, UNHEALTHY
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"  # info, warning, error, critical

@dataclass
class HealthSummary:
    """Resum de salut del specialist"""
    module_name: str
    specialist_type: str
    status: HealthStatus
    checks: List[str]  # Noms dels checks executats
    results: List[CheckResult]
    timestamp: datetime

@runtime_checkable
class SpecialistContract(BaseContract, Protocol):
    """
    Contract per specialists de diagnòstic.

    Basat en BaseSpecialist de NAT7-DEV.
    """

    def get_specialist_type(self) -> str:
        """Tipus de specialist: 'health', 'security', 'memory', etc."""
        ...

    def run_checks(self) -> List[CheckResult]:
        """
        Executa tots els checks específics.

        Returns:
            List de CheckResult amb status individual
        """
        ...

    def get_health_summary(self) -> HealthSummary:
        """
        Resum agregat de salut.

        Returns:
            HealthSummary amb status global i detalls
        """
        ...

    # Opcional: check específic
    async def run_check(self, check_name: str) -> CheckResult:
        """Executa un check específic per nom"""
        ...
```

---

## Exemple Complet: DemoModule amb Specialist

### 1. demo_module (ModuleContract)

**Manifest (`plugins/demo_module/manifest.toml`):**

```toml
manifest_version = "1.0"

[module]
name = "demo_module"
version = "1.0.0"
type = "module"
description = "Mòdul de demostració NAT"
author = "NAT Team"
enabled = true
auto_start = false
priority = 50

[capabilities]
has_api = true
has_ui = true
has_cli = true
has_specialist = true  # ← Té specialist associat
has_tests = true

[dependencies]
modules = []
specialists = ["demo_specialist"]  # ← Depèn del seu specialist

[api]
enabled = true
prefix = "/demo"
public_routes = ["/", "/health", "/greet"]

[ui]
enabled = true
path = "ui"
main_file = "index.html"

[cli]
enabled = true
command_name = "demo"
entry_point = "plugins.demo_module.cli"
```

**Implementació (`plugins/demo_module/module.py`):**

```python
from core.contracts.base import ModuleContract, ContractMetadata, ContractType

class DemoModule:
    def __init__(self, i18n=None):
        self._metadata = ContractMetadata(
            contract_id="demo_module",
            contract_type=ContractType.MODULE,
            name="Demo Module",
            version="1.0.0",
            description="Mòdul de demostració",
            capabilities={
                "has_api": True,
                "has_ui": True,
                "has_cli": True,
                "has_specialist": True
            },
            dependencies=["demo_specialist"]
        )
        self._router = self._init_router()

    @property
    def metadata(self) -> ContractMetadata:
        return self._metadata

    async def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> HealthResult:
        # Pot consultar el seu specialist!
        registry = context.get('registry')
        specialist = registry.get_instance("demo_specialist")

        if specialist:
            summary = specialist.get_health_summary()
            return HealthResult(
                status=summary.status,
                message=f"Module health via specialist",
                details={"specialist_checks": len(summary.results)}
            )

        return HealthResult(status=HealthStatus.HEALTHY)

    def get_router(self):
        return self._router

    def get_router_prefix(self) -> str:
        return "/demo"
```

### 2. demo_specialist (SpecialistContract)

**Manifest (`plugins/demo_module/specialists/manifest.toml`):**

```toml
manifest_version = "1.0"

[module]
name = "demo_specialist"
version = "1.0.0"
type = "specialist"
description = "Health specialist per demo_module"
author = "NAT Team"
enabled = true
priority = 90

# Specialist specifics
specialist_type = "health"
target_modules = ["demo_module"]

[capabilities]
provides_health_checks = true
provides_diagnostics = true
has_tests = true

[dependencies]
modules = ["demo_module"]
managers = ["doctor_manager"]  # Gestionat per Doctor

[specialist]
checks = [
    "module_structure",
    "basic_functionality",
    "api_endpoints",
    "ui_assets"
]
check_interval = 300
auto_run = true
severity_threshold = "warning"
```

**Implementació (`plugins/demo_module/specialists/demo_specialist.py`):**

```python
from core.contracts.base import SpecialistContract, ContractMetadata, ContractType
from core.contracts.base import CheckResult, HealthSummary, HealthStatus
from datetime import datetime

class DemoSpecialist:
    def __init__(self, i18n=None):
        self._metadata = ContractMetadata(
            contract_id="demo_specialist",
            contract_type=ContractType.SPECIALIST,
            name="Demo Specialist",
            version="1.0.0",
            specialist_type="health",
            target_modules=["demo_module"],
            capabilities={
                "provides_health_checks": True,
                "provides_diagnostics": True
            }
        )

    @property
    def metadata(self) -> ContractMetadata:
        return self._metadata

    async def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> HealthResult:
        # El specialist mateix està healthy si pot executar checks
        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="Specialist operational"
        )

    # SpecialistContract methods

    def get_specialist_type(self) -> str:
        return "health"

    def run_checks(self) -> List[CheckResult]:
        """Executa tots els health checks del demo_module"""
        checks = []

        # Check 1: Module structure
        checks.append(self._check_module_structure())

        # Check 2: Basic functionality
        checks.append(self._check_basic_functionality())

        # Check 3: API endpoints
        checks.append(self._check_api_endpoints())

        # Check 4: UI assets
        checks.append(self._check_ui_assets())

        return checks

    def get_health_summary(self) -> HealthSummary:
        """Resum agregat de tots els checks"""
        results = self.run_checks()

        # Determinar status global
        status = HealthStatus.HEALTHY
        for result in results:
            if result.status == HealthStatus.UNHEALTHY:
                status = HealthStatus.UNHEALTHY
                break
            elif result.status == HealthStatus.DEGRADED:
                status = HealthStatus.DEGRADED

        return HealthSummary(
            module_name="demo_module",
            specialist_type="health",
            status=status,
            checks=[r.name for r in results],
            results=results,
            timestamp=datetime.now()
        )

    async def run_check(self, check_name: str) -> CheckResult:
        """Executa un check específic"""
        check_map = {
            "module_structure": self._check_module_structure,
            "basic_functionality": self._check_basic_functionality,
            "api_endpoints": self._check_api_endpoints,
            "ui_assets": self._check_ui_assets
        }

        if check_name in check_map:
            return check_map[check_name]()

        return CheckResult(
            name=check_name,
            status=HealthStatus.UNKNOWN,
            message=f"Unknown check: {check_name}"
        )

    # Private check methods

    def _check_module_structure(self) -> CheckResult:
        """Valida estructura del mòdul"""
        try:
            module_path = Path("plugins/demo_module")
            required_files = ["manifest.toml", "module.py", "__init__.py"]

            missing = [f for f in required_files if not (module_path / f).exists()]

            if missing:
                return CheckResult(
                    name="module_structure",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Missing files: {missing}",
                    severity="error"
                )

            return CheckResult(
                name="module_structure",
                status=HealthStatus.HEALTHY,
                message="Module structure OK"
            )
        except Exception as e:
            return CheckResult(
                name="module_structure",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                severity="critical"
            )

    def _check_basic_functionality(self) -> CheckResult:
        """Valida funcionalitat bàsica"""
        try:
            # Importar i instanciar
            from plugins.demo_module.module import DemoModule
            module = DemoModule()

            # Verificar mètodes existeixen
            if not hasattr(module, 'greet'):
                return CheckResult(
                    name="basic_functionality",
                    status=HealthStatus.DEGRADED,
                    message="Missing greet() method",
                    severity="warning"
                )

            # Testar mètode
            result = module.greet("test")
            if not result:
                return CheckResult(
                    name="basic_functionality",
                    status=HealthStatus.DEGRADED,
                    message="greet() returned empty",
                    severity="warning"
                )

            return CheckResult(
                name="basic_functionality",
                status=HealthStatus.HEALTHY,
                message="Basic functionality OK"
            )
        except Exception as e:
            return CheckResult(
                name="basic_functionality",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                severity="error"
            )

    def _check_api_endpoints(self) -> CheckResult:
        """Valida endpoints API"""
        # ... implementació similar ...
        pass

    def _check_ui_assets(self) -> CheckResult:
        """Valida assets UI"""
        # ... implementació similar ...
        pass
```

### 3. DoctorManager (ManagerContract que gestiona specialists)

**Manifest (`plugins/doctor_manager/manifest.toml`):**

```toml
manifest_version = "1.0"

[module]
name = "doctor_manager"
version = "1.0.0"
type = "manager"
description = "Sistema de diagnòstic i health checks"
enabled = true
auto_start = true
priority = 5

# Manager specifics
can_manage_types = ["specialist"]  # ← Gestiona NOMÉS specialists!
parent_manager = "module_manager"

[capabilities]
has_api = true
has_ui = true
has_tests = true

[dependencies]
modules = []

[api]
enabled = true
prefix = "/doctor"
tags = ["doctor", "diagnostics", "health"]
public_routes = ["/health"]
protected_routes = ["/checks", "/specialists", "/run-check"]
```

**Implementació (`plugins/doctor_manager/module.py`):**

```python
from core.contracts.base import ManagerContract, SpecialistContract
from typing import Dict, List

class DoctorManager:
    """
    Manager que gestiona SPECIALISTS.

    Responsabilitats:
    - Descobrir i registrar specialists
    - Executar health checks periòdics
    - Agregar resultats de diagnòstic
    - Proporcionar API per consultar salut del sistema
    """

    def __init__(self):
        self._specialists: Dict[str, SpecialistContract] = {}
        self._metadata = ContractMetadata(
            contract_id="doctor_manager",
            contract_type=ContractType.MANAGER,
            can_manage_types=[ContractType.SPECIALIST],
            parent_manager="module_manager"
        )

    @property
    def metadata(self) -> ContractMetadata:
        return self._metadata

    async def initialize(self, context: Dict[str, Any]) -> bool:
        self._context = context
        return True

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> HealthResult:
        # Health check del manager mateix + aggregat dels specialists
        specialist_results = await self.run_all_specialist_checks()

        all_healthy = all(
            r.status == HealthStatus.HEALTHY
            for r in specialist_results.values()
        )

        return HealthResult(
            status=HealthStatus.HEALTHY if all_healthy else HealthStatus.DEGRADED,
            message=f"Managing {len(self._specialists)} specialists",
            details={"specialist_statuses": {
                sid: r.status.value
                for sid, r in specialist_results.items()
            }}
        )

    # ManagerContract methods

    async def register_contract(self, contract: BaseContract) -> bool:
        """Registra un specialist"""
        meta = contract.metadata

        # Només acceptem specialists
        if meta.contract_type != ContractType.SPECIALIST:
            return False

        # Validar que implementa SpecialistContract
        if not isinstance(contract, SpecialistContract):
            return False

        self._specialists[meta.contract_id] = contract
        return True

    async def unregister_contract(self, contract_id: str) -> bool:
        if contract_id in self._specialists:
            del self._specialists[contract_id]
            return True
        return False

    def list_managed_contracts(self) -> List[ContractMetadata]:
        return [s.metadata for s in self._specialists.values()]

    def get_managed_contract(self, contract_id: str) -> Optional[BaseContract]:
        return self._specialists.get(contract_id)

    # Specialist-specific methods

    def list_specialists(self) -> List[ContractMetadata]:
        """Llista tots els specialists"""
        return self.list_managed_contracts()

    async def run_all_specialist_checks(self) -> Dict[str, HealthResult]:
        """Executa health checks de TOTS els specialists"""
        results = {}

        for sid, specialist in self._specialists.items():
            try:
                summary = specialist.get_health_summary()
                results[sid] = HealthResult(
                    status=summary.status,
                    message=f"{len(summary.checks)} checks executed",
                    details={
                        "checks": summary.checks,
                        "results": [
                            {
                                "name": r.name,
                                "status": r.status.value,
                                "message": r.message
                            }
                            for r in summary.results
                        ]
                    }
                )
            except Exception as e:
                results[sid] = HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {e}"
                )

        return results

    async def run_specialist_check(
        self,
        specialist_id: str,
        check_name: Optional[str] = None
    ) -> HealthResult:
        """Executa check específic d'un specialist"""
        specialist = self._specialists.get(specialist_id)

        if not specialist:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message=f"Specialist not found: {specialist_id}"
            )

        if check_name:
            # Check específic
            result = await specialist.run_check(check_name)
            return HealthResult(
                status=result.status,
                message=result.message,
                details=result.details
            )
        else:
            # Tots els checks
            summary = specialist.get_health_summary()
            return HealthResult(
                status=summary.status,
                message=f"{len(summary.checks)} checks",
                details={"results": summary.results}
            )
```

---

## Migració de Components NAT7-DEV a NEXE

### Plugins/Mòduls a Migrar

| Component | Tipus | Prioritat | Canvis Necessaris |
|-----------|-------|-----------|-------------------|
| **demo_module** | Module | Alta (exemple) | Normalitzar manifest, adaptar a ModuleContract |
| **security** | Module | Alta | Ja existeix a NEXE, unificar format |
| **security_logger** | Module | Alta | Ja existeix a NEXE, unificar format |
| **observability** | Module | Mitjana | Nou, adaptar manifest |
| **prompt_manager** | Manager | Mitjana | Nou, implementar ManagerContract |
| **system_testing** | Manager | Baixa | Nou, pot esperar |
| **workflow_engine** | Manager | Baixa | Complex, pot esperar |

### Specialists a Migrar

| Specialist | Tipus | Target Module | Gestionat per |
|------------|-------|---------------|---------------|
| **demo_specialist** | health | demo_module | DoctorManager |
| **security_specialist** | security | security | SecurityManager |
| **memory_specialist** | health | memory | DoctorManager |
| **embeddings_specialist** | health | embeddings | DoctorManager |
| **rag_specialist** | health | rag | DoctorManager |

### Managers a Crear

| Manager | Gestiona | Prioritat |
|---------|----------|-----------|
| **ModuleManager** | Modules, Managers, Specialists | Crítica (ja existeix) |
| **DoctorManager** | Specialists (health checks) | Alta |
| **SecurityManager** | security modules + specialists | Alta |
| **I18nManager** | translation modules | Mitjana |
| **UIManager** | UI components | Baixa |

---

## Pla d'Implementació Actualitzat

### Fase 1: Infraestructura (3-5 dies)

✅ Igual que abans, afegint **SpecialistContract**:

```python
# core/contracts/base.py
+ class SpecialistContract(BaseContract, Protocol)
+ class CheckResult (dataclass)
+ class HealthSummary (dataclass)
```

### Fase 2: Migració Manifests (2-3 dies)

Migrar **6 plugins** (igual) + **afegir specialists**:

1. Migrar manifests de plugins (ollama, mlx, security, etc.)
2. **Nou:** Crear manifests per specialists:
   - `plugins/demo_module/specialists/manifest.toml`
   - `plugins/security/specialists/manifest.toml`

### Fase 3: Actualitzar ModuleManager (3-4 dies)

Actualitzar per gestionar **3 tipus**:

```python
async def register_contract(self, contract: BaseContract) -> bool:
    """Registra Module, Manager o Specialist"""

    if isinstance(contract, ModuleContract):
        # Registrar com a module
    elif isinstance(contract, ManagerContract):
        # Registrar com a manager
    elif isinstance(contract, SpecialistContract):
        # Registrar com a specialist
```

### Fase 4: Implementar Managers + Specialists (5-7 dies)

**Nou:** Afegir specialists:

1. **DoctorManager** + demo_specialist
2. **SecurityManager** + security_specialist
3. Testar jerarquia: ModuleManager → DoctorManager → demo_specialist

### Fase 5: Tests i Docs (2-3 dies)

Afegir tests per specialists:

```python
def test_specialist_contract_compliance():
    specialist = DemoSpecialist()
    assert isinstance(specialist, SpecialistContract)

def test_manager_can_register_specialist():
    doctor = DoctorManager()
    specialist = DemoSpecialist()

    success = await doctor.register_contract(specialist)
    assert success

    specialists = doctor.list_specialists()
    assert len(specialists) == 1
```

---

## Resum Final

### Contractes Unificats per NEXE

✅ **3 tipus de contractes:**
1. **ModuleContract** - Plugins estàndard (ollama, security, etc.)
2. **ManagerContract** - Gestors recursivos (ModuleManager, DoctorManager)
3. **SpecialistContract** - Diagnòstic i health checks (demo_specialist, etc.)

✅ **Jerarquia recursiva:**
```
ModuleManager
└── DoctorManager (Manager)
    ├── demo_specialist (Specialist)
    └── memory_specialist (Specialist)
```

✅ **Manifest unificat:**
- Format comú per tots 3 tipus
- Seccions condicionals segons `type`
- Validació Pydantic completa

✅ **Protocols type-safe:**
- BaseContract → tots ho implementen
- ModuleContract → afegeix get_router()
- ManagerContract → afegeix register_contract() per gestionar altres
- SpecialistContract → afegeix run_checks() i get_health_summary()

✅ **Migració de NAT7-DEV:**
- demo_module → ModuleContract
- demo_specialist → SpecialistContract
- DoctorManager → ManagerContract que gestiona specialists

**Timeline:** 15-22 dies (afegint specialists)

---

**Document:** UNIFIED_CONTRACTS_PLAN.md
**Versió:** 1.0 FINAL
**Data:** 2026-02-05
**Basat en:** Anàlisi real de NAT7-DEV
