# Sistema de Contractes de Plugins - NEXE 0.9

**Versió:** 1.0
**Data:** 2026-02-05
**Estat:** ✅ Implementat i Validat

---

## Resum Executiu

NEXE 0.9 implementa un **sistema unificat de contractes** per gestionar plugins de forma consistent, type-safe i escalable.

### Estat Actual

✅ **Sistema base implementat**: BaseContract + ModuleContract protocols
✅ **5 plugins migrats**: ollama, mlx, security, llama_cpp, web_ui
✅ **Validació completa**: Schema (Pydantic) + Runtime (Protocol) + Tests
✅ **Integració ModuleManager**: ContractBridge automàtic
✅ **Backward compatibility**: Manifests antics backupats com `.old`

### Mètriques

- **Tests**: 122 tests (116 unitaris + 6 integració) - 100% passing
- **Coverage**: 95% a core/contracts/
- **Plugins validats**: 5/5 (100%)
- **Overhead**: <1ms per plugin

---

## Arquitectura

### Components

```
core/contracts/
├── base.py              # BaseContract, ModuleContract
├── models.py            # UnifiedManifest (Pydantic)
├── registry.py          # ContractRegistry (singleton)
├── validators.py        # Multi-layer validation
└── migrations/
    └── manifest_migrator.py  # Auto-migració

personality/module_manager/
└── contract_bridge.py   # ModuleManager ↔ ContractRegistry
```

### Flux de Càrrega

```
ModuleManager.load_module()
    ↓
ModuleLoader carrega instància
    ↓
ContractBridge.register_module()
    ↓
ModuleContractAdapter
    ↓
ContractRegistry.register()
    ↓
✓ Plugin registrat i validat
```

---

## UnifiedManifest Schema

### Estructura TOML

```toml
manifest_version = "1.0"

[module]
name = "plugin_name"          # snake_case, lowercase
version = "1.0.0"             # semantic versioning
type = "module"               # "module" o "core"
description = "..."
author = "..."
license = "AGPL-3.0"
enabled = true
auto_start = false
priority = 10                 # 0-100

[capabilities]
has_api = true                # Plugin amb API?
has_ui = false                # Plugin amb UI?
has_cli = false               # Plugin amb CLI?
has_tests = false
streaming = false
real_time = false

[dependencies]
modules = []
optional_modules = []
external_services = []
python_packages = []

# Si has_api = true (obligatori)
[api]
prefix = "/plugin"
tags = []
public_routes = ["/health"]
protected_routes = ["/admin"]
admin_routes = []
rate_limit = "10/minute"      # opcional

# Si has_ui = true (obligatori)
[ui]
path = "ui"
main_file = "index.html"
route = "/plugin/ui"
framework = "vanilla-js"
theme_support = true
responsive = true

# Si has_cli = true (obligatori)
[cli]
command_name = "plugin"
entry_point = "path.to.cli"
description = "..."
commands = ["cmd1", "cmd2"]
framework = "click"

# Opcional
[i18n]
enabled = false
default_locale = "ca-ES"
supported_locales = ["ca-ES", "en-US"]

[storage]
[[storage.paths]]
path = "storage/data"
type = "data"
format = "json"
retention_days = 30

[metadata]
custom_field = "value"        # Custom data preservat
```

---

## Protocols

### BaseContract

```python
@runtime_checkable
class BaseContract(Protocol):
    @property
    def metadata(self) -> ContractMetadata: ...

    async def initialize(self, context: Dict[str, Any]) -> bool: ...
    async def shutdown(self) -> None: ...
    async def health_check(self) -> HealthResult: ...
```

### ModuleContract

```python
@runtime_checkable
class ModuleContract(BaseContract, Protocol):
    def get_router(self) -> Optional[Any]: ...
    def get_router_prefix(self) -> str: ...
```

---

## Plugins Migrats

| Plugin | Versió | API | UI | CLI | Validat |
|--------|--------|-----|----|----|---------|
| ollama_module | 0.5.0 | ✅ | ✅ | ✅ | ✅ |
| mlx_module | 0.8.0 | ✅ | ❌ | ❌ | ✅ |
| security | 0.2.0 | ✅ | ✅ | ❌ | ✅ |
| llama_cpp_module | 0.8.0 | ✅ | ❌ | ❌ | ✅ |
| web_ui_module | 0.8.0 | ✅ | ✅ | ❌ | ✅ |

**Backups**: Tots els manifests antics → `.old`

---

## Crear Plugin Nou

### 1. Estructura

```
plugins/nou_plugin/
├── manifest.toml
├── __init__.py
├── module.py
├── ui/              # si has_ui
├── tests/           # si has_tests
└── languages/       # si i18n
```

### 2. Manifest Mínim

```toml
manifest_version = "1.0"

[module]
name = "nou_plugin"
version = "1.0.0"
type = "module"
description = "..."

[capabilities]
has_api = false
```

### 3. Classe Plugin

```python
class NouPlugin:
    def __init__(self):
        self.name = "nou_plugin"

    async def initialize(self, context):
        return True

    async def shutdown(self):
        pass

    async def health_check(self):
        from core.contracts import HealthResult, HealthStatus
        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="OK"
        )
```

### 4. Validar

```bash
python3 -c "
from core.contracts import load_manifest_from_toml
manifest = load_manifest_from_toml('plugins/nou_plugin/manifest.toml')
print(f'✓ Valid: {manifest.module.name} v{manifest.module.version}')
"
```

---

## Tests

### Executar

```bash
# Tests unitaris
pytest core/contracts/tests/ -v

# Tests integració
pytest tests/integration/test_contract_integration.py -v

# Amb coverage
pytest --cov=core.contracts --cov-report=html
```

### Resultats Actuals

✅ 122 tests (116 unitaris + 6 integració)
✅ 95% coverage
✅ mypy --strict passa
✅ Tots els tests passing

---

## Migració

### Auto-migració

```bash
# Tots els plugins
python3 scripts/migrate_manifests.py

# Plugin específic
python3 scripts/migrate_manifests.py --plugin nom_plugin

# Dry-run
python3 scripts/migrate_manifests.py --dry-run
```

### Aplicar Migracions

```bash
# Amb confirmació
./scripts/apply_migrations.sh

# Rollback
for f in plugins/*/manifest.toml.old; do
    mv "$f" "${f%.old}"
done
```

---

## ContractRegistry

### API

```python
from core.contracts import get_contract_registry

registry = get_contract_registry()

# Llistar tots
contracts = registry.list_all()

# Obtenir un
registered = registry.get("ollama_module")

# Health check tots
results = await registry.health_check_all()

# Resum
summary = registry.get_summary()
print(f"Total: {summary['total']}")
```

---

## Validació Multi-Capa

### 1. Schema (Pydantic)

```python
manifest = load_manifest_from_toml("manifest.toml")
```

### 2. Runtime (Protocol)

```python
if validate_contract(instance):
    print("✓ Implementa BaseContract")
```

### 3. Integration

```python
validator = get_validator()
result = validator.validate_all(Path("plugins/plugin"))
```

### 4. Static (mypy)

```bash
mypy plugins/plugin/ --strict
```

---

## Limitacions Actuals

❌ No hi ha jerarquia de managers
❌ No hi ha specialists
❌ No hi ha dependency resolution automàtic
❌ No hi ha hot reload

---

## Documentació Completa

- `UNIFIED_CONTRACTS.md` - Arquitectura tècnica
- `UNIFIED_CONTRACTS_PLAN.md` - Pla amb specialists
- `IMPLEMENTATION_PLAN.md` - Detalls implementació
- `core/contracts/` - Codi font amb docstrings

---

## Changelog

### v1.0 (2026-02-05)

✅ Sistema base de contractes
✅ UnifiedManifest amb Pydantic
✅ ContractRegistry singleton
✅ ContractBridge per ModuleManager
✅ 5 plugins migrats
✅ 122 tests (116 unitaris + 6 integració)
✅ 95% test coverage
✅ Backward compatibility completa

---

**Sistema validat i en producció - NEXE 0.9**
