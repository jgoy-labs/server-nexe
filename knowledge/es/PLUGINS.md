# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentación del sistema de plugins de NEXE. Arquitectura modular con BasePlugin, plugins existentes (MLX, llama.cpp, Ollama, Security, Web UI), tutorial de creación de nuevos plugins y ciclo de vida completo."
tags: [plugins, extensibilidad, mlx, ollama, llama-cpp, BasePlugin, ciclo-de-vida]
chunk_size: 1000
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema de Plugins - NEXE 0.8

NEXE utiliza una **arquitectura de plugins** para hacer el sistema modular, extensible y fácil de mantener. Este documento explica cómo funciona y cómo crear plugins propios.

## Índice

1. [¿Qué son los plugins?](#qué-son-los-plugins)
2. [¿Por qué plugins?](#por-qué-plugins)
3. [Arquitectura del sistema](#arquitectura-del-sistema)
4. [Plugins existentes](#plugins-existentes)
5. [Interface BasePlugin](#interface-baseplugin)
6. [Crear un plugin nuevo](#crear-un-plugin-nuevo)
7. [Ciclo de vida](#ciclo-de-vida)
8. [Registro y descubrimiento](#registro-y-descubrimiento)
9. [Comunicación entre plugins](#comunicación-entre-plugins)
10. [Best practices](#best-practices)
11. [Ejemplos completos](#ejemplos-completos)
12. [Futuro](#futuro)

---

## ¿Qué son los plugins?

Un **plugin** es un **módulo independiente** que añade funcionalidad a NEXE sin modificar el código core.

**Ejemplos:**
- **Backend MLX:** Plugin que permite usar modelos MLX
- **Backend Ollama:** Plugin que hace de bridge a Ollama
- **Security:** Plugin que gestiona autenticación y sanitización
- **Web UI:** Plugin que sirve la interfaz web

### Analogía

Piensa en NEXE como un **sistema operativo** y los plugins como **aplicaciones**:
- El SO (core) proporciona servicios básicos
- Las apps (plugins) añaden funcionalidades específicas
- Puedes instalar/desinstalar apps sin romper el SO

---

## ¿Por qué plugins?

### Ventajas

**1. Modularidad**
```
Sin plugins:
core/ ← Todo el código aquí (mlx, ollama, security, ui...)
  ↓ Código demasiado acoplado, difícil de mantener

Con plugins:
core/ ← Solo lógica esencial
plugins/
  ├── mlx_module/ ← Backend MLX
  ├── ollama_module/ ← Backend Ollama
  └── security/ ← Seguridad
  ↓ Cada plugin es independiente
```

**2. Extensibilidad**

Añadir nueva funcionalidad = Crear un plugin nuevo

**Ejemplo:** Soporte para LM Studio
```bash
# Crear nuevo plugin
mkdir plugins/lmstudio_module/
# Implementar interface
# Registrar en el sistema
# ✅ Funciona sin tocar core!
```

**3. Testabilidad**

Cada plugin se puede testear de forma aislada:

```python
# Test de un plugin específico
def test_mlx_plugin():
    plugin = MLXPlugin()
    await plugin.load_model("phi3")
    response = await plugin.generate("Hola")
    assert len(response) > 0
```

**4. Mantenibilidad**

Los bugs en un plugin no afectan a otros:

```
Bug en el plugin Ollama
  ↓
Solo afecta a la funcionalidad Ollama
  ↓
MLX y llama.cpp siguen funcionando
```

**5. Opcionalidad**

Puedes desactivar los plugins que no necesites:

```python
# .env
ENABLED_PLUGINS=mlx_module,security
# No carga ollama_module ni web_ui_module
```

---

## Arquitectura del sistema

### Jerarquía de plugins

```
BasePlugin (interface base)
    ↓
├── LLMBackendPlugin (interface para backends LLM)
│   ├── MLXPlugin
│   ├── LlamaCppPlugin
│   └── OllamaPlugin
│
├── MiddlewarePlugin (interface para middleware)
│   └── SecurityPlugin
│
└── UIPlugin (interface para interfaces)
    └── WebUIPlugin
```

### Diagrama de componentes

```
┌──────────────────────────────────────────────────────┐
│                    CORE                              │
│  PluginRegistry · PluginLoader · Dependencies       │
└──────────────────────────────────────────────────────┘
                        ↓
        ┌───────────────┼───────────────┐
        ↓               ↓               ↓
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ LLM Backend │  │  Middleware │  │   UI Plugin │
│   Plugins   │  │   Plugins   │  │             │
├─────────────┤  ├─────────────┤  ├─────────────┤
│ MLX         │  │ Security    │  │ Web UI      │
│ llama.cpp   │  │ RateLimit   │  │ CLI         │
│ Ollama      │  │ Logging     │  │             │
└─────────────┘  └─────────────┘  └─────────────┘
```

### Flujo de ejecución

```
Startup
  ↓
PluginRegistry.load_plugins()
  ↓
Descubrir plugins (escanear carpeta plugins/)
  ↓
Para cada plugin:
  1. Import dinámico
  2. Instanciar
  3. Llamar plugin.initialize(config)
  4. Registrar en el registry
  ↓
Plugins cargados y operativos
  ↓
Request (ej: POST /v1/chat/completions)
  ↓
Core hace: plugin_registry.get("mlx")
  ↓
Plugin.generate(prompt)
  ↓
Response
```

---

## Plugins existentes

### 1. MLX Backend (`mlx_module`)

**Propósito:** Backend nativo para Apple Silicon

**Características:**
- Usa `mlx-lm` (Metal acceleration)
- Optimizado para M1/M2/M3/M4
- Formato: Checkpoints MLX (HuggingFace)
- El más rápido en Apple Silicon

**Ubicación:** `plugins/mlx_module/`

**Modelos soportados:**
- mlx-community/Phi-3.5-mini-instruct-4bit
- mlx-community/Mistral-7B-Instruct-v0.3-4bit
- mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
- etc.

### 2. llama.cpp Backend (`llama_cpp_module`)

**Propósito:** Backend universal (Mac, Linux, Windows)

**Características:**
- Usa `llama-cpp-python`
- Soporta modelos GGUF
- Metal (Mac), CUDA (Linux/Win), CPU
- Muy compatible

**Ubicación:** `plugins/llama_cpp_module/`

**Modelos soportados:**
- Cualquier modelo en formato GGUF
- Descargables de HuggingFace (TheBloke, etc.)

### 3. Ollama Backend (`ollama_module`)

**Propósito:** Bridge a Ollama (si ya lo tienes instalado)

**Características:**
- HTTP client a Ollama API
- No gestiona modelos (lo hace Ollama)
- Fácil si ya usas Ollama

**Ubicación:** `plugins/ollama_module/`

**Modelos soportados:**
- Los que tengas en Ollama (`ollama list`)

### 4. Security (`security`)

**Propósito:** Autenticación, sanitización, seguridad

**Características:**
- API Key validation
- Input sanitization (prevenir prompt injection)
- Rate limiting
- Security headers

**Ubicación:** `plugins/security/`

### 5. Web UI (`web_ui_module`)

**Propósito:** Interfaz web básica

**Características:**
- Sirve HTML/CSS/JS estáticos
- Chat UI simple
- Experimental (no prioritario)

**Ubicación:** `plugins/web_ui_module/`

---

## Interface BasePlugin

### Definición

**Ubicación:** `plugins/base.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class BasePlugin(ABC):
    \"\"\"Interface base para todos los plugins\"\"\"

    # Metadata del plugin
    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        \"\"\"
        Inicializar el plugin.
        Se llama durante el startup de NEXE.

        Args:
            config: Configuración del sistema (del .env + defaults)
        \"\"\"
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        \"\"\"
        Cleanup del plugin.
        Se llama durante el shutdown de NEXE.
        \"\"\"
        pass

    async def health_check(self) -> Dict[str, Any]:
        \"\"\"
        Health check del plugin (opcional).

        Returns:
            Dict con estado: {"status": "ok"|"error", "details": ...}
        \"\"\"
        return {"status": "ok"}
```

### Interface LLMBackendPlugin

**Ubicación:** `plugins/base.py`

```python
class LLMBackendPlugin(BasePlugin):
    \"\"\"Interface específica para backends LLM\"\"\"

    @abstractmethod
    async def load_model(self, model_id: str, **kwargs) -> None:
        \"\"\"
        Cargar un modelo LLM.

        Args:
            model_id: Identificador del modelo (path local o HF repo)
            **kwargs: Parámetros específicos del backend
        \"\"\"
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> str:
        \"\"\"
        Generar texto con el modelo.

        Args:
            prompt: Prompt de entrada
            temperature: Creatividad (0.0-1.0)
            max_tokens: Máximo de tokens a generar
            **kwargs: Otros parámetros

        Returns:
            Texto generado
        \"\"\"
        pass

    @abstractmethod
    async def unload_model(self) -> None:
        \"\"\"
        Descargar modelo de memoria.
        Liberar recursos (RAM, VRAM).
        \"\"\"
        pass

    async def get_model_info(self) -> Dict[str, Any]:
        \"\"\"
        Información sobre el modelo cargado.

        Returns:
            Dict con: name, size, parameters, etc.
        \"\"\"
        return {}
```

---

## Crear un plugin nuevo

### Ejemplo: Plugin LM Studio

Paso a paso para crear un plugin que hace bridge a LM Studio.

#### Paso 1: Crear estructura

```bash
mkdir -p plugins/lmstudio_module
touch plugins/lmstudio_module/__init__.py
touch plugins/lmstudio_module/plugin.py
```

#### Paso 2: Implementar plugin

**`plugins/lmstudio_module/plugin.py`:**

```python
import httpx
from typing import Dict, Any
from plugins.base import LLMBackendPlugin

class LMStudioPlugin(LLMBackendPlugin):
    \"\"\"Plugin para usar LM Studio como backend\"\"\"

    name = "lmstudio"
    version = "0.1.0"
    description = "Bridge a LM Studio local server"

    def __init__(self):
        self.base_url = "http://localhost:1234"  # Puerto por defecto LM Studio
        self.client = None
        self.model = None

    async def initialize(self, config: Dict[str, Any]) -> None:
        \"\"\"Inicializar cliente HTTP\"\"\"
        self.base_url = config.get("lmstudio_url", self.base_url)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120.0  # Los LLMs pueden tardar
        )
        print(f"✓ LMStudio plugin inicializado ({self.base_url})")

    async def load_model(self, model_id: str, **kwargs) -> None:
        \"\"\"
        'Cargar' modelo (solo guardar el nombre).
        LM Studio gestiona los modelos.
        \"\"\"
        # Verificar que LM Studio está corriendo
        try:
            response = await self.client.get("/v1/models")
            response.raise_for_status()
            models = response.json()["data"]
        except Exception as e:
            raise RuntimeError(f"LM Studio no accesible: {e}")

        # Verificar que el modelo existe
        model_ids = [m["id"] for m in models]
        if model_id not in model_ids:
            raise ValueError(
                f"Modelo {model_id} no encontrado en LM Studio. "
                f"Disponibles: {model_ids}"
            )

        self.model = model_id
        print(f"✓ Modelo {model_id} seleccionado")

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> str:
        \"\"\"Generar texto via LM Studio API\"\"\"
        if not self.model:
            raise RuntimeError("Ningún modelo cargado")

        # LM Studio usa API compatible OpenAI
        response = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False
            }
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def unload_model(self) -> None:
        \"\"\"No es necesario descargar (LM Studio lo gestiona)\"\"\"
        self.model = None
        print("✓ Modelo liberado")

    async def shutdown(self) -> None:
        \"\"\"Cerrar cliente HTTP\"\"\"
        if self.client:
            await self.client.aclose()
        print("✓ LMStudio plugin shutdown")

    async def health_check(self) -> Dict[str, Any]:
        \"\"\"Verificar que LM Studio está disponible\"\"\"
        try:
            response = await self.client.get("/v1/models", timeout=5.0)
            response.raise_for_status()
            return {"status": "ok", "url": self.base_url}
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "hint": "Verifica que LM Studio está corriendo"
            }

    async def get_model_info(self) -> Dict[str, Any]:
        \"\"\"Info del modelo cargado\"\"\"
        if not self.model:
            return {}

        try:
            response = await self.client.get("/v1/models")
            models = response.json()["data"]
            model_info = next(m for m in models if m["id"] == self.model)
            return {
                "id": model_info["id"],
                "owned_by": model_info.get("owned_by", "unknown")
            }
        except Exception:
            return {"id": self.model}
```

#### Paso 3: Registrar plugin

**`plugins/lmstudio_module/__init__.py`:**

```python
from .plugin import LMStudioPlugin

# Exportar para descubrimiento automático
__all__ = ["LMStudioPlugin"]
```

#### Paso 4: Configurar

**En el `.env`:**

```bash
# Añadir LM Studio a los backends disponibles
AVAILABLE_BACKENDS=mlx,llama_cpp,ollama,lmstudio

# Configuración LM Studio (opcional)
LMSTUDIO_URL=http://localhost:1234
```

#### Paso 5: Usar

```bash
# Seleccionar backend en el .env
NEXE_BACKEND=lmstudio
MODEL_ID=llama-3.1-8b  # Modelo que tienes en LM Studio

# Iniciar NEXE
./nexe go

# ¡Ahora NEXE usa LM Studio!
```

---

## Ciclo de vida

### Diagrama de ciclo de vida

```
┌─────────────────────────────────────────────────────┐
│ 1. DESCUBRIMIENTO                                   │
│    PluginRegistry escanea plugins/                  │
│    Encuentra: MLXPlugin, OllamaPlugin, SecurityPlugin│
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 2. INSTANCIACIÓN                                    │
│    plugin = MLXPlugin()                             │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 3. INICIALIZACIÓN                                   │
│    await plugin.initialize(config)                  │
│    - Cargar recursos                                │
│    - Conectar servicios externos                    │
│    - Setup interno                                  │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 4. REGISTRO                                         │
│    plugin_registry.register("mlx", plugin)          │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 5. OPERACIÓN (mientras NEXE está en ejecución)     │
│    - Recibir requests                               │
│    - Ejecutar tareas                                │
│    - Health checks periódicos                       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 6. SHUTDOWN                                         │
│    await plugin.shutdown()                          │
│    - Cleanup de recursos                            │
│    - Cerrar conexiones                              │
│    - Guardar estado si es necesario                 │
└─────────────────────────────────────────────────────┘
```

### Código del ciclo de vida

**`core/lifespan.py`:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from plugins.registry import plugin_registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    \"\"\"Gestión del ciclo de vida de NEXE\"\"\"

    # ========== STARTUP ==========
    print("Iniciando NEXE...")

    # 1. Cargar configuración
    config = load_config()

    # 2. Descubrir y cargar plugins
    print("Cargando plugins...")
    await plugin_registry.load_plugins(config)

    # 3. Seleccionar backend activo
    backend_name = config.get("backend", "mlx")
    backend = plugin_registry.get(backend_name)

    if not backend:
        raise RuntimeError(f"Backend '{backend_name}' no encontrado")

    # 4. Cargar modelo
    print(f"Cargando modelo {config.get('model_id')}...")
    await backend.load_model(config.get("model_id"))

    # 5. Health check inicial
    print("Health check plugins...")
    for name, plugin in plugin_registry.plugins.items():
        health = await plugin.health_check()
        status = "✓" if health["status"] == "ok" else "✗"
        print(f"  {status} {name}")

    print("NEXE operativo")

    # La app está en ejecución aquí
    yield

    # ========== SHUTDOWN ==========
    print("Deteniendo NEXE...")

    # 1. Descargar modelo
    await backend.unload_model()

    # 2. Shutdown de todos los plugins
    await plugin_registry.shutdown_all()

    print("NEXE detenido")
```

---

## Registro y descubrimiento

### PluginRegistry

**Ubicación:** `plugins/registry.py`

```python
import importlib
import inspect
from pathlib import Path
from typing import Dict
from plugins.base import BasePlugin

class PluginRegistry:
    \"\"\"Registry central de plugins\"\"\"

    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}

    async def load_plugins(self, config: Dict) -> None:
        \"\"\"Descubrir y cargar todos los plugins\"\"\"

        plugins_dir = Path(__file__).parent
        plugin_modules = [
            d for d in plugins_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]

        for plugin_dir in plugin_modules:
            module_name = plugin_dir.name

            # Saltar si está deshabilitado
            if not self._is_enabled(module_name, config):
                print(f"⊗ {module_name} (deshabilitado)")
                continue

            try:
                # Import dinámico
                module = importlib.import_module(f"plugins.{module_name}")

                # Buscar clases que heredan de BasePlugin
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BasePlugin) and
                        obj is not BasePlugin):

                        # Instanciar e inicializar
                        plugin = obj()
                        await plugin.initialize(config)

                        # Registrar
                        self.register(plugin.name, plugin)
                        print(f"✓ {plugin.name} v{plugin.version}")

            except Exception as e:
                print(f"✗ Error cargando {module_name}: {e}")

    def register(self, name: str, plugin: BasePlugin) -> None:
        \"\"\"Registrar un plugin\"\"\"
        self.plugins[name] = plugin

    def get(self, name: str) -> BasePlugin:
        \"\"\"Obtener un plugin por nombre\"\"\"
        return self.plugins.get(name)

    def list_plugins(self) -> Dict[str, BasePlugin]:
        \"\"\"Listar todos los plugins\"\"\"
        return self.plugins.copy()

    async def shutdown_all(self) -> None:
        \"\"\"Shutdown de todos los plugins\"\"\"
        for name, plugin in self.plugins.items():
            try:
                await plugin.shutdown()
                print(f"✓ {name} shutdown")
            except Exception as e:
                print(f"✗ Error en shutdown de {name}: {e}")

    def _is_enabled(self, module_name: str, config: Dict) -> bool:
        \"\"\"Verificar si un plugin está habilitado\"\"\"
        enabled_plugins = config.get("enabled_plugins", None)

        if enabled_plugins is None:
            # Por defecto, todos habilitados
            return True

        return module_name in enabled_plugins.split(",")

# Singleton global
plugin_registry = PluginRegistry()
```

---

## Comunicación entre plugins

### Dependency injection

Los plugins pueden acceder a otros plugins a través del registry:

```python
class MyPlugin(BasePlugin):
    async def initialize(self, config):
        # Acceder a otro plugin
        self.security_plugin = plugin_registry.get("security")

    async def do_something(self, data):
        # Usar el otro plugin
        sanitized = await self.security_plugin.sanitize(data)
        # ...
```

### Events (futuro)

Sistema de eventos para comunicación desacoplada:

```python
# Plugin A emite evento
event_bus.emit("model_loaded", {"model_id": "phi3"})

# Plugin B escucha evento
@event_bus.on("model_loaded")
async def on_model_loaded(data):
    print(f"Modelo {data['model_id']} cargado!")
```

---

## Best practices

### 1. Mantén los plugins simples

❌ **Mal:**
```python
class MegaPlugin(BasePlugin):
    # Hace demasiadas cosas: backend, UI, security, logs...
    pass
```

✅ **Bien:**
```python
class MLXBackendPlugin(LLMBackendPlugin):
    # Solo gestiona backend MLX
    pass

class SecurityPlugin(MiddlewarePlugin):
    # Solo gestiona seguridad
    pass
```

### 2. Gestiona los errores gracefully

```python
async def initialize(self, config):
    try:
        self.resource = await connect_to_resource()
    except Exception as e:
        # Log del error
        logger.error(f"Error inicializando {self.name}: {e}")
        # No propagar (dejar que otros plugins funcionen)
        self.resource = None

async def do_something(self):
    if self.resource is None:
        raise RuntimeError(f"{self.name} no inicializado correctamente")
    # ...
```

### 3. Implementa health checks

```python
async def health_check(self):
    try:
        # Verificar que todo funciona
        await self.resource.ping()
        return {"status": "ok"}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "hint": "Verifica la configuración"
        }
```

### 4. Cleanup siempre

```python
async def shutdown(self):
    \"\"\"SIEMPRE implementar cleanup\"\"\"
    if self.resource:
        await self.resource.close()
        self.resource = None

    if self.temp_files:
        for f in self.temp_files:
            f.unlink()  # Borrar ficheros temporales
```

### 5. Documenta el plugin

```python
class MyPlugin(BasePlugin):
    \"\"\"
    Plugin para hacer X.

    Configuración (.env):
        MY_PLUGIN_URL: URL del servicio externo
        MY_PLUGIN_TIMEOUT: Timeout en segundos (default: 30)

    Dependencies:
        - httpx
        - pydantic

    Example:
        plugin = MyPlugin()
        await plugin.initialize(config)
        result = await plugin.do_something()
    \"\"\"
    pass
```

---

## Ejemplos completos

### Ejemplo 1: Plugin de logging

```python
from plugins.base import BasePlugin
import logging
from pathlib import Path

class LoggingPlugin(BasePlugin):
    \"\"\"Plugin para gestionar logs estructurados\"\"\"

    name = "logging"
    version = "0.1.0"
    description = "Advanced logging with rotation and filtering"

    def __init__(self):
        self.logger = None
        self.log_file = None

    async def initialize(self, config):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        self.log_file = log_dir / "nexe.log"

        # Setup logging
        self.logger = logging.getLogger("nexe")
        self.logger.setLevel(config.get("log_level", "INFO"))

        # File handler con rotation
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(
            self.log_file,
            maxBytes=10_000_000,  # 10 MB
            backupCount=5
        )
        handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        )
        self.logger.addHandler(handler)

        print(f"✓ Logging en {self.log_file}")

    def log(self, level: str, message: str, **kwargs):
        \"\"\"Log con metadata extra\"\"\"
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} | {extra}" if extra else message

        getattr(self.logger, level.lower())(full_message)

    async def shutdown(self):
        if self.logger:
            for handler in self.logger.handlers:
                handler.close()
        print("✓ Logging shutdown")
```

### Ejemplo 2: Plugin de cache

```python
from plugins.base import BasePlugin
from typing import Any, Optional
import hashlib
import json
import time

class CachePlugin(BasePlugin):
    \"\"\"Plugin para cachear respuestas del modelo\"\"\"

    name = "cache"
    version = "0.1.0"
    description = "LRU cache for model responses"

    def __init__(self):
        self.cache = {}
        self.max_size = 100
        self.ttl = 3600  # 1 hora

    async def initialize(self, config):
        self.max_size = config.get("cache_size", 100)
        self.ttl = config.get("cache_ttl", 3600)
        print(f"✓ Cache (size={self.max_size}, ttl={self.ttl}s)")

    def _hash_key(self, prompt: str, **params) -> str:
        \"\"\"Generar clave de cache\"\"\"
        data = {"prompt": prompt, **params}
        return hashlib.md5(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

    def get(self, prompt: str, **params) -> Optional[str]:
        \"\"\"Obtener del cache\"\"\"
        key = self._hash_key(prompt, **params)
        entry = self.cache.get(key)

        if entry is None:
            return None

        # Verificar TTL
        if time.time() - entry["timestamp"] > self.ttl:
            del self.cache[key]
            return None

        return entry["response"]

    def set(self, prompt: str, response: str, **params):
        \"\"\"Guardar en el cache\"\"\"
        key = self._hash_key(prompt, **params)

        # Evict si el cache está lleno (LRU simple)
        if len(self.cache) >= self.max_size:
            oldest_key = min(
                self.cache.keys(),
                key=lambda k: self.cache[k]["timestamp"]
            )
            del self.cache[oldest_key]

        self.cache[key] = {
            "response": response,
            "timestamp": time.time()
        }

    async def shutdown(self):
        self.cache.clear()
        print("✓ Cache shutdown")
```

**Uso:**

```python
# En el endpoint de chat
cache_plugin = plugin_registry.get("cache")

# Intentar obtener del cache
cached_response = cache_plugin.get(prompt, temperature=0.7)
if cached_response:
    return cached_response  # Cache hit!

# Si no está en el cache, generar
response = await backend.generate(prompt)

# Guardar en el cache
cache_plugin.set(prompt, response, temperature=0.7)

return response
```

---

## Futuro

### Plugins planificados

1. **LM Studio bridge** (0.9)
2. **vLLM backend** (para inferencia muy rápida)
3. **Metrics collector** (formato Prometheus)
4. **Telemetry** (opcional, opt-in)
5. **Voice input/output** (STT/TTS)

### Sistema de eventos

Comunicación desacoplada entre plugins:

```python
@event_bus.on("request_received")
async def on_request(data):
    # Logging, metrics, etc.
    pass
```

### Plugin marketplace (sueño lejano)

Repositorio de plugins de la comunidad:

```bash
./nexe plugin install community/my-cool-plugin
```

---

## Recursos

### Documentación relacionada

- **ARCHITECTURE.md** - Arquitectura general
- **API.md** - Cómo integrar con la API

### Inspiración

- **Pytest plugins:** https://docs.pytest.org/en/stable/how-to/writing_plugins.html
- **FastAPI dependencies:** https://fastapi.tiangolo.com/tutorial/dependencies/
- **Plugin architecture patterns:** https://en.wikipedia.org/wiki/Plug-in_(computing)

---

## Siguientes pasos

1. **API.md** - Referencia de la API REST
2. **LIMITATIONS.md** - Limitaciones del sistema
3. **ROADMAP.md** - Futuro de NEXE

---

**Nota:** El sistema de plugins es experimental y puede evolucionar. Si creas plugins interesantes, ¡compártelos con la comunidad!

**Filosofía:** Simplicidad > Complejidad. No sobre-ingenierices los plugins.
