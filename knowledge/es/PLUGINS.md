# === METADATA RAG ===
versio: "2.0"
data: 2026-04-06
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia completa del sistema de plugins de server-nexe 0.9.0 pre-release. Cubre el Protocol NexeModule (duck typing, no herencia), formato manifest.toml, estructura de ficheros del plugin, ciclo de vida (discovery -> loading -> initialization -> integration -> shutdown), objeto context, registro de routers, plugins existentes (MLX, llama.cpp, Ollama, Security con normalizacion Unicode, Web UI con validacion de entrada), como crear un plugin nuevo paso a paso, errores comunes y buenas practicas."
tags: [plugins, extensibility, nexe-module, protocol, manifest, lifecycle, router, mlx, ollama, llama-cpp, security, web-ui, create-plugin, tutorial, duck-typing]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy"
expires: null
---

# Sistema de plugins — server-nexe 0.9.0 pre-release

server-nexe usa una arquitectura de plugins basada en descubrimiento automatico via ficheros manifest.toml. Los plugins son modulos independientes que anaden funcionalidad sin modificar el core. No hace falta registro manual — el sistema escanea, descubre y carga plugins automaticamente.

## Protocol NexeModule (la interfaz)

server-nexe usa **Python Protocols** (duck typing), NO herencia de clases. NO existe ninguna clase `BasePlugin`. Un plugin es valido si implementa los metodos correctos — no hace falta importar ni extender nada.

**Definido en:** `core/loader/protocol.py`

### Interfaz requerida (NexeModule)

Todo plugin DEBE implementar estos 4 miembros:

```python
class MyPlugin:
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="my_plugin",
            version="0.9.0",
            description="Que hace",
            author="Nombre Autor",
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

Si el plugin expone endpoints HTTP, implementar tambien:

```python
def get_router(self) -> APIRouter:
    return self._router

def get_router_prefix(self) -> str:
    return "/my-plugin"
```

### Opcional: NexeModuleWithSpecialists

Para plugins que envian/reciben componentes specialist a otros modulos:

```python
def get_outgoing_specialists(self) -> List[SpecialistInfo]: ...
def get_incoming_specialist_types(self) -> List[str]: ...
async def register_specialist(self, specialist: Any) -> bool: ...
```

### Tipos de datos

```python
class ModuleMetadata:
    name: str
    version: str
    description: str
    author: str
    module_type: str        # "local_llm_option" | "core" | "web_interface"
    quadrant: str           # "core" (por defecto)
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

## manifest.toml — Declaracion del plugin

Todo plugin DEBE tener un fichero `manifest.toml`. Es la fuente unica de verdad para el sistema de descubrimiento.

### manifest.toml minimo

```toml
[module]
name = "my_plugin"
version = "0.9.0"
type = "local_llm_option"
description = "Que hace este plugin"
location = "plugins/my_plugin/"
permanent = true

[module.metadata]
author = "Nombre Autor"
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

### Reglas clave
- Todas las secciones bajo `[module.*]` — nunca secciones de primer nivel
- `[module.entry]` es OBLIGATORIO — sin el, el descubrimiento falla
- `[module.router].prefix` debe coincidir con `[module.endpoints].router_prefix`
- La version deberia coincidir con server-nexe

## Estructura de ficheros del plugin

### Ficheros requeridos

```
plugins/my_plugin/
├── __init__.py         # Package Python (puede estar vacio)
├── manifest.toml       # Declaracion plugin (OBLIGATORIO)
├── manifest.py         # Singleton lazy + accessor router
└── module.py           # Clase principal implementando NexeModule
```

### Estructura recomendada (plugin completo)

```
plugins/my_plugin/
├── __init__.py
├── manifest.toml
├── manifest.py
├── module.py
├── api/
│   └── routes.py       # Endpoints FastAPI
├── core/               # Logica de negocio
├── cli/                # Subcomandos CLI (opcional)
├── tests/              # Tests unitarios + integracion
└── languages/          # Traducciones i18n (ca/es/en)
```

### manifest.py (patron lazy initialization)

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

## Ciclo de vida del plugin

```
DISCOVERY -> LOADING -> INITIALIZATION -> INTEGRATION -> RUNNING -> SHUTDOWN
```

### 1. Discovery
El ModuleManager escanea `plugins/`, `memory/`, `personality/` buscando ficheros `manifest.toml`. Extrae metadatos sin importar codigo Python.

### 2. Loading
Import dinamico de Python: `from plugins.my_plugin.module import MyPluginModule`. Valida el Protocol NexeModule.

### 3. Initialization
Llama a `await module.initialize(context)`. El contexto contiene config, servicios (logger, i18n, event_system), y el registro de modulos.

### 4. Integration
Si el modulo implementa `NexeModuleWithRouter`, el kernel registra el router en FastAPI via `app.include_router()`.

### 5. Shutdown
Llama a `await module.shutdown()` durante la parada del servidor. Debe ser idempotente.

## Activacion y seguridad — sistema dual

server-nexe tiene **tres mecanismos complementarios** para decidir que plugins se activan. Los tres conviven y se combinan — no son alternativas.

### 1. `server.toml` — seccion `[plugins.modules]`

Lista estatica declarativa en `personality/server.toml` (linea 172). Es la fuente primaria: indica al servidor que plugins DEBE activar al arrancar.

```toml
[plugins.modules]
enabled = ["security", "rag", "ollama_module", "mlx_module", "llama_cpp_module", "web_ui_module"]
```

Para anadir un plugin nuevo hay que incluirlo explicitamente aqui.

### 2. `NEXE_APPROVED_MODULES` — variable de entorno (allowlist de seguridad)

Validada por `get_module_allowlist()` en `core/config.py:240`. Es una capa de seguridad adicional sobre la lista de `server.toml`:

- **Modo desarrollo** (`NEXE_ENV=development` o no definido): `NEXE_APPROVED_MODULES` es **opcional**. Si no esta definida, `get_module_allowlist()` devuelve `None` y no filtra nada.
- **Modo produccion** (`NEXE_ENV=production` o `[core.environment].mode = "production"`): `NEXE_APPROVED_MODULES` es **OBLIGATORIA**. Si falta, el servidor aborta con `ValueError("SECURITY ERROR: NEXE_APPROVED_MODULES is required in production")`.

Formato: lista separada por comas, ej: `NEXE_APPROVED_MODULES="security,ollama_module,web_ui_module"`. El ModuleManager usa ese conjunto para filtrar la lista de `server.toml`.

### 3. `PathDiscovery` — descubrimiento drop-in

Definido en `personality/module_manager/path_discovery.py`. Escanea automaticamente paths conocidos buscando carpetas con `manifest.toml`:

```python
known_paths = [
    "plugins", "plugins/core", "plugins/tools",
    "storage", "storage/core", "storage/tools",
    "memory/core", "memory/tools",
    "core/core", "core/tools",
    "personality/core", "personality/tools"
]
```

- **Modo strict** (produccion): solo paths conocidos + configurados explicitamente.
- **Modo dev**: ademas, auto-descubre carpetas con `modul`/`module`/`mods` en el nombre.

### Como anadir un plugin nuevo (4 pasos)

1. Poner la carpeta en `plugins/<nombre>/` con `manifest.toml` + `manifest.py` + `module.py` + `__init__.py`.
2. Anadir el nombre a `[plugins.modules].enabled` en `personality/server.toml`.
3. (Solo produccion) Anadirlo a la variable de entorno `NEXE_APPROVED_MODULES`.
4. Reiniciar el server — `PathDiscovery` lo encuentra automaticamente, `ModuleDiscovery` lo carga.

## Arquitectura del ModuleManager

El ModuleManager vive en `personality/module_manager/` — 13 ficheros, ~3279 lineas. Es la facade central del sistema de plugins.

### Componentes principales

| Fichero | Responsabilidad |
|---------|----------------|
| `module_manager.py` | Facade central, ciclo de vida, load/unload/health (642 lineas) |
| `config_manager.py` | Carga `server.toml`, config parseada, secrets |
| `config_validator.py` | Validaciones y esquemas de configuracion |
| `module_lifecycle.py` | Inicializacion, shutdown, manejo de errores |
| `path_discovery.py` | Escanea paths (`plugins/`, `memory/modules/`, `core/tools/`...) |
| `discovery.py` | Importa manifests, detecta capabilities |
| `registry.py` | Registro de modulos cargados, cache |
| `system_lifecycle.py` | Startup/shutdown global del sistema |

### Flujo del descubrimiento

1. `PathDiscovery.discover_all_paths()` encuentra carpetas con `manifest.toml`
2. `ModuleDiscovery` importa cada `manifest.py` y valida el Protocol
3. `ModuleRegistry` registra las instancias descubiertas
4. `ModuleLoader` carga las clases dinamicamente
5. `APIIntegrator` incluye los routers en la app FastAPI via `load_plugin_routers()`

## Plugins existentes (5)

| Plugin | Tipo | Router | Caracteristicas clave |
|--------|------|--------|----------------------|
| **mlx_module** | local_llm_option | /mlx | Nativo Apple Silicon, prefix caching (trie), Metal GPU, is_model_loaded() |
| **llama_cpp_module** | local_llm_option | /llama-cpp | GGUF universal, ModelPool LRU, CPU/GPU, is_model_loaded() |
| **ollama_module** | local_llm_option | /ollama | Bridge HTTP a Ollama, auto-arranque, limpieza VRAM en shutdown, streaming, is_model_loaded() via /api/ps |
| **security** | core | /security | Auth dual-key, 6 detectores de inyeccion con normalizacion Unicode (NFKC), 47 patrones de jailbreak, rate limiting (todos los endpoints), logging de auditoria RFC5424, permanent=true |
| **web_ui_module** | web_interface | /ui | Chat web, gestor de sesiones, subida de documentos (aislamiento por sesion), memory helper (MEM_SAVE), validacion de entrada (validate_string_input en todas las rutas), sanitizacion de contexto RAG, i18n (ca/es/en), 6 ficheros de rutas |

### Patrones comunes en plugins backend LLM
- Todos implementan `is_model_loaded()` (Ollama via /api/ps, MLX/llama.cpp via pool stats)
- Todos soportan streaming via generadores async
- Todos tienen endpoints `/health` y `/info`
- Prefijo del router puesto en constructor (NO despues — bug de FastAPI corregido en marzo 2026)

## Como crear un plugin nuevo (paso a paso)

### Paso 1: Crear directorio y ficheros

```bash
mkdir -p plugins/my_plugin
touch plugins/my_plugin/__init__.py
```

### Paso 2: Escribir manifest.toml

Copiar la plantilla minima de manifest.toml de arriba. Cambiar nombre, descripcion, clase de entry y prefijo del router.

### Paso 3: Escribir module.py

Implementar el Protocol NexeModule (property metadata, initialize, shutdown, health_check). Si necesitas endpoints HTTP, implementar tambien get_router() y get_router_prefix().

**Patron critico:** Crear el router PRIMERO en initialize(), antes de cualquier setup que pueda fallar.

```python
async def initialize(self, context):
    if self._initialized:
        return True
    self._init_router()  # SIEMPRE primero
    try:
        # Tu setup aqui
        self._initialized = True
        return True
    except Exception as e:
        logger.error(f"Init failed: {e}")
        return False
```

### Paso 4: Escribir manifest.py

Copiar la plantilla de lazy initialization de arriba. Cambiar el import path y nombre de clase.

### Paso 5: Reiniciar servidor

El ModuleManager descubre nuevos plugins automaticamente al arrancar.

### Paso 6: Verificar

```bash
./nexe modules
curl http://127.0.0.1:9119/my-plugin/health
curl http://127.0.0.1:9119/my-plugin/info
```

## Errores comunes

### 1. Falta [module.entry]
Sin `[module.entry]` en manifest.toml, el scanner no puede cargar el plugin.

### 2. Prefijo de router inconsistente
`[module.endpoints].router_prefix` y `[module.router].prefix` DEBEN coincidir.

### 3. Prefijo de router puesto despues del constructor
```python
# MAL — prefijo ignorado en FastAPI
self._router = APIRouter()
self._router.prefix = "/my-plugin"  # No hace nada!

# CORRECTO — prefijo en constructor
self._router = APIRouter(prefix="/my-plugin")
```

### 4. health_check que bloquea
Nunca usar llamadas HTTP sincronas en health_check(). Usar httpx.AsyncClient async.

### 5. initialize/shutdown no idempotente
Ambos metodos pueden llamarse multiples veces. Siempre poner guard `self._initialized`.

## Buenas practicas

1. **Router primero** — Crear router antes de cualquier otro setup en initialize()
2. **Todo idempotente** — initialize() y shutdown() seguros de llamar repetidamente
3. **health_check rapido** — Menos de 1 segundo, sin llamadas a APIs externas
4. **Declarar dependencias** — En manifest.toml, el kernel las carga primero
5. **Usar servicios del context** — Acceder a i18n, logger, event system desde el context
6. **Tests junto al codigo** — Poner tests en `plugins/my_plugin/tests/`
7. **manifest.py lazy** — Nunca importar dependencias pesadas en el momento del escaneo

## Ficheros fuente clave

| Concepto | Fichero |
|----------|---------|
| Protocol NexeModule | `core/loader/protocol.py` |
| ModuleManager facade | `personality/module_manager/module_manager.py` |
| Descubrimiento de paths | `personality/module_manager/path_discovery.py` |
| Descubrimiento de modulos | `personality/module_manager/discovery.py` |
| Ciclo de vida de modulos | `personality/module_manager/module_lifecycle.py` |
| Gestor de configuracion | `personality/module_manager/config_manager.py` |
| Registro de modulos | `personality/module_manager/registry.py` |
| Allowlist de seguridad | `core/config.py:240` (`get_module_allowlist()`) |
| Registro de routers | `core/server/factory_modules.py` |
| Plugin de referencia (mas limpio) | `plugins/llama_cpp_module/` |
