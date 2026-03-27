# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guía completa del sistema de plugins de server-nexe 0.8.2. Cubre Protocol NexeModule (duck typing, no herencia), formato manifest.toml, estructura de ficheros, ciclo de vida (discovery → loading → initialization → integration → shutdown), objeto context, registro de routers, plugins existentes (MLX, llama.cpp, Ollama, Security, Web UI), cómo crear un plugin nuevo paso a paso, errores comunes y buenas prácticas."
tags: [plugins, extensibilidad, nexe-module, protocol, manifest, ciclo-vida, router, mlx, ollama, llama-cpp, security, web-ui, crear-plugin, tutorial, duck-typing]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema de Plugins — server-nexe 0.8.2

server-nexe usa una arquitectura de plugins basada en descubrimiento automático vía ficheros manifest.toml. Los plugins son módulos independientes que añaden funcionalidad sin modificar el core. No hace falta registro manual — el sistema escanea, descubre y carga plugins automáticamente.

## Protocol NexeModule (la interfaz)

server-nexe usa **Python Protocols** (duck typing), NO herencia de clases. NO existe ninguna clase `BasePlugin`. Un plugin es válido si implementa los métodos correctos — no hace falta importar ni extender nada.

**Definido en:** `core/loader/protocol.py`

### Interfaz requerida (NexeModule)

Todo plugin DEBE implementar estos 4 miembros:

```python
class MiPlugin:
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="mi_plugin",
            version="0.8.2",
            description="Qué hace",
            author="Nombre Autor",
            module_type="local_llm_option",  # o "core", "web_interface"
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        # Setup del plugin. Retorna True si OK, False si falla.
        return True

    async def shutdown(self) -> None:
        # Cleanup. Debe ser idempotente (seguro llamar múltiples veces).
        pass

    async def health_check(self) -> HealthResult:
        # Retorna estado de salud. Debe ser rápido (< 1 segundo).
        return HealthResult(status=HealthStatus.HEALTHY, message="OK")
```

### Opcional: NexeModuleWithRouter

Si el plugin expone endpoints HTTP, implementar también:

```python
def get_router(self) -> APIRouter:
    return self._router

def get_router_prefix(self) -> str:
    return "/mi-plugin"
```

El kernel lo detecta vía `isinstance(module, NexeModuleWithRouter)` y registra el router en FastAPI automáticamente.

### Opcional: NexeModuleWithSpecialists

Para plugins que envían/reciben componentes specialist a otros módulos:

```python
def get_outgoing_specialists(self) -> List[SpecialistInfo]: ...
def get_incoming_specialist_types(self) -> List[str]: ...
async def register_specialist(self, specialist: Any) -> bool: ...
```

### Tipos de datos

```python
class ModuleMetadata:
    name: str               # Identificador del plugin
    version: str            # Versión (coincidir con server-nexe)
    description: str        # Descripción legible
    author: str             # Nombre autor
    module_type: str        # "local_llm_option" | "core" | "web_interface"
    quadrant: str           # "core" (por defecto)
    dependencies: List[str] # Otros módulos requeridos
    tags: List[str]         # Tags de búsqueda

class HealthResult:
    status: HealthStatus    # HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN
    message: str            # Estado legible
    details: Dict           # Info extra
    checks: List[Dict]      # Sub-checks

class ModuleStatus(Enum):
    DISCOVERED | LOADING | INITIALIZED | RUNNING | DEGRADED | FAILED | STOPPED
```

## manifest.toml — Declaración del Plugin

Todo plugin DEBE tener un fichero `manifest.toml`. Es la fuente única de verdad para el sistema de descubrimiento.

### manifest.toml mínimo

```toml
[module]
name = "mi_plugin"
version = "0.8.2"
type = "local_llm_option"
description = "Qué hace este plugin"
location = "plugins/mi_plugin/"
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
module = "plugins.mi_plugin.module"
class = "MiPluginModule"

[module.router]
prefix = "/mi-plugin"

[module.endpoints]
router_prefix = "/mi-plugin"
public_routes = ["/health", "/info"]
protected_routes = ["/process"]
```

### Reglas clave
- Todas las secciones bajo `[module.*]` — nunca secciones de primer nivel
- `[module.entry]` es OBLIGATORIO — sin él, el descubrimiento falla
- `[module.router].prefix` debe coincidir con `[module.endpoints].router_prefix`
- La versión debería coincidir con server-nexe (0.8.2)

## Estructura de Ficheros del Plugin

### Ficheros requeridos

```
plugins/mi_plugin/
├── __init__.py         # Package Python (puede estar vacío)
├── manifest.toml       # Declaración plugin (OBLIGATORIO)
├── manifest.py         # Singleton lazy + accessor router
└── module.py           # Clase principal implementando NexeModule
```

### Estructura recomendada (plugin completo)

```
plugins/mi_plugin/
├── __init__.py
├── manifest.toml
├── manifest.py
├── module.py
├── api/
│   └── routes.py       # Endpoints FastAPI
├── core/               # Lógica de negocio
├── cli/                # Subcomandos CLI (opcional)
├── tests/              # Tests unitarios + integración
└── languages/          # Traducciones i18n (ca/es/en)
```

### manifest.py (patrón lazy initialization)

```python
from typing import Optional

_module: Optional["MiPluginModule"] = None
_router = None

def _get_module():
    global _module
    if _module is None:
        from .module import MiPluginModule
        _module = MiPluginModule()
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

## Ciclo de Vida del Plugin

```
DISCOVERY → LOADING → INITIALIZATION → INTEGRATION → RUNNING → SHUTDOWN
```

### 1. Discovery
El ModuleManager escanea `plugins/`, `memory/`, `personality/` buscando ficheros `manifest.toml`. Extrae metadatos sin importar código Python. Detecta ciclos de dependencias.

### 2. Loading
Import dinámico de Python: `from plugins.mi_plugin.module import MiPluginModule`. Valida Protocol NexeModule vía `validate_module()`.

### 3. Initialization
Llama a `await module.initialize(context)`. El contexto contiene:

```python
context = {
    "config": {...},            # Config global de server.toml
    "services": {               # Servicios compartidos
        "logger": logging.Logger,
        "i18n": I18nManager,
        "event_system": EventSystem,
    },
    "modules": ModuleRegistry,  # Acceso a otros módulos cargados
}
```

### 4. Integration
Si el módulo implementa `NexeModuleWithRouter`, el kernel llama a `get_router()` y `get_router_prefix()`, y registra el router en FastAPI.

### 5. Shutdown
Llama a `await module.shutdown()` durante la parada del servidor. Debe ser idempotente.

## Plugins Existentes (5)

| Plugin | Tipo | Router | Características clave |
|--------|------|--------|----------------------|
| **mlx_module** | local_llm_option | /mlx | Nativo Apple Silicon, prefix caching (trie), Metal GPU, is_model_loaded() |
| **llama_cpp_module** | local_llm_option | /llama-cpp | GGUF universal, ModelPool LRU, CPU/GPU, is_model_loaded() |
| **ollama_module** | local_llm_option | /ollama | Bridge HTTP a Ollama, auto-start (open -g macOS), VRAM cleanup, streaming, is_model_loaded() vía /api/ps |
| **security** | core | /security | Auth dual-key, 6 detectores de inyección, 69 patrones jailbreak, rate limiting, logging auditoría RFC5424, permanent=true |
| **web_ui_module** | web_interface | /ui | Chat web, gestor sesiones, subida documentos (aislamiento sesión), memory helper (detección intenciones, MEM_SAVE), i18n (ca/es/en), 6 ficheros de routes |

### Patrones comunes en plugins backend LLM
- Todos implementan `is_model_loaded()` (Ollama vía /api/ps, MLX/llama.cpp vía pool stats)
- Todos soportan streaming vía generadores async
- Todos tienen endpoints `/health` y `/info`
- Prefix del router puesto en constructor (NO después — bug FastAPI arreglado marzo 2026)

## Cómo Crear un Plugin Nuevo (Paso a Paso)

### Paso 1: Crear directorio y ficheros
```bash
mkdir -p plugins/mi_plugin
touch plugins/mi_plugin/__init__.py
```

### Paso 2: Escribir manifest.toml
Copiar la plantilla mínima de arriba. Cambiar nombre, descripción, clase entry y prefix router.

### Paso 3: Escribir module.py
Implementar Protocol NexeModule (property metadata, initialize, shutdown, health_check). Si necesitas endpoints HTTP, implementar también get_router() y get_router_prefix().

**Patrón crítico:** Crear el router PRIMERO en initialize(), antes de cualquier setup que pueda fallar.

```python
async def initialize(self, context):
    if self._initialized:
        return True
    self._init_router()  # SIEMPRE primero
    try:
        # Tu setup aquí
        self._initialized = True
        return True
    except Exception as e:
        logger.error(f"Init failed: {e}")
        return False
```

### Paso 4: Escribir manifest.py
Copiar la plantilla lazy initialization de arriba. Cambiar el import path y nombre de clase.

### Paso 5: Reiniciar servidor
El ModuleManager descubre nuevos plugins automáticamente al arrancar.

### Paso 6: Verificar
```bash
./nexe modules
curl http://127.0.0.1:9119/mi-plugin/health
curl http://127.0.0.1:9119/mi-plugin/info
```

## Errores Comunes

### 1. Falta [module.entry]
Sin `[module.entry]` en manifest.toml, el scanner no puede cargar el plugin. Se omite silenciosamente.

### 2. Prefix router inconsistente
`[module.endpoints].router_prefix` y `[module.router].prefix` DEBEN coincidir.

### 3. Prefix router puesto después del constructor
```python
# MAL — prefix ignorado en FastAPI
self._router = APIRouter()
self._router.prefix = "/mi-plugin"  # ¡No hace nada!

# CORRECTO — prefix en constructor
self._router = APIRouter(prefix="/mi-plugin")
```

### 4. Health_check que bloquea
Nunca usar llamadas HTTP síncronas en health_check(). Usar httpx.AsyncClient async o consultar estado interno cached.

### 5. Initialize/shutdown no idempotente
Ambos métodos pueden llamarse múltiples veces. Poner guard `self._initialized` al principio.

## Buenas Prácticas

1. **Router primero** — Crear router antes de cualquier otro setup en initialize()
2. **Todo idempotente** — initialize() y shutdown() seguros de llamar repetidamente
3. **Health_check rápido** — Menos de 1 segundo, sin llamadas a APIs externas
4. **Declarar dependencias** — En manifest.toml `[module.dependencies].modules`
5. **Usar servicios del context** — i18n, logger, event system del context, no crear propios
6. **Tests junto al código** — En `plugins/mi_plugin/tests/`
7. **Manifest.py lazy** — Nunca importar dependencias pesadas en el escaneo

## Ficheros Fuente Clave

| Concepto | Fichero |
|----------|---------|
| Protocol NexeModule | `core/loader/protocol.py` |
| ModuleMetadata, HealthResult | `core/loader/protocol.py` |
| Descubrimiento de módulos | `personality/module_manager/discovery.py` |
| Ciclo de vida de módulos | `personality/module_manager/module_lifecycle.py` |
| Registro de routers | `core/server/factory_modules.py` |
| Plugin referencia (más limpio) | `plugins/llama_cpp_module/` |
