# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia completa del sistema de plugins de server-nexe 0.8.2. Cobreix Protocol NexeModule (duck typing, no herència), format manifest.toml, estructura de fitxers, cicle de vida (discovery → loading → initialization → integration → shutdown), objecte context, registre de routers, plugins existents (MLX, llama.cpp, Ollama, Security, Web UI), com crear un plugin nou pas a pas, errors comuns i bones pràctiques."
tags: [plugins, extensibilitat, nexe-module, protocol, manifest, cicle-vida, router, mlx, ollama, llama-cpp, security, web-ui, crear-plugin, tutorial, duck-typing]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema de Plugins — server-nexe 0.8.2

server-nexe usa una arquitectura de plugins basada en descobriment automàtic via fitxers manifest.toml. Els plugins són mòduls independents que afegeixen funcionalitat sense modificar el core. No cal registre manual — el sistema escaneja, descobreix i carrega plugins automàticament.

## Protocol NexeModule (la interfície)

server-nexe usa **Python Protocols** (duck typing), NO herència de classes. NO existeix cap classe `BasePlugin`. Un plugin és vàlid si implementa els mètodes correctes — no cal importar ni estendre res.

**Definit a:** `core/loader/protocol.py`

### Interfície requerida (NexeModule)

Tot plugin HA d'implementar aquests 4 membres:

```python
class ElMeuPlugin:
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="el_meu_plugin",
            version="0.8.2",
            description="Què fa",
            author="Nom Autor",
            module_type="local_llm_option",  # o "core", "web_interface"
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        # Setup del plugin. Retorna True si OK, False si falla.
        return True

    async def shutdown(self) -> None:
        # Cleanup. Ha de ser idempotent (segur cridar múltiples vegades).
        pass

    async def health_check(self) -> HealthResult:
        # Retorna estat de salut. Ha de ser ràpid (< 1 segon).
        return HealthResult(status=HealthStatus.HEALTHY, message="OK")
```

### Opcional: NexeModuleWithRouter

Si el plugin exposa endpoints HTTP, implementar també:

```python
def get_router(self) -> APIRouter:
    return self._router

def get_router_prefix(self) -> str:
    return "/el-meu-plugin"
```

El kernel ho detecta via `isinstance(module, NexeModuleWithRouter)` i registra el router a FastAPI automàticament.

### Opcional: NexeModuleWithSpecialists

Per plugins que envien/reben components specialist a altres mòduls:

```python
def get_outgoing_specialists(self) -> List[SpecialistInfo]: ...
def get_incoming_specialist_types(self) -> List[str]: ...
async def register_specialist(self, specialist: Any) -> bool: ...
```

### Tipus de dades

```python
class ModuleMetadata:
    name: str               # Identificador del plugin
    version: str            # Versió (coincidir amb server-nexe)
    description: str        # Descripció llegible
    author: str             # Nom autor
    module_type: str        # "local_llm_option" | "core" | "web_interface"
    quadrant: str           # "core" (per defecte)
    dependencies: List[str] # Altres mòduls requerits
    tags: List[str]         # Tags de cerca

class HealthResult:
    status: HealthStatus    # HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN
    message: str            # Estat llegible
    details: Dict           # Info extra
    checks: List[Dict]      # Sub-checks

class ModuleStatus(Enum):
    DISCOVERED | LOADING | INITIALIZED | RUNNING | DEGRADED | FAILED | STOPPED
```

## manifest.toml — Declaració del Plugin

Tot plugin HA de tenir un fitxer `manifest.toml`. És la font única de veritat pel sistema de descobriment.

### manifest.toml mínim

```toml
[module]
name = "el_meu_plugin"
version = "0.8.2"
type = "local_llm_option"
description = "Què fa aquest plugin"
location = "plugins/el_meu_plugin/"
permanent = true

[module.metadata]
author = "Nom Autor"
status = "active"

[module.capabilities]
has_api = true
has_ui = false
has_tests = true

[module.dependencies]
modules = []

[module.entry]
module = "plugins.el_meu_plugin.module"
class = "ElMeuPluginModule"

[module.router]
prefix = "/el-meu-plugin"

[module.endpoints]
router_prefix = "/el-meu-plugin"
public_routes = ["/health", "/info"]
protected_routes = ["/process"]
```

### Regles clau
- Totes les seccions sota `[module.*]` — mai seccions de primer nivell
- `[module.entry]` és OBLIGATORI — sense ell, el descobriment falla
- `[module.router].prefix` ha de coincidir amb `[module.endpoints].router_prefix`
- La versió hauria de coincidir amb server-nexe (0.8.2)

## Estructura de Fitxers del Plugin

### Fitxers requerits

```
plugins/el_meu_plugin/
├── __init__.py         # Package Python (pot estar buit)
├── manifest.toml       # Declaració plugin (OBLIGATORI)
├── manifest.py         # Singleton lazy + accessor router
└── module.py           # Classe principal implementant NexeModule
```

### Estructura recomanada (plugin complet)

```
plugins/el_meu_plugin/
├── __init__.py
├── manifest.toml
├── manifest.py
├── module.py
├── api/
│   └── routes.py       # Endpoints FastAPI
├── core/               # Lògica de negoci
├── cli/                # Subcomandes CLI (opcional)
├── tests/              # Tests unitaris + integració
└── languages/          # Traduccions i18n (ca/es/en)
```

### manifest.py (patró lazy initialization)

```python
from typing import Optional

_module: Optional["ElMeuPluginModule"] = None
_router = None

def _get_module():
    global _module
    if _module is None:
        from .module import ElMeuPluginModule
        _module = ElMeuPluginModule()
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

## Cicle de Vida del Plugin

```
DISCOVERY → LOADING → INITIALIZATION → INTEGRATION → RUNNING → SHUTDOWN
```

### 1. Discovery
El ModuleManager escaneja `plugins/`, `memory/`, `personality/` cercant fitxers `manifest.toml`. Extreu metadades sense importar codi Python. Detecta cicles de dependències.

### 2. Loading
Import dinàmic de Python: `from plugins.el_meu_plugin.module import ElMeuPluginModule`. Valida Protocol NexeModule via `validate_module()`.

### 3. Initialization
Crida `await module.initialize(context)`. El context conté:

```python
context = {
    "config": {...},            # Config global de server.toml
    "services": {               # Serveis compartits
        "logger": logging.Logger,
        "i18n": I18nManager,
        "event_system": EventSystem,
    },
    "modules": ModuleRegistry,  # Accés a altres mòduls carregats
}
```

### 4. Integration
Si el mòdul implementa `NexeModuleWithRouter`, el kernel crida `get_router()` i `get_router_prefix()`, i registra el router a FastAPI.

### 5. Shutdown
Crida `await module.shutdown()` durant l'aturada del servidor. Ha de ser idempotent.

## Plugins Existents (5)

| Plugin | Tipus | Router | Característiques clau |
|--------|------|--------|----------------------|
| **mlx_module** | local_llm_option | /mlx | Natiu Apple Silicon, prefix caching (trie), Metal GPU, is_model_loaded() |
| **llama_cpp_module** | local_llm_option | /llama-cpp | GGUF universal, ModelPool LRU, CPU/GPU, is_model_loaded() |
| **ollama_module** | local_llm_option | /ollama | Bridge HTTP a Ollama, auto-start (open -g macOS), VRAM cleanup, streaming, is_model_loaded() via /api/ps |
| **security** | core | /security | Auth dual-key, 6 detectors d'injecció, 69 patrons jailbreak, rate limiting, logging auditoria RFC5424, permanent=true |
| **web_ui_module** | web_interface | /ui | Chat web, gestor sessions, pujada documents (aïllament sessió), memory helper (detecció intencions, MEM_SAVE), i18n (ca/es/en), 6 fitxers de routes |

### Patrons comuns als plugins backend LLM
- Tots implementen `is_model_loaded()` (Ollama via /api/ps, MLX/llama.cpp via pool stats)
- Tots suporten streaming via generadors async
- Tots tenen endpoints `/health` i `/info`
- Prefix del router posat al constructor (NO després — bug FastAPI arreglat març 2026)

## Com Crear un Plugin Nou (Pas a Pas)

### Pas 1: Crear directori i fitxers
```bash
mkdir -p plugins/el_meu_plugin
touch plugins/el_meu_plugin/__init__.py
```

### Pas 2: Escriure manifest.toml
Copiar la plantilla mínima de dalt. Canviar nom, descripció, classe entry i prefix router.

### Pas 3: Escriure module.py
Implementar Protocol NexeModule (property metadata, initialize, shutdown, health_check). Si necessites endpoints HTTP, implementar també get_router() i get_router_prefix().

**Patró crític:** Crear el router PRIMER a initialize(), abans de qualsevol setup que pugui fallar.

```python
async def initialize(self, context):
    if self._initialized:
        return True
    self._init_router()  # SEMPRE primer
    try:
        # El teu setup aquí
        self._initialized = True
        return True
    except Exception as e:
        logger.error(f"Init failed: {e}")
        return False
```

### Pas 4: Escriure manifest.py
Copiar la plantilla lazy initialization de dalt. Canviar l'import path i nom de classe.

### Pas 5: Reiniciar servidor
El ModuleManager descobreix nous plugins automàticament a l'arrencada.

### Pas 6: Verificar
```bash
./nexe modules
curl http://127.0.0.1:9119/el-meu-plugin/health
curl http://127.0.0.1:9119/el-meu-plugin/info
```

## Errors Comuns

### 1. Falta [module.entry]
Sense `[module.entry]` al manifest.toml, l'scanner no pot carregar el plugin. S'omet silenciosament.

### 2. Prefix router inconsistent
`[module.endpoints].router_prefix` i `[module.router].prefix` HAN de coincidir.

### 3. Prefix router posat després del constructor
```python
# MALAMENT — prefix ignorat a FastAPI
self._router = APIRouter()
self._router.prefix = "/el-meu-plugin"  # No fa res!

# CORRECTE — prefix al constructor
self._router = APIRouter(prefix="/el-meu-plugin")
```

### 4. Health_check que bloqueja
Mai usar crides HTTP síncrones a health_check(). Usar httpx.AsyncClient async o consultar estat intern cached.

### 5. Initialize/shutdown no idempotent
Ambdós mètodes es poden cridar múltiples vegades. Posar guard `self._initialized` al principi.

## Bones Pràctiques

1. **Router primer** — Crear router abans de qualsevol altre setup a initialize()
2. **Tot idempotent** — initialize() i shutdown() segurs de cridar repetidament
3. **Health_check ràpid** — Menys d'1 segon, sense crides a APIs externes
4. **Declarar dependències** — Al manifest.toml `[module.dependencies].modules`
5. **Usar serveis del context** — i18n, logger, event system del context, no crear-ne de propis
6. **Tests al costat del codi** — A `plugins/el_meu_plugin/tests/`
7. **Manifest.py lazy** — Mai importar dependències pesades a l'escanneig

## Fitxers Font Clau

| Concepte | Fitxer |
|----------|--------|
| Protocol NexeModule | `core/loader/protocol.py` |
| ModuleMetadata, HealthResult | `core/loader/protocol.py` |
| Descobriment de mòduls | `personality/module_manager/discovery.py` |
| Cicle de vida de mòduls | `personality/module_manager/module_lifecycle.py` |
| Registre de routers | `core/server/factory_modules.py` |
| Plugin referència (més net) | `plugins/llama_cpp_module/` |
