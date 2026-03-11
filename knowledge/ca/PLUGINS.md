# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentació del sistema de plugins de NEXE. Arquitectura modular amb BasePlugin, plugins existents (MLX, llama.cpp, Ollama, Security, Web UI), tutorial de creació de nous plugins i cicle de vida complet."
tags: [plugins, extensibilitat, mlx, ollama, llama-cpp, BasePlugin, cicle-de-vida]
chunk_size: 1000
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema de Plugins - NEXE 0.8

NEXE utilitza una **arquitectura de plugins** per fer el sistema modular, extensible i fàcil de mantenir. Aquest document explica com funciona i com crear plugins propis.

## Índex

1. [Què són els plugins?](#què-són-els-plugins)
2. [Per què plugins?](#per-què-plugins)
3. [Arquitectura del sistema](#arquitectura-del-sistema)
4. [Plugins existents](#plugins-existents)
5. [Interface BasePlugin](#interface-baseplugin)
6. [Crear un plugin nou](#crear-un-plugin-nou)
7. [Cicle de vida](#cicle-de-vida)
8. [Registre i descobriment](#registre-i-descobriment)
9. [Comunicació entre plugins](#comunicació-entre-plugins)
10. [Best practices](#best-practices)
11. [Exemples complets](#exemples-complets)
12. [Futur](#futur)

---

## Què són els plugins?

Un **plugin** és un **mòdul independent** que afegeix funcionalitat a NEXE sense modificar el codi core.

**Exemples:**
- **Backend MLX:** Plugin que permet usar models MLX
- **Backend Ollama:** Plugin que fa de bridge a Ollama
- **Security:** Plugin que gestiona autenticació i sanitització
- **Web UI:** Plugin que serveix la interfície web

### Analogia

Pensa en NEXE com un **sistema operatiu** i els plugins com **aplicacions**:
- El SO (core) proporciona serveis bàsics
- Les apps (plugins) afegeixen funcionalitats específiques
- Pots instal·lar/desinstal·lar apps sense trencar el SO

---

## Per què plugins?

### Avantatges

**1. Modularitat**
```
Sense plugins:
core/ ← Tot el codi aquí (mlx, ollama, security, ui...)
  ↓ Codi massa acoblat, difícil mantenir

Amb plugins:
core/ ← Només lògica essencial
plugins/
  ├── mlx_module/ ← Backend MLX
  ├── ollama_module/ ← Backend Ollama
  └── security/ ← Seguretat
  ↓ Cada plugin és independent
```

**2. Extensibilitat**

Afegir funcionalitat nova = Crear un plugin nou

**Exemple:** Suportar un nou backend
```bash
# Crear nou plugin
mkdir plugins/custom_module/
# Implementar interface
# Registrar al sistema
# ✅ Funciona sense tocar core!
```

**3. Testabilitat**

Cada plugin es pot testar aïlladament:

```python
# Test d'un plugin específic
def test_mlx_plugin():
    plugin = MLXPlugin()
    await plugin.load_model("phi3")
    response = await plugin.generate("Hola")
    assert len(response) > 0
```

**4. Mantenibilitat**

Bugs en un plugin no afecten altres:

```
Bug al plugin Ollama
  ↓
Només afecta funcionalitat Ollama
  ↓
MLX i llama.cpp segueixen funcionant
```

**5. Opcionalitat**

Pots desactivar plugins que no necessites:

```python
# .env
ENABLED_PLUGINS=mlx_module,security
# No carrega ollama_module ni web_ui_module
```

---

## Arquitectura del sistema

### Jerarquia de plugins

```
BasePlugin (interface base)
    ↓
├── LLMBackendPlugin (interface per backends LLM)
│   ├── MLXPlugin
│   ├── LlamaCppPlugin
│   └── OllamaPlugin
│
├── MiddlewarePlugin (interface per middleware)
│   └── SecurityPlugin
│
└── UIPlugin (interface per interfícies)
    └── WebUIPlugin
```

### Diagrama de components

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

### Flux d'execució

```
Startup
  ↓
PluginRegistry.load_plugins()
  ↓
Descobrir plugins (scan carpeta plugins/)
  ↓
Per cada plugin:
  1. Import dinàmic
  2. Instanciar
  3. Cridar plugin.initialize(config)
  4. Registrar al registry
  ↓
Plugins carregats i operatius
  ↓
Request (ex: POST /v1/chat/completions)
  ↓
Core fa: plugin_registry.get("mlx")
  ↓
Plugin.generate(prompt)
  ↓
Response
```

---

## Plugins existents

### 1. MLX Backend (`mlx_module`)

**Propòsit:** Backend natiu per Apple Silicon

**Característiques:**
- Usa `mlx-lm` (Metal acceleration)
- Optimitzat per M1/M2/M3/M4
- Format: Checkpoints MLX (HuggingFace)
- El més ràpid en Apple Silicon

**Ubicació:** `plugins/mlx_module/`

**Models suportats:**
- mlx-community/Phi-3.5-mini-instruct-4bit
- mlx-community/Mistral-7B-Instruct-v0.3-4bit
- mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
- etc.

### 2. llama.cpp Backend (`llama_cpp_module`)

**Propòsit:** Backend universal (Mac, Linux, Windows)

**Característiques:**
- Usa `llama-cpp-python`
- Suporta GGUF models
- Metal (Mac), CUDA (Linux/Win), CPU
- Molt compatible

**Ubicació:** `plugins/llama_cpp_module/`

**Models suportats:**
- Qualsevol model en format GGUF
- Descarregables de HuggingFace (TheBloke, etc.)

### 3. Ollama Backend (`ollama_module`)

**Propòsit:** Bridge a Ollama (si ja el tens instal·lat)

**Característiques:**
- HTTP client a Ollama API
- No gestiona models (ho fa Ollama)
- Fàcil si ja uses Ollama

**Ubicació:** `plugins/ollama_module/`

**Models suportats:**
- Els que tinguis a Ollama (`ollama list`)

### 4. Security (`security`)

**Propòsit:** Autenticació, sanitització, seguretat

**Característiques:**
- API Key validation
- Input sanitization (prevenir prompt injection)
- Rate limiting
- Security headers

**Ubicació:** `plugins/security/`

### 5. Web UI (`web_ui_module`)

**Propòsit:** Interfície web bàsica

**Característiques:**
- Serveix HTML/CSS/JS estàtics
- Chat UI simple
- Experimental (no prioritari)

**Ubicació:** `plugins/web_ui_module/`

---

## Interface BasePlugin

### Definició

**Ubicació:** `plugins/base.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class BasePlugin(ABC):
    """Interface base per tots els plugins"""

    # Metadata del plugin
    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        """
        Inicialitzar el plugin.
        Es crida durant el startup de NEXE.

        Args:
            config: Configuració del sistema (del .env + defaults)
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Cleanup del plugin.
        Es crida durant el shutdown de NEXE.
        """
        pass

    async def health_check(self) -> Dict[str, Any]:
        """
        Health check del plugin (opcional).

        Returns:
            Dict amb estat: {"status": "ok"|"error", "details": ...}
        """
        return {"status": "ok"}
```

### Interface LLMBackendPlugin

**Ubicació:** `plugins/base.py`

```python
class LLMBackendPlugin(BasePlugin):
    """Interface específica per backends LLM"""

    @abstractmethod
    async def load_model(self, model_id: str, **kwargs) -> None:
        """
        Carregar un model LLM.

        Args:
            model_id: Identificador del model (path local o HF repo)
            **kwargs: Paràmetres específics del backend
        """
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> str:
        """
        Generar text amb el model.

        Args:
            prompt: Prompt d'entrada
            temperature: Creativitat (0.0-1.0)
            max_tokens: Màxim tokens a generar
            **kwargs: Altres paràmetres

        Returns:
            Text generat
        """
        pass

    @abstractmethod
    async def unload_model(self) -> None:
        """
        Descarregar model de memòria.
        Alliberar recursos (RAM, VRAM).
        """
        pass

    async def get_model_info(self) -> Dict[str, Any]:
        """
        Informació sobre el model carregat.

        Returns:
            Dict amb: name, size, parameters, etc.
        """
        return {}
```

---

## Crear un plugin nou

### Exemple: Plugin per backend extern compatible OpenAI

Pas a pas per crear un plugin que fa bridge a un servidor local compatible amb l'API OpenAI.

#### Pas 1: Crear estructura

```bash
mkdir -p plugins/custom_backend_module
touch plugins/custom_backend_module/__init__.py
touch plugins/custom_backend_module/plugin.py
```

#### Pas 2: Implementar plugin

**`plugins/custom_backend_module/plugin.py`:**

```python
import httpx
from typing import Dict, Any
from plugins.base import LLMBackendPlugin

class CustomBackendPlugin(LLMBackendPlugin):
    """Plugin per usar un backend local compatible amb l'API OpenAI"""

    name = "custom_backend"
    version = "0.1.0"
    description = "Bridge a un servidor local compatible OpenAI"

    def __init__(self):
        self.base_url = "http://localhost:1234"  # Port del backend extern
        self.client = None
        self.model = None

    async def initialize(self, config: Dict[str, Any]) -> None:
        """Inicialitzar client HTTP"""
        self.base_url = config.get("custom_backend_url", self.base_url)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120.0  # LLMs poden trigar
        )
        print(f"✓ CustomBackend plugin inicialitzat ({self.base_url})")

    async def load_model(self, model_id: str, **kwargs) -> None:
        """
        'Carregar' model (només guardar el nom).
        El backend extern gestiona els models.
        """
        # Verificar que el backend extern està corrent
        try:
            response = await self.client.get("/v1/models")
            response.raise_for_status()
            models = response.json()["data"]
        except Exception as e:
            raise RuntimeError(f"Backend extern no accessible: {e}")

        # Verificar que el model existeix
        model_ids = [m["id"] for m in models]
        if model_id not in model_ids:
            raise ValueError(
                f"Model {model_id} no trobat al backend. "
                f"Disponibles: {model_ids}"
            )

        self.model = model_id
        print(f"✓ Model {model_id} seleccionat")

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> str:
        """Generar text via API compatible OpenAI"""
        if not self.model:
            raise RuntimeError("Cap model carregat")

        # API compatible OpenAI
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
        """No cal descarregar (el backend extern ho gestiona)"""
        self.model = None
        print("✓ Model alliberat")

    async def shutdown(self) -> None:
        """Tancar client HTTP"""
        if self.client:
            await self.client.aclose()
        print("✓ CustomBackend plugin shutdown")

    async def health_check(self) -> Dict[str, Any]:
        """Verificar que el backend extern està disponible"""
        try:
            response = await self.client.get("/v1/models", timeout=5.0)
            response.raise_for_status()
            return {"status": "ok", "url": self.base_url}
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "hint": "Verifica que el backend extern està corrent"
            }

    async def get_model_info(self) -> Dict[str, Any]:
        """Info del model carregat"""
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

#### Pas 3: Registrar plugin

**`plugins/custom_backend_module/__init__.py`:**

```python
from .plugin import CustomBackendPlugin

# Exportar per descobriment automàtic
__all__ = ["CustomBackendPlugin"]
```

#### Pas 4: Configurar

**Al `.env`:**

```bash
# Afegir el backend personalitzat als backends disponibles
AVAILABLE_BACKENDS=mlx,llama_cpp,ollama,custom_backend

# Configuració del backend (opcional)
CUSTOM_BACKEND_URL=http://localhost:1234
```

#### Pas 5: Usar

```bash
# Seleccionar backend al .env
NEXE_BACKEND=custom_backend
MODEL_ID=nom-del-model

# Iniciar NEXE
./nexe go

# Ara NEXE usa el backend personalitzat!
```

---

## Cicle de vida

### Diagrama de cicle de vida

```
┌─────────────────────────────────────────────────────┐
│ 1. DESCOBRIMENT                                     │
│    PluginRegistry escaneja plugins/                 │
│    Troba: MLXPlugin, OllamaPlugin, SecurityPlugin  │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 2. INSTANCIACIÓ                                     │
│    plugin = MLXPlugin()                             │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 3. INICIALITZACIÓ                                   │
│    await plugin.initialize(config)                  │
│    - Carregar recursos                              │
│    - Connectar serveis externs                      │
│    - Setup intern                                   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 4. REGISTRE                                         │
│    plugin_registry.register("mlx", plugin)          │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 5. OPERACIÓ (mentre NEXE està running)             │
│    - Rebre requests                                 │
│    - Executar tasques                               │
│    - Health checks periòdics                        │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 6. SHUTDOWN                                         │
│    await plugin.shutdown()                          │
│    - Cleanup recursos                               │
│    - Tancar connexions                              │
│    - Guardar estat si cal                           │
└─────────────────────────────────────────────────────┘
```

### Codi del cicle de vida

**`core/lifespan.py`:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from plugins.registry import plugin_registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestió del cicle de vida de NEXE"""

    # ========== STARTUP ==========
    print("🚀 Iniciant NEXE...")

    # 1. Carregar configuració
    config = load_config()

    # 2. Descobrir i carregar plugins
    print("📦 Carregant plugins...")
    await plugin_registry.load_plugins(config)

    # 3. Seleccionar backend actiu
    backend_name = config.get("backend", "mlx")
    backend = plugin_registry.get(backend_name)

    if not backend:
        raise RuntimeError(f"Backend '{backend_name}' no trobat")

    # 4. Carregar model
    print(f"🧠 Carregant model {config.get('model_id')}...")
    await backend.load_model(config.get("model_id"))

    # 5. Health check inicial
    print("🏥 Health check plugins...")
    for name, plugin in plugin_registry.plugins.items():
        health = await plugin.health_check()
        status = "✓" if health["status"] == "ok" else "✗"
        print(f"  {status} {name}")

    print("✅ NEXE operatiu")

    # App està running aquí
    yield

    # ========== SHUTDOWN ==========
    print("🛑 Aturant NEXE...")

    # 1. Descarregar model
    await backend.unload_model()

    # 2. Shutdown tots els plugins
    await plugin_registry.shutdown_all()

    print("👋 NEXE aturat")
```

---

## Registre i descobriment

### PluginRegistry

**Ubicació:** `plugins/registry.py`

```python
import importlib
import inspect
from pathlib import Path
from typing import Dict
from plugins.base import BasePlugin

class PluginRegistry:
    """Registry central de plugins"""

    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}

    async def load_plugins(self, config: Dict) -> None:
        """Descobrir i carregar tots els plugins"""

        plugins_dir = Path(__file__).parent
        plugin_modules = [
            d for d in plugins_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]

        for plugin_dir in plugin_modules:
            module_name = plugin_dir.name

            # Saltar si està deshabilitat
            if not self._is_enabled(module_name, config):
                print(f"⊗ {module_name} (deshabilitat)")
                continue

            try:
                # Import dinàmic
                module = importlib.import_module(f"plugins.{module_name}")

                # Buscar classes que hereten de BasePlugin
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BasePlugin) and
                        obj is not BasePlugin):

                        # Instanciar i inicialitzar
                        plugin = obj()
                        await plugin.initialize(config)

                        # Registrar
                        self.register(plugin.name, plugin)
                        print(f"✓ {plugin.name} v{plugin.version}")

            except Exception as e:
                print(f"✗ Error carregant {module_name}: {e}")

    def register(self, name: str, plugin: BasePlugin) -> None:
        """Registrar un plugin"""
        self.plugins[name] = plugin

    def get(self, name: str) -> BasePlugin:
        """Obtenir un plugin pel nom"""
        return self.plugins.get(name)

    def list_plugins(self) -> Dict[str, BasePlugin]:
        """Llistar tots els plugins"""
        return self.plugins.copy()

    async def shutdown_all(self) -> None:
        """Shutdown de tots els plugins"""
        for name, plugin in self.plugins.items():
            try:
                await plugin.shutdown()
                print(f"✓ {name} shutdown")
            except Exception as e:
                print(f"✗ Error shutdown {name}: {e}")

    def _is_enabled(self, module_name: str, config: Dict) -> bool:
        """Verificar si un plugin està habilitat"""
        enabled_plugins = config.get("enabled_plugins", None)

        if enabled_plugins is None:
            # Per defecte, tots habilitats
            return True

        return module_name in enabled_plugins.split(",")

# Singleton global
plugin_registry = PluginRegistry()
```

---

## Comunicació entre plugins

### Dependency injection

Els plugins poden accedir a altres plugins via el registry:

```python
class MyPlugin(BasePlugin):
    async def initialize(self, config):
        # Accedir a un altre plugin
        self.security_plugin = plugin_registry.get("security")

    async def do_something(self, data):
        # Usar l'altre plugin
        sanitized = await self.security_plugin.sanitize(data)
        # ...
```

### Events (futur)

Sistema d'events per comunicació desacoblada:

```python
# Plugin A emet event
event_bus.emit("model_loaded", {"model_id": "phi3"})

# Plugin B escolta event
@event_bus.on("model_loaded")
async def on_model_loaded(data):
    print(f"Model {data['model_id']} carregat!")
```

---

## Best practices

### 1. Mantén plugins simples

❌ **Malament:**
```python
class MegaPlugin(BasePlugin):
    # Fa massa coses: backend, UI, security, logs...
    pass
```

✅ **Bé:**
```python
class MLXBackendPlugin(LLMBackendPlugin):
    # Només gestiona backend MLX
    pass

class SecurityPlugin(MiddlewarePlugin):
    # Només gestiona seguretat
    pass
```

### 2. Gestiona errors gracefully

```python
async def initialize(self, config):
    try:
        self.resource = await connect_to_resource()
    except Exception as e:
        # Log error
        logger.error(f"Error inicialitzant {self.name}: {e}")
        # No propagar (deixar altres plugins funcionar)
        self.resource = None

async def do_something(self):
    if self.resource is None:
        raise RuntimeError(f"{self.name} no inicialitzat correctament")
    # ...
```

### 3. Implementa health checks

```python
async def health_check(self):
    try:
        # Verificar que tot funciona
        await self.resource.ping()
        return {"status": "ok"}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "hint": "Verifica la configuració"
        }
```

### 4. Cleanup sempre

```python
async def shutdown(self):
    """SEMPRE implementar cleanup"""
    if self.resource:
        await self.resource.close()
        self.resource = None

    if self.temp_files:
        for f in self.temp_files:
            f.unlink()  # Esborrar fitxers temporals
```

### 5. Documenta el plugin

```python
class MyPlugin(BasePlugin):
    """
    Plugin per fer X.

    Configuració (.env):
        MY_PLUGIN_URL: URL del servei extern
        MY_PLUGIN_TIMEOUT: Timeout en segons (default: 30)

    Dependencies:
        - httpx
        - pydantic

    Example:
        plugin = MyPlugin()
        await plugin.initialize(config)
        result = await plugin.do_something()
    """
    pass
```

---

## Exemples complets

### Exemple 1: Plugin de logging

```python
from plugins.base import BasePlugin
import logging
from pathlib import Path

class LoggingPlugin(BasePlugin):
    """Plugin per gestionar logs estructurats"""

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

        # File handler amb rotation
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

        print(f"✓ Logging a {self.log_file}")

    def log(self, level: str, message: str, **kwargs):
        """Log amb metadata extra"""
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} | {extra}" if extra else message

        getattr(self.logger, level.lower())(full_message)

    async def shutdown(self):
        if self.logger:
            for handler in self.logger.handlers:
                handler.close()
        print("✓ Logging shutdown")
```

### Exemple 2: Plugin de cache

```python
from plugins.base import BasePlugin
from typing import Any, Optional
import hashlib
import json
import time

class CachePlugin(BasePlugin):
    """Plugin per cachear respostes del model"""

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
        """Generar clau de cache"""
        data = {"prompt": prompt, **params}
        return hashlib.md5(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

    def get(self, prompt: str, **params) -> Optional[str]:
        """Obtenir del cache"""
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
        """Guardar al cache"""
        key = self._hash_key(prompt, **params)

        # Evict si cache ple (LRU simple)
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

**Ús:**

```python
# Al endpoint de chat
cache_plugin = plugin_registry.get("cache")

# Intentar obtenir del cache
cached_response = cache_plugin.get(prompt, temperature=0.7)
if cached_response:
    return cached_response  # Cache hit! 🎉

# Si no està al cache, generar
response = await backend.generate(prompt)

# Guardar al cache
cache_plugin.set(prompt, response, temperature=0.7)

return response
```

---

## Futur

### Plugins planificats

1. **Metrics collector** (Prometheus format)
2. **Telemetry** (opcional, opt-in)
3. **Voice input/output** (STT/TTS)

### Sistema d'events

Comunicació desacoblada entre plugins:

```python
@event_bus.on("request_received")
async def on_request(data):
    # Logging, metrics, etc.
    pass
```

### Plugin marketplace (somni llunyà)

Repositori de plugins de la comunitat:

```bash
./nexe plugin install community/my-cool-plugin
```

---

## Recursos

### Documentació relacionada

- **ARCHITECTURE.md** - Arquitectura general
- **API.md** - Com integrar amb l'API

### Inspiració

- **Pytest plugins:** https://docs.pytest.org/en/stable/how-to/writing_plugins.html
- **FastAPI dependencies:** https://fastapi.tiangolo.com/tutorial/dependencies/
- **Plugin architecture patterns:** https://en.wikipedia.org/wiki/Plug-in_(computing)

---

## Següents passos

1. **API.md** - Referència de l'API REST
2. **LIMITATIONS.md** - Limitacions del sistema
3. **ROADMAP.md** - Futur de NEXE

---

**Nota:** El sistema de plugins és experimental i pot evolucionar. Si crees plugins interessants, comparteix-los amb la comunitat!

**Filosofia:** Simplicitat > Complexitat. No sobre-enginyeris els plugins.
