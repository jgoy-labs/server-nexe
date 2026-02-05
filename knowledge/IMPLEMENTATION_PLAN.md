# Pla d'Implementació Complet - Sistema Unificat de Contractes NEXE 0.9

**Versió:** 1.0 EXECUTIU
**Data Inici:** 2026-02-05
**Data Fi Estimada:** 2026-02-27 (22 dies)
**Autor:** Jordi Goy

---

## Índex

1. [Visió General](#visió-general)
2. [Prerequisites](#prerequisites)
3. [Fase 1: Infraestructura Base](#fase-1-infraestructura-base-dies-1-5)
4. [Fase 2: Migració Manifests](#fase-2-migració-manifests-dies-6-8)
5. [Fase 3: Actualització ModuleManager](#fase-3-actualització-modulemanager-dies-9-12)
6. [Fase 4: Implementació Managers i Specialists](#fase-4-implementació-managers-i-specialists-dies-13-19)
7. [Fase 5: Tests i Documentació](#fase-5-tests-i-documentació-dies-20-22)
8. [Checkpoints i Validació](#checkpoints-i-validació)
9. [Rollback Strategy](#rollback-strategy)

---

## Visió General

### Objectiu

Implementar sistema unificat de contractes per NEXE que suporti:
- **Modules** (plugins: ollama, mlx, security)
- **Managers** (gestors recursivos: ModuleManager, DoctorManager, SecurityManager)
- **Specialists** (diagnòstic: demo_specialist, security_specialist)

### Arquitectura Final

```
core/contracts/
├── __init__.py
├── base.py              # BaseContract, ModuleContract, ManagerContract, SpecialistContract
├── models.py            # UnifiedManifest (Pydantic)
├── registry.py          # ContractRegistry (singleton)
├── validators.py        # Multi-layer validation
├── tests/
│   ├── test_base.py
│   ├── test_models.py
│   ├── test_registry.py
│   └── test_validators.py
└── migrations/
    ├── __init__.py
    └── manifest_migrator.py
```

### Timeline

| Fase | Dies | Deliverables |
|------|------|--------------|
| Fase 1 | 1-5 | Protocols, Models, Registry, Validators + Tests |
| Fase 2 | 6-8 | 6 manifests migrats + Migrator tool |
| Fase 3 | 9-12 | ModuleManager integrat amb ContractRegistry |
| Fase 4 | 13-19 | DoctorManager, SecurityManager, demo_specialist |
| Fase 5 | 20-22 | Tests E2E, Docs actualitzades |

---

## Prerequisites

### Entorn de Desenvolupament

```bash
# Working directory
cd /Users/jgoy/NatSytem/Nexe/server-nexe

# Activar virtual environment (si cal)
python -m venv venv
source venv/bin/activate

# Instal·lar dependencies
pip install -r requirements.txt
pip install mypy pytest pytest-cov black ruff

# Verificar versions
python --version  # >= 3.11
mypy --version
pytest --version
```

### Crear Branch de Desenvolupament

```bash
git checkout -b feature/unified-contracts
git push -u origin feature/unified-contracts
```

### Backup del Codi Actual

```bash
# Backup complet
cp -r personality/module_manager personality/module_manager.backup
cp -r plugins plugins.backup

# Crear tag de seguretat
git tag -a pre-unified-contracts -m "Before unified contracts implementation"
git push origin pre-unified-contracts
```

---

## Fase 1: Infraestructura Base (Dies 1-5)

### Dia 1: Protocols Base

#### 1.1 Crear `core/contracts/__init__.py`

```python
"""
Core Contracts System for NEXE 0.9

Unified contract system supporting:
- Modules (standard plugins)
- Managers (recursive managers)
- Specialists (diagnostic components)
"""

from .base import (
    # Enums
    ContractType,
    HealthStatus,

    # Dataclasses
    ContractMetadata,
    HealthResult,
    CheckResult,
    HealthSummary,

    # Protocols
    BaseContract,
    ModuleContract,
    ManagerContract,
    SpecialistContract,

    # Validators
    validate_contract,
    contract_is_manager,
    contract_is_specialist,
)

from .models import (
    UnifiedManifest,
    ModuleSection,
    CapabilitiesSection,
    DependenciesSection,
    APISection,
    UISection,
    CLISection,
    SpecialistSection,
    load_manifest_from_toml,
)

from .registry import (
    ContractRegistry,
    RegisteredContract,
    ContractStatus,
    get_contract_registry,
)

from .validators import (
    ContractValidator,
    ValidationResult,
    get_validator,
)

__version__ = "1.0.0"
__all__ = [
    # Base
    "ContractType",
    "HealthStatus",
    "ContractMetadata",
    "HealthResult",
    "CheckResult",
    "HealthSummary",
    "BaseContract",
    "ModuleContract",
    "ManagerContract",
    "SpecialistContract",
    "validate_contract",
    "contract_is_manager",
    "contract_is_specialist",

    # Models
    "UnifiedManifest",
    "load_manifest_from_toml",

    # Registry
    "ContractRegistry",
    "get_contract_registry",

    # Validators
    "ContractValidator",
    "ValidationResult",
    "get_validator",
]
```

**Executar:**
```bash
mkdir -p core/contracts
touch core/contracts/__init__.py
# Copiar codi anterior
```

#### 1.2 Crear `core/contracts/base.py`

**Fitxer complet:** [Veure UNIFIED_CONTRACTS_PLAN.md secció Protocols]

Contingut clau:
- `ContractType` enum (MODULE, MANAGER, SPECIALIST, CORE)
- `HealthStatus` enum (HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN)
- `ContractMetadata` dataclass
- `HealthResult` dataclass
- `CheckResult` dataclass (per specialists)
- `HealthSummary` dataclass (per specialists)
- `BaseContract` Protocol
- `ModuleContract` Protocol
- `ManagerContract` Protocol
- `SpecialistContract` Protocol

**Executar:**
```bash
# Crear fitxer
touch core/contracts/base.py

# Validar sintaxi
python -m py_compile core/contracts/base.py

# Type check
mypy core/contracts/base.py --strict
```

**Checkpoint Dia 1:**
```bash
# Validació
python -c "from core.contracts.base import BaseContract, ContractType; print('✓ Protocols OK')"
```

---

### Dia 2: Pydantic Models

#### 2.1 Crear `core/contracts/models.py`

**Contingut:**

```python
"""
Pydantic models for UnifiedManifest validation.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from pathlib import Path

class ManifestVersion(str, Enum):
    V1 = "1.0"
    V2 = "2.0"  # Futur

class ContractTypeModel(str, Enum):
    MODULE = "module"
    MANAGER = "manager"
    SPECIALIST = "specialist"
    CORE = "core"

# ============================================
# SECTIONS
# ============================================

class ModuleSection(BaseModel):
    """[module] section - OBLIGATORI"""
    name: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-z0-9_]+$')
    version: str = Field(..., pattern=r'^\d+\.\d+\.\d+$')
    type: ContractTypeModel = ContractTypeModel.MODULE
    description: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=200)
    license: str = Field(default="AGPL-3.0")

    enabled: bool = True
    auto_start: bool = False
    priority: int = Field(default=10, ge=0, le=100)

    # Manager specifics
    can_manage_types: List[ContractTypeModel] = Field(default_factory=list)
    parent_manager: Optional[str] = None

    # Specialist specifics
    specialist_type: Optional[str] = None  # "health", "security", "memory"
    target_modules: List[str] = Field(default_factory=list)

    @field_validator('name')
    @classmethod
    def name_lowercase_no_spaces(cls, v: str) -> str:
        if ' ' in v:
            raise ValueError("name cannot contain spaces")
        return v.lower()

class CapabilitiesSection(BaseModel):
    """[capabilities] section"""
    # Module capabilities
    has_api: bool = False
    has_ui: bool = False
    has_cli: bool = False
    has_specialist: bool = False
    has_tests: bool = False
    streaming: bool = False
    real_time: bool = False

    # Specialist capabilities
    provides_health_checks: bool = False
    provides_diagnostics: bool = False

    # Custom capabilities (extensible)
    custom: Dict[str, bool] = Field(default_factory=dict)

class DependenciesSection(BaseModel):
    """[dependencies] section"""
    modules: List[str] = Field(default_factory=list)
    optional_modules: List[str] = Field(default_factory=list)
    specialists: List[str] = Field(default_factory=list)
    managers: List[str] = Field(default_factory=list)
    external_services: List[str] = Field(default_factory=list)
    python_packages: List[str] = Field(default_factory=list)

class APISection(BaseModel):
    """[api] section - Obligatori si has_api=true"""
    enabled: bool = True
    prefix: str = Field(..., pattern=r'^/[a-z0-9/_-]*$')
    tags: List[str] = Field(default_factory=list)
    public_routes: List[str] = Field(default_factory=list)
    protected_routes: List[str] = Field(default_factory=list)
    admin_routes: List[str] = Field(default_factory=list)
    rate_limit: Optional[str] = None  # "10/minute"

class UISection(BaseModel):
    """[ui] section - Obligatori si has_ui=true"""
    enabled: bool = True
    path: str = "ui"
    main_file: str = "index.html"
    route: Optional[str] = None
    framework: Optional[str] = "vanilla-js"
    theme_support: bool = True
    responsive: bool = True

class CLISection(BaseModel):
    """[cli] section - Obligatori si has_cli=true"""
    enabled: bool = True
    command_name: str = Field(..., min_length=1)
    entry_point: str = Field(..., min_length=1)
    description: str = ""
    commands: List[str] = Field(default_factory=list)
    framework: str = Field(default="click")

    @field_validator('framework')
    @classmethod
    def valid_framework(cls, v: str) -> str:
        allowed = ["click", "typer", "argparse"]
        if v not in allowed:
            raise ValueError(f"framework must be one of: {allowed}")
        return v

class SpecialistSection(BaseModel):
    """[specialist] section - Obligatori si type='specialist'"""
    checks: List[str] = Field(default_factory=list)
    check_interval: int = Field(default=300, ge=60)  # Seconds
    auto_run: bool = True
    severity_threshold: str = Field(default="warning")  # info, warning, error, critical

    @field_validator('severity_threshold')
    @classmethod
    def valid_severity(cls, v: str) -> str:
        allowed = ["info", "warning", "error", "critical"]
        if v not in allowed:
            raise ValueError(f"severity_threshold must be one of: {allowed}")
        return v

class I18nSection(BaseModel):
    """[i18n] section - Opcional"""
    enabled: bool = False
    default_locale: str = "ca-ES"
    supported_locales: List[str] = Field(default_factory=lambda: ["ca-ES", "en-US"])
    translations_path: str = "languages/"

class StoragePathDeclaration(BaseModel):
    path: str
    type: str
    format: str = "json"
    retention_days: int = Field(default=30, ge=1)
    action: str = Field(default="DELETE")
    archive_to: Optional[str] = None

class StorageSection(BaseModel):
    """[storage] section - Opcional"""
    paths: List[StoragePathDeclaration] = Field(default_factory=list)
    protected_patterns: List[str] = Field(default_factory=list)

# ============================================
# UNIFIED MANIFEST (ROOT MODEL)
# ============================================

class UnifiedManifest(BaseModel):
    """
    Root model per manifest.toml unificat.

    Suporta:
    - Modules (type="module")
    - Managers (type="manager")
    - Specialists (type="specialist")
    """

    manifest_version: ManifestVersion = ManifestVersion.V1

    # Obligatori
    module: ModuleSection

    # Opcional
    capabilities: CapabilitiesSection = Field(default_factory=CapabilitiesSection)
    dependencies: DependenciesSection = Field(default_factory=DependenciesSection)

    # Condicionals
    api: Optional[APISection] = None
    ui: Optional[UISection] = None
    cli: Optional[CLISection] = None
    specialist: Optional[SpecialistSection] = None
    i18n: Optional[I18nSection] = None
    storage: Optional[StorageSection] = None

    # Metadata adicional (free-form)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_conditional_sections(self) -> 'UnifiedManifest':
        """Valida seccions condicionals segons capabilities i type"""

        # Si has_api, [api] és obligatori
        if self.capabilities.has_api and self.api is None:
            raise ValueError("[api] section required when capabilities.has_api = true")

        # Si has_ui, [ui] és obligatori
        if self.capabilities.has_ui and self.ui is None:
            raise ValueError("[ui] section required when capabilities.has_ui = true")

        # Si has_cli, [cli] és obligatori
        if self.capabilities.has_cli and self.cli is None:
            raise ValueError("[cli] section required when capabilities.has_cli = true")

        # Si type=specialist, [specialist] és obligatori
        if self.module.type == ContractTypeModel.SPECIALIST:
            if self.specialist is None:
                raise ValueError("[specialist] section required for type='specialist'")
            if not self.module.specialist_type:
                raise ValueError("module.specialist_type required for specialists")

        # Si type=manager, can_manage_types no pot estar buit
        if self.module.type == ContractTypeModel.MANAGER:
            if not self.module.can_manage_types:
                raise ValueError("managers must specify can_manage_types")

        return self

    @model_validator(mode='after')
    def validate_api_prefix_matches_name(self) -> 'UnifiedManifest':
        """Valida que api.prefix coincideix amb module.name"""
        if self.api:
            expected_prefix = f"/{self.module.name}"
            if not self.api.prefix.startswith(expected_prefix):
                raise ValueError(
                    f"api.prefix must start with /{self.module.name}, "
                    f"got: {self.api.prefix}"
                )
        return self

    def to_contract_metadata(self) -> 'ContractMetadata':
        """Converteix UnifiedManifest a ContractMetadata"""
        from .base import ContractMetadata, ContractType

        return ContractMetadata(
            contract_id=self.module.name,
            contract_type=ContractType(self.module.type.value),
            contract_version=self.manifest_version.value,
            name=self.module.name,
            version=self.module.version,
            description=self.module.description,
            author=self.module.author,
            license=self.module.license,
            capabilities=self.capabilities.model_dump(),
            dependencies=self.dependencies.modules,
            optional_dependencies=self.dependencies.optional_modules,
            can_manage_types=[
                ContractType(t.value)
                for t in self.module.can_manage_types
            ],
            parent_manager=self.module.parent_manager,
            specialist_type=self.module.specialist_type,
            target_modules=self.module.target_modules,
            tags=self.api.tags if self.api else []
        )

# ============================================
# HELPER FUNCTIONS
# ============================================

def load_manifest_from_toml(toml_path: str) -> UnifiedManifest:
    """
    Carrega i valida un manifest.toml.

    Args:
        toml_path: Path al fitxer manifest.toml

    Returns:
        UnifiedManifest validat

    Raises:
        ValidationError: Si el manifest no compleix l'schema
        FileNotFoundError: Si el fitxer no existeix
    """
    import toml
    from pathlib import Path

    path = Path(toml_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {toml_path}")

    with open(path, 'r', encoding='utf-8') as f:
        data = toml.load(f)

    return UnifiedManifest(**data)

def validate_manifest_dict(data: Dict[str, Any]) -> UnifiedManifest:
    """Valida un diccionari com a manifest"""
    return UnifiedManifest(**data)
```

**Executar:**
```bash
touch core/contracts/models.py
# Copiar codi

# Validar
python -m py_compile core/contracts/models.py
mypy core/contracts/models.py --strict
```

**Test Manual:**
```bash
python -c "
from core.contracts.models import UnifiedManifest, load_manifest_from_toml
print('✓ Models OK')
"
```

---

### Dia 3: Contract Registry

#### 3.1 Crear `core/contracts/registry.py`

**Contingut complet:** [Veure UNIFIED_CONTRACTS_PLAN.md]

Punts clau:
- Singleton pattern thread-safe
- `register(contract, managed_by)`
- `unregister(contract_id)`
- `get_hierarchy(contract_id)` - recursiu
- `list_managed_by(manager_id)`
- `initialize_contract(contract_id, context)`
- `health_check_all()`

**Executar:**
```bash
touch core/contracts/registry.py
# Copiar codi

python -m py_compile core/contracts/registry.py
mypy core/contracts/registry.py --strict
```

---

### Dia 4: Validators

#### 4.1 Crear `core/contracts/validators.py`

**Contingut:** [Veure UNIFIED_CONTRACTS.md secció Validators]

Mètodes:
- `validate_manifest_schema(manifest_path)` - Pydantic
- `validate_contract_runtime(contract)` - Protocol
- `validate_file_structure(contract_path, manifest)` - Integration
- `validate_all(contract_path, contract_instance)`

**Executar:**
```bash
touch core/contracts/validators.py
# Copiar codi

python -m py_compile core/contracts/validators.py
```

---

### Dia 5: Tests Unitaris

#### 5.1 Crear tests structure

```bash
mkdir -p core/contracts/tests
touch core/contracts/tests/__init__.py
touch core/contracts/tests/test_base.py
touch core/contracts/tests/test_models.py
touch core/contracts/tests/test_registry.py
touch core/contracts/tests/test_validators.py
```

#### 5.2 `test_base.py`

```python
"""Tests for base protocols"""
import pytest
from core.contracts.base import (
    BaseContract, ModuleContract, ManagerContract, SpecialistContract,
    ContractMetadata, ContractType, HealthResult, HealthStatus,
    CheckResult, HealthSummary,
    validate_contract, contract_is_manager, contract_is_specialist
)

class TestBaseContract:
    def test_contract_metadata_creation(self):
        """Test ContractMetadata dataclass"""
        meta = ContractMetadata(
            contract_id="test",
            contract_type=ContractType.MODULE,
            name="Test",
            version="1.0.0",
            description="Test contract"
        )

        assert meta.contract_id == "test"
        assert meta.contract_type == ContractType.MODULE
        assert meta.is_module()
        assert not meta.is_manager()

    def test_health_result_to_dict(self):
        """Test HealthResult serialization"""
        result = HealthResult(
            status=HealthStatus.HEALTHY,
            message="All OK",
            details={"checks": 5}
        )

        data = result.to_dict()
        assert data["status"] == "healthy"
        assert data["message"] == "All OK"
        assert data["details"]["checks"] == 5

class TestModuleContract:
    def test_module_implements_base_contract(self):
        """Test ModuleContract extends BaseContract"""

        class TestModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test_module",
                    contract_type=ContractType.MODULE,
                    name="Test"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY)

            def get_router(self):
                return None

            def get_router_prefix(self):
                return "/test"

        module = TestModule()

        # Runtime check
        assert isinstance(module, BaseContract)
        assert isinstance(module, ModuleContract)
        assert validate_contract(module)

        # Check methods
        assert hasattr(module, 'metadata')
        assert hasattr(module, 'get_router')

class TestManagerContract:
    @pytest.mark.asyncio
    async def test_manager_can_manage_modules(self):
        """Test manager managing modules"""

        class TestManager:
            def __init__(self):
                self._contracts = {}

            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test_manager",
                    contract_type=ContractType.MANAGER,
                    can_manage_types=[ContractType.MODULE]
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY)

            async def register_contract(self, contract):
                self._contracts[contract.metadata.contract_id] = contract
                return True

            async def unregister_contract(self, contract_id):
                return self._contracts.pop(contract_id, None) is not None

            def list_managed_contracts(self):
                return [c.metadata for c in self._contracts.values()]

            def get_managed_contract(self, contract_id):
                return self._contracts.get(contract_id)

            def list_specialists(self):
                return []

            async def run_all_specialist_checks(self):
                return {}

        manager = TestManager()

        assert isinstance(manager, ManagerContract)
        assert contract_is_manager(manager)

class TestSpecialistContract:
    def test_specialist_check_result(self):
        """Test CheckResult dataclass"""
        check = CheckResult(
            name="test_check",
            status=HealthStatus.HEALTHY,
            message="Check passed",
            severity="info"
        )

        assert check.name == "test_check"
        assert check.status == HealthStatus.HEALTHY
        assert check.severity == "info"

    @pytest.mark.asyncio
    async def test_specialist_implements_contract(self):
        """Test SpecialistContract implementation"""
        from datetime import datetime

        class TestSpecialist:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test_specialist",
                    contract_type=ContractType.SPECIALIST,
                    specialist_type="health"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY)

            def get_specialist_type(self):
                return "health"

            def run_checks(self):
                return [
                    CheckResult(
                        name="check1",
                        status=HealthStatus.HEALTHY,
                        message="OK"
                    )
                ]

            def get_health_summary(self):
                results = self.run_checks()
                return HealthSummary(
                    module_name="test",
                    specialist_type="health",
                    status=HealthStatus.HEALTHY,
                    checks=["check1"],
                    results=results,
                    timestamp=datetime.now()
                )

            async def run_check(self, check_name):
                return CheckResult(
                    name=check_name,
                    status=HealthStatus.HEALTHY,
                    message="OK"
                )

        specialist = TestSpecialist()

        assert isinstance(specialist, SpecialistContract)
        assert contract_is_specialist(specialist)

        summary = specialist.get_health_summary()
        assert summary.module_name == "test"
        assert summary.status == HealthStatus.HEALTHY
```

#### 5.3 `test_models.py`

```python
"""Tests for Pydantic models"""
import pytest
from pydantic import ValidationError
from core.contracts.models import (
    UnifiedManifest, ModuleSection, CapabilitiesSection,
    ContractTypeModel, load_manifest_from_toml
)

class TestModuleSection:
    def test_module_section_valid(self):
        """Test valid module section"""
        section = ModuleSection(
            name="test_module",
            version="1.0.0",
            type=ContractTypeModel.MODULE
        )

        assert section.name == "test_module"
        assert section.version == "1.0.0"
        assert section.enabled is True

    def test_module_name_lowercase(self):
        """Test name is converted to lowercase"""
        section = ModuleSection(
            name="TestModule",
            version="1.0.0"
        )

        assert section.name == "testmodule"

    def test_module_name_no_spaces(self):
        """Test name cannot contain spaces"""
        with pytest.raises(ValidationError):
            ModuleSection(
                name="test module",
                version="1.0.0"
            )

    def test_version_pattern(self):
        """Test version must be semantic versioning"""
        with pytest.raises(ValidationError):
            ModuleSection(
                name="test",
                version="1.0"  # Invalid
            )

class TestUnifiedManifest:
    def test_minimal_manifest(self):
        """Test minimal valid manifest"""
        manifest = UnifiedManifest(
            module=ModuleSection(
                name="test",
                version="1.0.0"
            )
        )

        assert manifest.module.name == "test"
        assert manifest.manifest_version == "1.0"

    def test_module_with_api_requires_api_section(self):
        """Test [api] required when has_api=true"""
        with pytest.raises(ValidationError, match="api.*section required"):
            UnifiedManifest(
                module=ModuleSection(
                    name="test",
                    version="1.0.0"
                ),
                capabilities=CapabilitiesSection(
                    has_api=True
                )
                # Missing [api] section!
            )

    def test_manager_requires_can_manage_types(self):
        """Test managers must specify can_manage_types"""
        with pytest.raises(ValidationError, match="can_manage_types"):
            UnifiedManifest(
                module=ModuleSection(
                    name="test_manager",
                    version="1.0.0",
                    type=ContractTypeModel.MANAGER
                    # Missing can_manage_types!
                )
            )

    def test_specialist_requires_specialist_section(self):
        """Test specialists require [specialist] section"""
        with pytest.raises(ValidationError, match="specialist.*section"):
            UnifiedManifest(
                module=ModuleSection(
                    name="test_specialist",
                    version="1.0.0",
                    type=ContractTypeModel.SPECIALIST,
                    specialist_type="health"
                )
                # Missing [specialist] section!
            )

    def test_to_contract_metadata(self):
        """Test conversion to ContractMetadata"""
        from core.contracts.models import APISection

        manifest = UnifiedManifest(
            module=ModuleSection(
                name="test",
                version="1.0.0",
                description="Test module"
            ),
            capabilities=CapabilitiesSection(
                has_api=True
            ),
            api=APISection(
                prefix="/test",
                tags=["test", "demo"]
            )
        )

        metadata = manifest.to_contract_metadata()

        assert metadata.contract_id == "test"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test module"
        assert "test" in metadata.tags
```

#### 5.4 Executar Tests

```bash
# Run all tests
pytest core/contracts/tests/ -v

# With coverage
pytest core/contracts/tests/ -v --cov=core.contracts --cov-report=html

# Coverage report
open htmlcov/index.html
```

**Target:** Coverage > 80%

---

### Checkpoint Fase 1

```bash
# Validacions finals
python -c "
from core.contracts import (
    BaseContract, ModuleContract, ManagerContract, SpecialistContract,
    UnifiedManifest, ContractRegistry, ContractValidator
)
print('✓ All imports OK')
"

# Tests
pytest core/contracts/tests/ -v --cov=core.contracts

# Type check
mypy core/contracts/ --strict

# Linting
ruff check core/contracts/

# Git commit
git add core/contracts/
git commit -m "feat: Implement unified contracts infrastructure (Phase 1)

- Add BaseContract, ModuleContract, ManagerContract, SpecialistContract protocols
- Add UnifiedManifest Pydantic model with validation
- Add ContractRegistry with hierarchical support
- Add multi-layer validators
- Add comprehensive unit tests (>80% coverage)
"
git push
```

**Go/No-Go Decision:**
- ✅ Tests pass (>80% coverage)
- ✅ Mypy strict passes
- ✅ No critical bugs
- **→ Proceed to Phase 2**

---

## Fase 2: Migració Manifests (Dies 6-8)

### Dia 6: Manifest Migrator

#### 6.1 Crear `core/contracts/migrations/__init__.py`

```python
"""Manifest migration tools"""

from .manifest_migrator import (
    ManifestMigrator,
    MigrationResult,
    migrate_manifest,
    migrate_all_plugins,
)

__all__ = [
    "ManifestMigrator",
    "MigrationResult",
    "migrate_manifest",
    "migrate_all_plugins",
]
```

#### 6.2 Crear `core/contracts/migrations/manifest_migrator.py`

```python
"""
Manifest Migrator - Migra manifests antics al nou format UnifiedManifest.
"""

import toml
import logging
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class MigrationResult:
    """Resultat d'una migració"""
    success: bool
    original_path: Path
    migrated_path: Path
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "✓ SUCCESS" if self.success else "✗ FAILED"
        output = [f"{status}: {self.original_path.name}"]

        if self.changes:
            output.append(f"  Changes ({len(self.changes)}):")
            for change in self.changes:
                output.append(f"    - {change}")

        if self.warnings:
            output.append(f"  Warnings ({len(self.warnings)}):")
            for warn in self.warnings:
                output.append(f"    ⚠ {warn}")

        if self.errors:
            output.append(f"  Errors ({len(self.errors)}):")
            for err in self.errors:
                output.append(f"    ✗ {err}")

        return "\n".join(output)

class ManifestMigrator:
    """
    Migrador de manifests antics al nou format UnifiedManifest.

    Suporta:
    - Ollama format (module.cli, module.endpoints)
    - Security format (authentication, rate_limiting)
    - MLX format (module.entry, module.router)
    - NAT7-DEV format (module.capabilities dins [module])
    """

    def detect_format(self, data: Dict[str, Any]) -> str:
        """Detecta el format del manifest"""

        if "manifest_version" in data:
            return "unified"  # Ja és nou format

        if "module" not in data:
            return "unknown"

        module = data["module"]

        # Check for old NAT7-DEV format
        if "capabilities" in module:
            return "nat7"

        # Check for Ollama format
        if "cli" in module or "endpoints" in module:
            return "ollama"

        # Check for MLX format
        if "entry" in module or "router" in module:
            return "mlx"

        # Check for Security format
        if "authentication" in data or "rate_limiting" in data:
            return "security"

        return "generic"

    def migrate_manifest(self, manifest_path: Path, backup: bool = True) -> MigrationResult:
        """
        Migra un manifest al nou format.

        Args:
            manifest_path: Path al manifest.toml antic
            backup: Si True, crea backup (.old)

        Returns:
            MigrationResult amb els canvis
        """
        changes = []
        warnings = []
        errors = []

        try:
            # Load old manifest
            with open(manifest_path, 'r', encoding='utf-8') as f:
                old_data = toml.load(f)

            # Detect format
            format_type = self.detect_format(old_data)
            logger.info(f"Detected format: {format_type} for {manifest_path.name}")

            if format_type == "unified":
                warnings.append("Already in unified format, skipping")
                return MigrationResult(
                    success=True,
                    original_path=manifest_path,
                    migrated_path=manifest_path,
                    warnings=warnings
                )

            # Migrate based on format
            if format_type == "nat7":
                new_data = self._migrate_nat7_format(old_data, changes, warnings)
            elif format_type == "ollama":
                new_data = self._migrate_ollama_format(old_data, changes, warnings)
            elif format_type == "mlx":
                new_data = self._migrate_mlx_format(old_data, changes, warnings)
            elif format_type == "security":
                new_data = self._migrate_security_format(old_data, changes, warnings)
            else:
                new_data = self._migrate_generic_format(old_data, changes, warnings)

            # Validate with Pydantic
            from core.contracts.models import UnifiedManifest
            try:
                manifest = UnifiedManifest(**new_data)
                changes.append("✓ Validated with Pydantic")
            except Exception as e:
                errors.append(f"Pydantic validation failed: {e}")
                raise

            # Write migrated manifest
            migrated_path = manifest_path.parent / f"{manifest_path.stem}.toml.new"

            with open(migrated_path, 'w', encoding='utf-8') as f:
                toml.dump(new_data, f)

            changes.append(f"Written to {migrated_path.name}")

            # Create backup if requested
            if backup:
                backup_path = manifest_path.parent / f"{manifest_path.stem}.toml.old"
                import shutil
                shutil.copy2(manifest_path, backup_path)
                changes.append(f"Backup created: {backup_path.name}")

            logger.info(f"Successfully migrated {manifest_path.name}")

            return MigrationResult(
                success=True,
                original_path=manifest_path,
                migrated_path=migrated_path,
                changes=changes,
                warnings=warnings,
                errors=errors
            )

        except Exception as e:
            errors.append(str(e))
            logger.error(f"Failed to migrate {manifest_path}: {e}")
            return MigrationResult(
                success=False,
                original_path=manifest_path,
                migrated_path=Path(),
                changes=changes,
                warnings=warnings,
                errors=errors
            )

    def _migrate_nat7_format(
        self,
        old_data: Dict[str, Any],
        changes: List[str],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Migra format NAT7-DEV"""

        new_data = {
            "manifest_version": "1.0",
            "module": {},
            "capabilities": {},
            "dependencies": {},
        }

        old_module = old_data["module"]

        # [module]
        new_data["module"] = {
            "name": old_module.get("name", ""),
            "version": old_module.get("version", "0.1.0"),
            "type": old_module.get("type", "module"),
            "description": old_module.get("description", ""),
            "author": old_module.get("author", ""),
            "enabled": old_module.get("enabled", True),
            "auto_start": old_module.get("auto_start", False),
            "priority": old_module.get("priority", 10),
        }
        changes.append("Migrated [module] section")

        # [capabilities] - Extraure de [module.capabilities]
        if "capabilities" in old_module:
            new_data["capabilities"] = old_module["capabilities"]
            changes.append("Extracted [capabilities] from [module.capabilities]")

        # [dependencies] - Extraure de [module.dependencies]
        if "dependencies" in old_module:
            new_data["dependencies"] = old_module["dependencies"]
            changes.append("Extracted [dependencies] from [module.dependencies]")

        # [api] - Extraure de [module.endpoints]
        if "endpoints" in old_module:
            old_endpoints = old_module["endpoints"]
            new_data["api"] = {
                "enabled": True,
                "prefix": old_endpoints.get("router_prefix", f"/{new_data['module']['name']}"),
                "public_routes": old_endpoints.get("public_routes", []),
                "protected_routes": old_endpoints.get("protected_routes", [])
            }

            if "ui_path" in old_endpoints:
                new_data["ui"] = {
                    "enabled": True,
                    "route": old_endpoints["ui_path"],
                    "path": "ui",
                    "main_file": "index.html"
                }
                new_data["capabilities"]["has_ui"] = True
                changes.append("Extracted [ui] from module.endpoints.ui_path")

            new_data["capabilities"]["has_api"] = True
            changes.append("Migrated [module.endpoints] to [api]")

        # [cli] - Extraure de [module.cli]
        if "cli" in old_module:
            old_cli = old_module["cli"]
            new_data["cli"] = {
                "enabled": True,
                "command_name": old_cli.get("command_name", old_cli.get("main_command", new_data["module"]["name"])),
                "entry_point": old_cli.get("entry_point", old_cli.get("executable", "")),
                "description": old_cli.get("description", ""),
                "commands": old_cli.get("commands", []),
                "framework": old_cli.get("framework", "click")
            }
            new_data["capabilities"]["has_cli"] = True
            changes.append("Migrated [module.cli] to [cli]")

        # [specialist] - Si type=specialist
        if new_data["module"]["type"] == "specialist":
            # Buscar secció [specialist] o [requirements]
            if "specialist" in old_data:
                new_data["specialist"] = old_data["specialist"]
            elif "requirements" in old_data:
                new_data["specialist"] = {
                    "checks": old_data["requirements"].get("checks", [])
                }
            changes.append("Migrated specialist section")

        # [i18n]
        if "i18n" in old_module:
            new_data["i18n"] = old_module["i18n"]
            changes.append("Copied [i18n] section")

        # [storage]
        if "storage" in old_module:
            new_data["storage"] = old_module["storage"]
            changes.append("Copied [storage] section")

        return new_data

    def _migrate_ollama_format(
        self,
        old_data: Dict[str, Any],
        changes: List[str],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Migra format Ollama (similar a NAT7)"""
        return self._migrate_nat7_format(old_data, changes, warnings)

    def _migrate_mlx_format(
        self,
        old_data: Dict[str, Any],
        changes: List[str],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Migra format MLX"""
        # Similar a NAT7 però amb [module.entry] i [module.router]
        new_data = self._migrate_nat7_format(old_data, changes, warnings)

        old_module = old_data["module"]

        # [module.router] → [api]
        if "router" in old_module:
            old_router = old_module["router"]
            if "api" not in new_data:
                new_data["api"] = {}
            new_data["api"]["prefix"] = old_router.get("prefix", f"/{new_data['module']['name']}")
            changes.append("Migrated [module.router] to [api]")

        return new_data

    def _migrate_security_format(
        self,
        old_data: Dict[str, Any],
        changes: List[str],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Migra format Security"""
        new_data = self._migrate_nat7_format(old_data, changes, warnings)

        # [authentication] → warnings (deprecated)
        if "authentication" in old_data:
            warnings.append("[authentication] section deprecated, consider merging into [api]")

        # [rate_limiting] → warnings (deprecated)
        if "rate_limiting" in old_data:
            warnings.append("[rate_limiting] section deprecated, use api.rate_limit")
            if "api" in new_data:
                new_data["api"]["rate_limit"] = "10/minute"  # Default

        return new_data

    def _migrate_generic_format(
        self,
        old_data: Dict[str, Any],
        changes: List[str],
        warnings: List[str]
    ) -> Dict[str, Any]:
        """Migra format genèric"""
        warnings.append("Using generic migration, manual review recommended")
        return self._migrate_nat7_format(old_data, changes, warnings)

    def migrate_all_plugins(
        self,
        plugins_dir: Path,
        backup: bool = True,
        dry_run: bool = False
    ) -> List[MigrationResult]:
        """
        Migra tots els manifests dins plugins/.

        Args:
            plugins_dir: Path a plugins/
            backup: Crear backups
            dry_run: Només simular, no escriure

        Returns:
            List[MigrationResult]
        """
        results = []

        for manifest_path in plugins_dir.rglob("manifest.toml"):
            # Skip backups and migrations
            if ".old" in manifest_path.name or ".new" in manifest_path.name:
                continue

            logger.info(f"Migrating {manifest_path}")

            if dry_run:
                logger.info(f"[DRY RUN] Would migrate {manifest_path}")
                continue

            result = self.migrate_manifest(manifest_path, backup=backup)
            results.append(result)

        return results

# Helper functions

def migrate_manifest(manifest_path: Path, backup: bool = True) -> MigrationResult:
    """Helper function to migrate a single manifest"""
    migrator = ManifestMigrator()
    return migrator.migrate_manifest(manifest_path, backup=backup)

def migrate_all_plugins(
    plugins_dir: Path,
    backup: bool = True,
    dry_run: bool = False
) -> List[MigrationResult]:
    """Helper function to migrate all plugins"""
    migrator = ManifestMigrator()
    return migrator.migrate_all_plugins(plugins_dir, backup=backup, dry_run=dry_run)
```

**Executar:**
```bash
touch core/contracts/migrations/__init__.py
touch core/contracts/migrations/manifest_migrator.py
# Copiar codi

python -m py_compile core/contracts/migrations/manifest_migrator.py
```

---

### Dia 7-8: Migrar Plugins

#### 7.1 Script de Migració

Crear `scripts/migrate_manifests.py`:

```python
#!/usr/bin/env python3
"""
Script per migrar tots els manifests de plugins al nou format.
"""

import sys
from pathlib import Path
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.contracts.migrations import migrate_all_plugins

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    plugins_dir = Path("plugins")

    if not plugins_dir.exists():
        logger.error(f"Plugins directory not found: {plugins_dir}")
        return 1

    logger.info(f"Migrating manifests in {plugins_dir}")

    # Dry run first
    logger.info("=== DRY RUN ===")
    results_dry = migrate_all_plugins(plugins_dir, dry_run=True)
    logger.info(f"Would migrate {len(results_dry)} manifests")

    # Ask for confirmation
    response = input("\nProceed with migration? [y/N]: ")
    if response.lower() != 'y':
        logger.info("Migration cancelled")
        return 0

    # Real migration
    logger.info("\n=== REAL MIGRATION ===")
    results = migrate_all_plugins(plugins_dir, backup=True)

    # Print results
    print("\n" + "="*60)
    print("MIGRATION RESULTS")
    print("="*60)

    for result in results:
        print("\n" + str(result))

    # Summary
    success_count = sum(1 for r in results if r.success)
    failed_count = len(results) - success_count

    print("\n" + "="*60)
    print(f"SUMMARY: {success_count} success, {failed_count} failed")
    print("="*60)

    if failed_count > 0:
        print("\n⚠ Some migrations failed. Review errors above.")
        return 1

    print("\n✓ All migrations successful!")
    print("\nNext steps:")
    print("1. Review .new files manually")
    print("2. Run: pytest core/contracts/tests/ -v")
    print("3. Replace old manifests: ./scripts/apply_migrations.sh")

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Executar:**
```bash
chmod +x scripts/migrate_manifests.py
python scripts/migrate_manifests.py
```

#### 7.2 Script per Aplicar Migracions

Crear `scripts/apply_migrations.sh`:

```bash
#!/bin/bash
# Aplica les migracions (.new → .toml)

set -e

PLUGINS_DIR="plugins"

echo "Applying manifest migrations..."

# Find all .new files
find "$PLUGINS_DIR" -name "*.toml.new" | while read new_file; do
    original_file="${new_file%.new}"

    echo "Replacing $original_file"

    # Backup already exists (.old)
    mv "$new_file" "$original_file"
done

echo "✓ Migrations applied"
echo ""
echo "Old manifests backed up as .toml.old"
echo "To rollback: ./scripts/rollback_migrations.sh"
```

**Executar:**
```bash
chmod +x scripts/apply_migrations.sh
# NO executar encara - revisar .new files primer
```

#### 7.3 Migrar Plugins Específics

**Llista de plugins a migrar:**

1. `plugins/ollama_module/manifest.toml`
2. `plugins/mlx_module/manifest.toml`
3. `plugins/llama_cpp_module/manifest.toml`
4. `plugins/security/manifest.toml`
5. `plugins/security_logger/manifest.toml`
6. `plugins/web_ui_module/manifest.toml`

**Per cada plugin:**

```bash
# 1. Migrar
python scripts/migrate_manifests.py

# 2. Revisar .new file
cat plugins/ollama_module/manifest.toml.new

# 3. Validar amb Pydantic
python -c "
from core.contracts.models import load_manifest_from_toml
manifest = load_manifest_from_toml('plugins/ollama_module/manifest.toml.new')
print(f'✓ {manifest.module.name} v{manifest.module.version} validated')
"

# 4. Si OK, repetir per tots
```

**Checkpoint Dia 8:**
```bash
# Comptar migracions
ls plugins/*/manifest.toml.new | wc -l  # Hauria de ser 6

# Validar totes
for manifest in plugins/*/manifest.toml.new; do
    echo "Validating $manifest"
    python -c "from core.contracts.models import load_manifest_from_toml; load_manifest_from_toml('$manifest')"
done

echo "✓ All manifests validated"
```

---

### Checkpoint Fase 2

```bash
# Git commit
git add core/contracts/migrations/
git add scripts/migrate_manifests.py
git add scripts/apply_migrations.sh
git add plugins/*/manifest.toml.new
git add plugins/*/manifest.toml.old

git commit -m "feat: Implement manifest migrator and migrate plugins (Phase 2)

- Add ManifestMigrator for auto-migration
- Migrate 6 plugins to UnifiedManifest format
- Create migration scripts
- All migrations validated with Pydantic
"
git push
```

**Go/No-Go Decision:**
- ✅ 6 manifests migrats
- ✅ Tots validats amb Pydantic
- ✅ Backups creats (.old)
- **→ Proceed to Phase 3**

---

## Fase 3: Actualització ModuleManager (Dies 9-12)

[CONTINUARÀ amb detalls de Fase 3, 4 i 5...]

---

**TOTAL DOCUMENT:** ~250 pàgines amb tots els detalls d'implementació.

Vols que continuï amb les Fases 3, 4 i 5 detallades?
