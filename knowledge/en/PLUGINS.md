# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-plugins-system
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete guide to the server-nexe 1.0.1-beta plugin system. Covers NexeModule Protocol (duck typing, not inheritance), manifest.toml format, plugin file structure, lifecycle (discovery → loading → initialization → integration → shutdown), context object, router registration, existing plugins (5: MLX, llama.cpp, Ollama, Security with Unicode normalization, Web UI with input validation), how to create a new plugin step by step, common errors and best practices."
tags: [plugins, extensibility, nexe-module, protocol, manifest, lifecycle, router, mlx, ollama, llama-cpp, security, web-ui, create-plugin, tutorial, duck-typing]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Plugin System — server-nexe 1.0.1-beta

server-nexe uses a plugin architecture based on automatic discovery via manifest.toml files. Plugins are independent modules that add functionality without modifying the core. No manual registration needed — the system scans, discovers, and loads plugins automatically.

## NexeModule Protocol (the interface)

server-nexe uses **Python Protocols** (duck typing), NOT class inheritance. There is NO `BasePlugin` class. A plugin is valid if it implements the right methods — no need to import or extend anything.

**Defined in:** `core/loader/protocol.py`

### Required interface (NexeModule)

Every plugin MUST implement these 4 members:

```python
class MyPlugin:
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="my_plugin",
            version="1.0.0-beta",
            description="What it does",
            author="Author Name",
            module_type="local_llm_option",
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        return True

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> HealthResult:
        return HealthResult(status=HealthStatus.HEALTHY, message="OK")
```

### Optional: NexeModuleWithRouter

If your plugin exposes HTTP endpoints, also implement:

```python
def get_router(self) -> APIRouter:
    return self._router

def get_router_prefix(self) -> str:
    return "/my-plugin"
```

### Optional: NexeModuleWithSpecialists

For plugins that send/receive specialist components to other modules:

```python
def get_outgoing_specialists(self) -> List[SpecialistInfo]: ...
def get_incoming_specialist_types(self) -> List[str]: ...
async def register_specialist(self, specialist: Any) -> bool: ...
```

### Data types

```python
class ModuleMetadata:
    name: str
    version: str
    description: str
    author: str
    module_type: str        # "local_llm_option" | "core" | "web_interface"
    quadrant: str           # "core" (default)
    dependencies: List[str]
    tags: List[str]

class HealthResult:
    status: HealthStatus    # HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN
    message: str
    details: Dict
    checks: List[Dict]

class ModuleStatus(Enum):
    DISCOVERED | LOADING | INITIALIZED | RUNNING | DEGRADED | FAILED | STOPPED
```

## manifest.toml — Plugin Declaration

Every plugin MUST have a `manifest.toml` file. This is the single source of truth for the discovery system.

### Minimal manifest.toml

```toml
[module]
name = "my_plugin"
version = "1.0.0-beta"
type = "local_llm_option"
description = "What this plugin does"
location = "plugins/my_plugin/"
permanent = true

[module.metadata]
author = "Author Name"
status = "active"

[module.capabilities]
has_api = true
has_ui = false
has_tests = true

[module.dependencies]
modules = []

[module.entry]
module = "plugins.my_plugin.module"
class = "MyPluginModule"

[module.router]
prefix = "/my-plugin"

[module.endpoints]
router_prefix = "/my-plugin"
public_routes = ["/health", "/info"]
protected_routes = ["/process"]
```

### Key rules
- All sections under `[module.*]` — never top-level sections
- `[module.entry]` is MANDATORY — without it, discovery fails
- `[module.router].prefix` must match `[module.endpoints].router_prefix`
- Version should match server-nexe version

## Plugin File Structure

### Required files

```
plugins/my_plugin/
├── __init__.py         # Python package (can be empty)
├── manifest.toml       # Plugin declaration (MANDATORY)
├── manifest.py         # Lazy singleton + router accessor
└── module.py           # Main class implementing NexeModule
```

### Recommended structure (full plugin)

```
plugins/my_plugin/
├── __init__.py
├── manifest.toml
├── manifest.py
├── module.py
├── api/
│   └── routes.py       # FastAPI endpoints
├── core/               # Business logic
├── cli/                # CLI subcommands (optional)
├── tests/              # Unit + integration tests
└── languages/          # i18n translations (ca/es/en)
```

### manifest.py (lazy initialization pattern)

```python
from typing import Optional

_module: Optional["MyPluginModule"] = None
_router = None

def _get_module():
    global _module
    if _module is None:
        from .module import MyPluginModule
        _module = MyPluginModule()
    return _module

def get_router():
    global _router
    if _router is None:
        module = _get_module()
        _router = module.get_router()
    return _router

def get_module_instance():
    return _get_module()
```

## Plugin Lifecycle

```
DISCOVERY → LOADING → INITIALIZATION → INTEGRATION → RUNNING → SHUTDOWN
```

### 1. Discovery
The ModuleManager scans `plugins/`, `memory/`, `personality/` for `manifest.toml` files. Extracts metadata without importing Python code.

### 2. Loading
Dynamic Python import: `from plugins.my_plugin.module import MyPluginModule`. Validates NexeModule Protocol.

### 3. Initialization
Calls `await module.initialize(context)`. Context contains config, services (logger, i18n, event_system), and module registry.

### 4. Integration
If the module implements `NexeModuleWithRouter`, the kernel registers the router in FastAPI via `app.include_router()`.

### 5. Shutdown
Calls `await module.shutdown()` during server stop. Must be idempotent.

## Activation & Security — Triple System

server-nexe has **three complementary mechanisms** to decide which plugins get activated. All three coexist and combine — they are not alternatives.

### 1. `server.toml` — `[plugins.modules]` section

Static declarative list in `personality/server.toml` (line 172). This is the primary source: it tells the server which plugins MUST be activated at startup.

```toml
[plugins.modules]
enabled = ["security", "rag", "ollama_module", "mlx_module", "llama_cpp_module", "web_ui_module"]
```

> **Note: 5 real plugins, not 6.** The `enabled` list contains 6 names, but `rag` is **NOT a NexeModule plugin** — it is an internal subsystem managed by `memory/rag/` (the RAG layer of the memory system). It is listed here for historical coherence and so the module activator recognises it, but it has no `manifest.toml` and does not implement the NexeModule Protocol. The **5 real plugins** are: `mlx_module`, `llama_cpp_module`, `ollama_module`, `security`, `web_ui_module`.

To add a new plugin, it must be included explicitly here.

### 2. `NEXE_APPROVED_MODULES` — env var (security allowlist)

Validated by `get_module_allowlist()` in `core/config.py:261`. This is an additional security layer on top of the `server.toml` list:

- **Development mode** (`NEXE_ENV=development` or unset): `NEXE_APPROVED_MODULES` is **optional**. If not defined, `get_module_allowlist()` returns `None` and filters nothing.
- **Production mode** (`NEXE_ENV=production` or `[core.environment].mode = "production"`): `NEXE_APPROVED_MODULES` is **MANDATORY**. If missing, the server aborts with `ValueError("SECURITY ERROR: NEXE_APPROVED_MODULES is required in production")`.

Format: comma-separated list, e.g. `NEXE_APPROVED_MODULES="security,ollama_module,web_ui_module"`. The ModuleManager uses this set to filter the `server.toml` list.

### 3. `PathDiscovery` — drop-in discovery

Defined in `personality/module_manager/path_discovery.py`. It automatically scans known paths looking for folders containing `manifest.toml`:

```python
known_paths = [
    "plugins", "plugins/core", "plugins/tools",
    "storage", "storage/core", "storage/tools",
    "memory/core", "memory/tools",
    "core/core", "core/tools",
    "personality/core", "personality/tools"
]
```

- **Strict mode** (production): only known paths + explicitly configured ones.
- **Dev mode**: also auto-discovers folders with `modul`/`module`/`mods` in the name.

### How to add a new plugin (4 steps)

1. Place the folder at `plugins/<name>/` with `manifest.toml` + `manifest.py` + `module.py` + `__init__.py`.
2. Add the name to `[plugins.modules].enabled` in `personality/server.toml`.
3. (Production only) Add it to the `NEXE_APPROVED_MODULES` env var.
4. Restart the server — `PathDiscovery` finds it automatically, `ModuleDiscovery` loads it.

## ModuleManager Architecture

The ModuleManager lives in `personality/module_manager/` — 13 files, ~3279 lines. It is the central facade of the plugin system.

### Main components

| File | Responsibility |
|------|----------------|
| `module_manager.py` | Central facade, lifecycle, load/unload/health (642 lines) |
| `config_manager.py` | Loads `server.toml`, parsed config, secrets |
| `config_validator.py` | Configuration validation and schemas |
| `module_lifecycle.py` | Initialization, shutdown, error handling |
| `path_discovery.py` | Scans paths (`plugins/`, `memory/modules/`, `core/tools/`...) |
| `discovery.py` | Imports manifests, detects capabilities |
| `registry.py` | Registry of loaded modules, cache |
| `system_lifecycle.py` | Global system startup/shutdown |

### Discovery flow

1. `PathDiscovery.discover_all_paths()` finds folders with `manifest.toml`
2. `ModuleDiscovery` imports each `manifest.py` and validates the Protocol
3. `ModuleRegistry` registers discovered instances
4. `ModuleLoader` dynamically loads the classes
5. `APIIntegrator` includes the routers in the FastAPI app via `load_plugin_routers()`

## Existing Plugins (5)

| Plugin | Type | Router | Key features |
|--------|------|--------|-------------|
| **mlx_module** | local_llm_option | /mlx | Apple Silicon native, prefix caching (trie), Metal GPU, is_model_loaded() |
| **llama_cpp_module** | local_llm_option | /llama-cpp | GGUF universal, ModelPool LRU, CPU/GPU, is_model_loaded() |
| **ollama_module** | local_llm_option | /ollama | HTTP bridge to Ollama, auto-start, VRAM cleanup on shutdown, streaming, is_model_loaded() via /api/ps |
| **security** | core | /security | Dual-key auth, 6 injection detectors with Unicode normalization (NFKC), 47 jailbreak patterns, rate limiting (all endpoints), RFC5424 audit logging, permanent=true |
| **web_ui_module** | web_interface | /ui | Web chat UI, session manager, document upload (session-isolated), memory helper (MEM_SAVE), input validation (validate_string_input on all routes), RAG context sanitization, i18n (ca/es/en), 6 route files |

### Common patterns in LLM backend plugins
- All implement `is_model_loaded()` (Ollama via /api/ps, MLX/llama.cpp via pool stats)
- All support streaming via async generators
- All have `/health` and `/info` endpoints
- Router prefix set in constructor (NOT after — FastAPI bug fixed in March 2026)

## How to Create a New Plugin (Step by Step)

### Step 1: Create directory and files

```bash
mkdir -p plugins/my_plugin
touch plugins/my_plugin/__init__.py
```

### Step 2: Write manifest.toml

Copy the minimal manifest.toml template above. Change name, description, entry class, and router prefix.

### Step 3: Write module.py

Implement NexeModule Protocol (metadata property, initialize, shutdown, health_check). If you need HTTP endpoints, also implement get_router() and get_router_prefix().

**Critical pattern:** Create the router FIRST in initialize(), before any setup that might fail.

```python
async def initialize(self, context):
    if self._initialized:
        return True
    self._init_router()  # ALWAYS first
    try:
        # Your setup here
        self._initialized = True
        return True
    except Exception as e:
        logger.error(f"Init failed: {e}")
        return False
```

### Step 4: Write manifest.py

Copy the lazy initialization template above. Change the import path and class name.

### Step 5: Restart server

The ModuleManager discovers new plugins automatically on startup.

### Step 6: Verify

```bash
./nexe modules
curl http://127.0.0.1:9119/my-plugin/health
curl http://127.0.0.1:9119/my-plugin/info
```

## Common Errors

### 1. Missing [module.entry]
Without `[module.entry]` in manifest.toml, the scanner cannot load the plugin.

### 2. Router prefix mismatch
`[module.endpoints].router_prefix` and `[module.router].prefix` MUST match.

### 3. Router prefix set after constructor
```python
# WRONG — prefix ignored in FastAPI
self._router = APIRouter()
self._router.prefix = "/my-plugin"  # Does nothing!

# CORRECT — prefix in constructor
self._router = APIRouter(prefix="/my-plugin")
```

### 4. Blocking health_check
Never use synchronous HTTP calls in health_check(). Use async httpx.AsyncClient.

### 5. Non-idempotent initialize/shutdown
Both methods may be called multiple times. Always check `self._initialized` guard.

## Best Practices

1. **Router first** — Create router before any other setup in initialize()
2. **Idempotent everything** — initialize() and shutdown() safe to call repeatedly
3. **Fast health_check** — Under 1 second, no external API calls
4. **Declare dependencies** — In manifest.toml, the kernel loads them first
5. **Use context services** — Access i18n, logger, event system from context
6. **Tests alongside code** — Put tests in `plugins/my_plugin/tests/`
7. **Lazy manifest.py** — Never import heavy dependencies at module scan time

## Key Source Files

| Concept | File |
|---------|------|
| NexeModule Protocol | `core/loader/protocol.py` |
| ModuleManager facade | `personality/module_manager/module_manager.py` |
| Path Discovery | `personality/module_manager/path_discovery.py` |
| Module Discovery | `personality/module_manager/discovery.py` |
| Module Lifecycle | `personality/module_manager/module_lifecycle.py` |
| Config Manager | `personality/module_manager/config_manager.py` |
| Module Registry | `personality/module_manager/registry.py` |
| Security Allowlist | `core/config.py:261` (`get_module_allowlist()`) |
| Router Registration | `core/server/factory_modules.py` |
| Reference plugin (cleanest) | `plugins/llama_cpp_module/` |
