# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia completa del sistema de plugins de server-nexe 0.9.0 pre-release. Cobreix Protocol NexeModule (duck typing, no herencia), format manifest.toml, estructura de fitxers del plugin, cicle de vida (discovery -> loading -> initialization -> integration -> shutdown), objecte context, registre de routers, plugins existents (MLX, llama.cpp, Ollama, Security amb normalitzacio Unicode, Web UI amb validacio d'input), com crear un plugin nou pas a pas, errors comuns i bones practiques."
tags: [plugins, extensibility, nexe-module, protocol, manifest, lifecycle, router, mlx, ollama, llama-cpp, security, web-ui, create-plugin, tutorial, duck-typing]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema de plugins — server-nexe 0.9.0 pre-release

server-nexe utilitza una arquitectura de plugins basada en descobriment automatic via fitxers manifest.toml. Els plugins son moduls que afegeixen funcionalitat sense modificar el core. No cal registre manual — el sistema escaneja, descobreix i carrega plugins automaticament.

## Protocol NexeModule (la interficie)

server-nexe utilitza **Python Protocols** (duck typing), NO herencia de classes. NO existeix cap classe `BasePlugin`. Un plugin es valid si implementa els metodes correctes — no cal importar ni estendre res.

**Definit a:** `core/loader/protocol.py`

### Interficie requerida (NexeModule)

Tot plugin HA d'implementar aquests 4 membres:

```python
class MyPlugin:
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="my_plugin",
            version="0.9.0",
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

### Opcional: NexeModuleWithRouter

Si el plugin exposa endpoints HTTP, tambe implementar:

```python
def get_router(self) -> APIRouter:
    return self._router

def get_router_prefix(self) -> str:
    return "/my-plugin"
```

### Opcional: NexeModuleWithSpecialists

Per a plugins que envien/reben components specialist a altres moduls:

```python
def get_outgoing_specialists(self) -> List[SpecialistInfo]: ...
def get_incoming_specialist_types(self) -> List[str]: ...
async def register_specialist(self, specialist: Any) -> bool: ...
```

### Tipus de dades

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

## manifest.toml — Declaracio del plugin

Tot plugin HA de tenir un fitxer `manifest.toml`. Es la font unica de veritat per al sistema de descobriment.

### manifest.toml minim

```toml
[module]
name = "my_plugin"
version = "0.9.0"
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

### Regles clau
- Totes les seccions sota `[module.*]` — mai seccions de primer nivell
- `[module.entry]` es OBLIGATORI — sense ell, el descobriment falla
- `[module.router].prefix` ha de coincidir amb `[module.endpoints].router_prefix`
- La versio hauria de coincidir amb la de server-nexe

## Estructura de fitxers del plugin

### Fitxers requerits

```
plugins/my_plugin/
├── __init__.py         # Paquet Python (pot estar buit)
├── manifest.toml       # Declaracio del plugin (OBLIGATORI)
├── manifest.py         # Singleton lazy + accessor del router
└── module.py           # Classe principal que implementa NexeModule
```

### Estructura recomanada (plugin complet)

```
plugins/my_plugin/
├── __init__.py
├── manifest.toml
├── manifest.py
├── module.py
├── api/
│   └── routes.py       # Endpoints FastAPI
├── core/               # Logica de negoci
├── cli/                # Subcomandes CLI (opcional)
├── tests/              # Tests unitaris + integracio
└── languages/          # Traduccions i18n (ca/es/en)
```

### manifest.py (patro d'inicialitzacio lazy)

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

## Cicle de vida del plugin

```
DISCOVERY -> LOADING -> INITIALIZATION -> INTEGRATION -> RUNNING -> SHUTDOWN
```

### 1. Discovery
El ModuleManager escaneja `plugins/`, `memory/`, `personality/` per a fitxers `manifest.toml`. Extreu metadades sense importar codi Python.

### 2. Loading
Import dinamic de Python: `from plugins.my_plugin.module import MyPluginModule`. Valida el Protocol NexeModule.

### 3. Initialization
Crida `await module.initialize(context)`. El context conte config, serveis (logger, i18n, event_system) i registre de moduls.

### 4. Integration
Si el modul implementa `NexeModuleWithRouter`, el kernel registra el router a FastAPI via `app.include_router()`.

### 5. Shutdown
Crida `await module.shutdown()` durant l'aturada del servidor. Ha de ser idempotent.

## Plugins existents (5)

| Plugin | Tipus | Router | Caracteristiques clau |
|--------|------|--------|-------------|
| **mlx_module** | local_llm_option | /mlx | Natiu Apple Silicon, prefix caching (trie), GPU Metal, is_model_loaded() |
| **llama_cpp_module** | local_llm_option | /llama-cpp | GGUF universal, ModelPool LRU, CPU/GPU, is_model_loaded() |
| **ollama_module** | local_llm_option | /ollama | Bridge HTTP a Ollama, auto-arrencada, neteja VRAM a l'aturada, streaming, is_model_loaded() via /api/ps |
| **security** | core | /security | Auth dual-key, 6 detectors d'injeccio amb normalitzacio Unicode (NFKC), 47 patrons de jailbreak, rate limiting (tots els endpoints), logging d'auditoria RFC5424, permanent=true |
| **web_ui_module** | web_interface | /ui | Chat web UI, gestor de sessions, pujada de documents (aillament per sessio), memory helper (MEM_SAVE), validacio d'input (validate_string_input a totes les rutes), sanititzacio de context RAG, i18n (ca/es/en), 6 fitxers de rutes |

### Patrons comuns als plugins backend LLM
- Tots implementen `is_model_loaded()` (Ollama via /api/ps, MLX/llama.cpp via pool stats)
- Tots suporten streaming via generadors async
- Tots tenen endpoints `/health` i `/info`
- Prefix del router establert al constructor (NO despres — bug de FastAPI corregit al marc 2026)

## Com crear un plugin nou (pas a pas)

### Pas 1: Crear directori i fitxers

```bash
mkdir -p plugins/my_plugin
touch plugins/my_plugin/__init__.py
```

### Pas 2: Escriure manifest.toml

Copia la plantilla minima del manifest.toml de dalt. Canvia nom, descripcio, classe d'entrada i prefix del router.

### Pas 3: Escriure module.py

Implementa el Protocol NexeModule (propietat metadata, initialize, shutdown, health_check). Si necessites endpoints HTTP, tambe implementa get_router() i get_router_prefix().

**Patro critic:** Crea el router PRIMER a initialize(), abans de qualsevol setup que pugui fallar.

```python
async def initialize(self, context):
    if self._initialized:
        return True
    self._init_router()  # SEMPRE primer
    try:
        # El teu setup aqui
        self._initialized = True
        return True
    except Exception as e:
        logger.error(f"Init failed: {e}")
        return False
```

### Pas 4: Escriure manifest.py

Copia la plantilla d'inicialitzacio lazy de dalt. Canvia la ruta d'import i el nom de classe.

### Pas 5: Reiniciar servidor

El ModuleManager descobreix nous plugins automaticament a l'arrencada.

### Pas 6: Verificar

```bash
./nexe modules
curl http://127.0.0.1:9119/my-plugin/health
curl http://127.0.0.1:9119/my-plugin/info
```

## Errors comuns

### 1. Falta [module.entry]
Sense `[module.entry]` al manifest.toml, l'scanner no pot carregar el plugin.

### 2. Prefix del router inconsistent
`[module.endpoints].router_prefix` i `[module.router].prefix` HAN de coincidir.

### 3. Prefix del router establert despres del constructor
```python
# MALAMENT — prefix ignorat a FastAPI
self._router = APIRouter()
self._router.prefix = "/my-plugin"  # No fa res!

# CORRECTE — prefix al constructor
self._router = APIRouter(prefix="/my-plugin")
```

### 4. health_check que bloqueja
Mai utilitzar crides HTTP sincrones a health_check(). Utilitza httpx.AsyncClient async.

### 5. initialize/shutdown no idempotent
Ambdos metodes es poden cridar multiples vegades. Posa sempre guard `self._initialized`.

## Bones practiques

1. **Router primer** — Crea el router abans de qualsevol altre setup a initialize()
2. **Tot idempotent** — initialize() i shutdown() segurs de cridar repetidament
3. **health_check rapid** — Menys d'1 segon, sense crides a APIs externes
4. **Declarar dependencies** — Al manifest.toml, el kernel les carrega primer
5. **Utilitzar serveis del context** — Accedeix a i18n, logger, event system des del context
6. **Tests al costat del codi** — Posa els tests a `plugins/my_plugin/tests/`
7. **manifest.py lazy** — Mai importar dependencies pesades en el moment de l'escaneig

## Fitxers font clau

| Concepte | Fitxer |
|---------|------|
| Protocol NexeModule | `core/loader/protocol.py` |
| Descobriment de moduls | `personality/module_manager/discovery.py` |
| Cicle de vida de moduls | `personality/module_manager/module_lifecycle.py` |
| Registre de routers | `core/server/factory_modules.py` |
| Plugin de referencia (el mes net) | `plugins/llama_cpp_module/` |
