# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-plugins-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentation for the NEXE plugin system. Modular architecture with BasePlugin, existing plugins (MLX, llama.cpp, Ollama, Security, Web UI), tutorial for creating new plugins and complete lifecycle."
tags: [plugins, extensibility, mlx, ollama, llama-cpp, BasePlugin, lifecycle]
chunk_size: 1000
priority: P2

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Plugin System - NEXE 0.8

NEXE uses a **plugin architecture** to make the system modular, extensible and easy to maintain. This document explains how it works and how to create your own plugins.

## Table of Contents

1. [What are plugins?](#what-are-plugins)
2. [Why plugins?](#why-plugins)
3. [System architecture](#system-architecture)
4. [Existing plugins](#existing-plugins)
5. [BasePlugin interface](#baseplugin-interface)
6. [Creating a new plugin](#creating-a-new-plugin)
7. [Lifecycle](#lifecycle)
8. [Registry and discovery](#registry-and-discovery)
9. [Communication between plugins](#communication-between-plugins)
10. [Best practices](#best-practices)
11. [Complete examples](#complete-examples)
12. [Future](#future)

---

## What are plugins?

A **plugin** is an **independent module** that adds functionality to NEXE without modifying the core code.

**Examples:**
- **Backend MLX:** Plugin that allows using MLX models
- **Backend Ollama:** Plugin that acts as a bridge to Ollama
- **Security:** Plugin that handles authentication and sanitization
- **Web UI:** Plugin that serves the web interface

### Analogy

Think of NEXE as an **operating system** and plugins as **applications**:
- The OS (core) provides basic services
- The apps (plugins) add specific functionalities
- You can install/uninstall apps without breaking the OS

---

## Why plugins?

### Advantages

**1. Modularity**
```
Without plugins:
core/ ← All code here (mlx, ollama, security, ui...)
  ↓ Code too tightly coupled, hard to maintain

With plugins:
core/ ← Only essential logic
plugins/
  ├── mlx_module/ ← Backend MLX
  ├── ollama_module/ ← Backend Ollama
  └── security/ ← Security
  ↓ Each plugin is independent
```

**2. Extensibility**

Adding new functionality = Creating a new plugin

**Example:** Support for LM Studio
```bash
# Create new plugin
mkdir plugins/lmstudio_module/
# Implement interface
# Register in the system
# ✅ Works without touching core!
```

**3. Testability**

Each plugin can be tested in isolation:

```python
# Test for a specific plugin
def test_mlx_plugin():
    plugin = MLXPlugin()
    await plugin.load_model("phi3")
    response = await plugin.generate("Hello")
    assert len(response) > 0
```

**4. Maintainability**

Bugs in one plugin do not affect others:

```
Bug in the Ollama plugin
  ↓
Only affects Ollama functionality
  ↓
MLX and llama.cpp keep working
```

**5. Optionality**

You can disable plugins you do not need:

```python
# .env
ENABLED_PLUGINS=mlx_module,security
# Does not load ollama_module or web_ui_module
```

---

## System architecture

### Plugin hierarchy

```
BasePlugin (base interface)
    ↓
├── LLMBackendPlugin (interface for LLM backends)
│   ├── MLXPlugin
│   ├── LlamaCppPlugin
│   └── OllamaPlugin
│
├── MiddlewarePlugin (interface for middleware)
│   └── SecurityPlugin
│
└── UIPlugin (interface for interfaces)
    └── WebUIPlugin
```

### Component diagram

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

### Execution flow

```
Startup
  ↓
PluginRegistry.load_plugins()
  ↓
Discover plugins (scan plugins/ folder)
  ↓
For each plugin:
  1. Dynamic import
  2. Instantiate
  3. Call plugin.initialize(config)
  4. Register in registry
  ↓
Plugins loaded and operational
  ↓
Request (e.g.: POST /v1/chat/completions)
  ↓
Core does: plugin_registry.get("mlx")
  ↓
Plugin.generate(prompt)
  ↓
Response
```

---

## Existing plugins

### 1. MLX Backend (`mlx_module`)

**Purpose:** Native backend for Apple Silicon

**Features:**
- Uses `mlx-lm` (Metal acceleration)
- Optimized for M1/M2/M3/M4
- Format: MLX Checkpoints (HuggingFace)
- Fastest on Apple Silicon

**Location:** `plugins/mlx_module/`

**Supported models:**
- mlx-community/Phi-3.5-mini-instruct-4bit
- mlx-community/Mistral-7B-Instruct-v0.3-4bit
- mlx-community/Meta-Llama-3.1-8B-Instruct-4bit
- etc.

### 2. llama.cpp Backend (`llama_cpp_module`)

**Purpose:** Universal backend (Mac, Linux, Windows)

**Features:**
- Uses `llama-cpp-python`
- Supports GGUF models
- Metal (Mac), CUDA (Linux/Win), CPU
- Highly compatible

**Location:** `plugins/llama_cpp_module/`

**Supported models:**
- Any model in GGUF format
- Downloadable from HuggingFace (TheBloke, etc.)

### 3. Ollama Backend (`ollama_module`)

**Purpose:** Bridge to Ollama (if you already have it installed)

**Features:**
- HTTP client to Ollama API
- Does not manage models (Ollama does that)
- Easy if you already use Ollama

**Location:** `plugins/ollama_module/`

**Supported models:**
- Those you have in Ollama (`ollama list`)

### 4. Security (`security`)

**Purpose:** Authentication, sanitization, security

**Features:**
- API Key validation
- Input sanitization (prevent prompt injection)
- Rate limiting
- Security headers

**Location:** `plugins/security/`

### 5. Web UI (`web_ui_module`)

**Purpose:** Basic web interface

**Features:**
- Serves static HTML/CSS/JS
- Simple Chat UI
- Experimental (not a priority)

**Location:** `plugins/web_ui_module/`

---

## BasePlugin interface

### Definition

**Location:** `plugins/base.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class BasePlugin(ABC):
    \"\"\"Base interface for all plugins\"\"\"

    # Plugin metadata
    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        \"\"\"
        Initialize the plugin.
        Called during NEXE startup.

        Args:
            config: System configuration (from .env + defaults)
        \"\"\"
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        \"\"\"
        Plugin cleanup.
        Called during NEXE shutdown.
        \"\"\"
        pass

    async def health_check(self) -> Dict[str, Any]:
        \"\"\"
        Plugin health check (optional).

        Returns:
            Dict with status: {"status": "ok"|"error", "details": ...}
        \"\"\"
        return {"status": "ok"}
```

### LLMBackendPlugin interface

**Location:** `plugins/base.py`

```python
class LLMBackendPlugin(BasePlugin):
    \"\"\"Specific interface for LLM backends\"\"\"

    @abstractmethod
    async def load_model(self, model_id: str, **kwargs) -> None:
        \"\"\"
        Load an LLM model.

        Args:
            model_id: Model identifier (local path or HF repo)
            **kwargs: Backend-specific parameters
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
        Generate text with the model.

        Args:
            prompt: Input prompt
            temperature: Creativity (0.0-1.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Other parameters

        Returns:
            Generated text
        \"\"\"
        pass

    @abstractmethod
    async def unload_model(self) -> None:
        \"\"\"
        Unload model from memory.
        Release resources (RAM, VRAM).
        \"\"\"
        pass

    async def get_model_info(self) -> Dict[str, Any]:
        \"\"\"
        Information about the loaded model.

        Returns:
            Dict with: name, size, parameters, etc.
        \"\"\"
        return {}
```

---

## Creating a new plugin

### Example: LM Studio plugin

Step by step to create a plugin that bridges to LM Studio.

#### Step 1: Create structure

```bash
mkdir -p plugins/lmstudio_module
touch plugins/lmstudio_module/__init__.py
touch plugins/lmstudio_module/plugin.py
```

#### Step 2: Implement plugin

**`plugins/lmstudio_module/plugin.py`:**

```python
import httpx
from typing import Dict, Any
from plugins.base import LLMBackendPlugin

class LMStudioPlugin(LLMBackendPlugin):
    \"\"\"Plugin to use LM Studio as a backend\"\"\"

    name = "lmstudio"
    version = "0.1.0"
    description = "Bridge a LM Studio local server"

    def __init__(self):
        self.base_url = "http://localhost:1234"  # Default LM Studio port
        self.client = None
        self.model = None

    async def initialize(self, config: Dict[str, Any]) -> None:
        \"\"\"Initialize HTTP client\"\"\"
        self.base_url = config.get("lmstudio_url", self.base_url)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120.0  # LLMs can take time
        )
        print(f"✓ LMStudio plugin initialized ({self.base_url})")

    async def load_model(self, model_id: str, **kwargs) -> None:
        \"\"\"
        'Load' model (just store the name).
        LM Studio manages the models.
        \"\"\"
        # Check that LM Studio is running
        try:
            response = await self.client.get("/v1/models")
            response.raise_for_status()
            models = response.json()["data"]
        except Exception as e:
            raise RuntimeError(f"LM Studio not accessible: {e}")

        # Check that the model exists
        model_ids = [m["id"] for m in models]
        if model_id not in model_ids:
            raise ValueError(
                f"Model {model_id} not found in LM Studio. "
                f"Available: {model_ids}"
            )

        self.model = model_id
        print(f"✓ Model {model_id} selected")

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        **kwargs
    ) -> str:
        \"\"\"Generate text via LM Studio API\"\"\"
        if not self.model:
            raise RuntimeError("No model loaded")

        # LM Studio uses OpenAI-compatible API
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
        \"\"\"No need to unload (LM Studio manages it)\"\"\"
        self.model = None
        print("✓ Model released")

    async def shutdown(self) -> None:
        \"\"\"Close HTTP client\"\"\"
        if self.client:
            await self.client.aclose()
        print("✓ LMStudio plugin shutdown")

    async def health_check(self) -> Dict[str, Any]:
        \"\"\"Check that LM Studio is available\"\"\"
        try:
            response = await self.client.get("/v1/models", timeout=5.0)
            response.raise_for_status()
            return {"status": "ok", "url": self.base_url}
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "hint": "Check that LM Studio is running"
            }

    async def get_model_info(self) -> Dict[str, Any]:
        \"\"\"Info about the loaded model\"\"\"
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

#### Step 3: Register plugin

**`plugins/lmstudio_module/__init__.py`:**

```python
from .plugin import LMStudioPlugin

# Export for automatic discovery
__all__ = ["LMStudioPlugin"]
```

#### Step 4: Configure

**In the `.env`:**

```bash
# Add LM Studio to available backends
AVAILABLE_BACKENDS=mlx,llama_cpp,ollama,lmstudio

# LM Studio configuration (optional)
LMSTUDIO_URL=http://localhost:1234
```

#### Step 5: Use

```bash
# Select backend in .env
NEXE_BACKEND=lmstudio
MODEL_ID=llama-3.1-8b  # Model you have in LM Studio

# Start NEXE
./nexe go

# NEXE now uses LM Studio!
```

---

## Lifecycle

### Lifecycle diagram

```
┌─────────────────────────────────────────────────────┐
│ 1. DISCOVERY                                        │
│    PluginRegistry scans plugins/                    │
│    Finds: MLXPlugin, OllamaPlugin, SecurityPlugin  │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 2. INSTANTIATION                                    │
│    plugin = MLXPlugin()                             │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 3. INITIALIZATION                                   │
│    await plugin.initialize(config)                  │
│    - Load resources                                 │
│    - Connect external services                      │
│    - Internal setup                                 │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 4. REGISTRATION                                     │
│    plugin_registry.register("mlx", plugin)          │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 5. OPERATION (while NEXE is running)               │
│    - Receive requests                               │
│    - Execute tasks                                  │
│    - Periodic health checks                         │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ 6. SHUTDOWN                                         │
│    await plugin.shutdown()                          │
│    - Resource cleanup                               │
│    - Close connections                              │
│    - Save state if needed                           │
└─────────────────────────────────────────────────────┘
```

### Lifecycle code

**`core/lifespan.py`:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from plugins.registry import plugin_registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    \"\"\"NEXE lifecycle management\"\"\"

    # ========== STARTUP ==========
    print("Starting NEXE...")

    # 1. Load configuration
    config = load_config()

    # 2. Discover and load plugins
    print("Loading plugins...")
    await plugin_registry.load_plugins(config)

    # 3. Select active backend
    backend_name = config.get("backend", "mlx")
    backend = plugin_registry.get(backend_name)

    if not backend:
        raise RuntimeError(f"Backend '{backend_name}' not found")

    # 4. Load model
    print(f"Loading model {config.get('model_id')}...")
    await backend.load_model(config.get("model_id"))

    # 5. Initial health check
    print("Plugin health check...")
    for name, plugin in plugin_registry.plugins.items():
        health = await plugin.health_check()
        status = "✓" if health["status"] == "ok" else "✗"
        print(f"  {status} {name}")

    print("NEXE operational")

    # App is running here
    yield

    # ========== SHUTDOWN ==========
    print("Stopping NEXE...")

    # 1. Unload model
    await backend.unload_model()

    # 2. Shutdown all plugins
    await plugin_registry.shutdown_all()

    print("NEXE stopped")
```

---

## Registry and discovery

### PluginRegistry

**Location:** `plugins/registry.py`

```python
import importlib
import inspect
from pathlib import Path
from typing import Dict
from plugins.base import BasePlugin

class PluginRegistry:
    \"\"\"Central plugin registry\"\"\"

    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}

    async def load_plugins(self, config: Dict) -> None:
        \"\"\"Discover and load all plugins\"\"\"

        plugins_dir = Path(__file__).parent
        plugin_modules = [
            d for d in plugins_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]

        for plugin_dir in plugin_modules:
            module_name = plugin_dir.name

            # Skip if disabled
            if not self._is_enabled(module_name, config):
                print(f"⊗ {module_name} (disabled)")
                continue

            try:
                # Dynamic import
                module = importlib.import_module(f"plugins.{module_name}")

                # Find classes that inherit from BasePlugin
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BasePlugin) and
                        obj is not BasePlugin):

                        # Instantiate and initialize
                        plugin = obj()
                        await plugin.initialize(config)

                        # Register
                        self.register(plugin.name, plugin)
                        print(f"✓ {plugin.name} v{plugin.version}")

            except Exception as e:
                print(f"✗ Error loading {module_name}: {e}")

    def register(self, name: str, plugin: BasePlugin) -> None:
        \"\"\"Register a plugin\"\"\"
        self.plugins[name] = plugin

    def get(self, name: str) -> BasePlugin:
        \"\"\"Get a plugin by name\"\"\"
        return self.plugins.get(name)

    def list_plugins(self) -> Dict[str, BasePlugin]:
        \"\"\"List all plugins\"\"\"
        return self.plugins.copy()

    async def shutdown_all(self) -> None:
        \"\"\"Shutdown all plugins\"\"\"
        for name, plugin in self.plugins.items():
            try:
                await plugin.shutdown()
                print(f"✓ {name} shutdown")
            except Exception as e:
                print(f"✗ Error shutting down {name}: {e}")

    def _is_enabled(self, module_name: str, config: Dict) -> bool:
        \"\"\"Check if a plugin is enabled\"\"\"
        enabled_plugins = config.get("enabled_plugins", None)

        if enabled_plugins is None:
            # By default, all enabled
            return True

        return module_name in enabled_plugins.split(",")

# Global singleton
plugin_registry = PluginRegistry()
```

---

## Communication between plugins

### Dependency injection

Plugins can access other plugins through the registry:

```python
class MyPlugin(BasePlugin):
    async def initialize(self, config):
        # Access another plugin
        self.security_plugin = plugin_registry.get("security")

    async def do_something(self, data):
        # Use the other plugin
        sanitized = await self.security_plugin.sanitize(data)
        # ...
```

### Events (future)

Event system for decoupled communication:

```python
# Plugin A emits event
event_bus.emit("model_loaded", {"model_id": "phi3"})

# Plugin B listens to event
@event_bus.on("model_loaded")
async def on_model_loaded(data):
    print(f"Model {data['model_id']} loaded!")
```

---

## Best practices

### 1. Keep plugins simple

❌ **Wrong:**
```python
class MegaPlugin(BasePlugin):
    # Does too many things: backend, UI, security, logs...
    pass
```

✅ **Right:**
```python
class MLXBackendPlugin(LLMBackendPlugin):
    # Only manages MLX backend
    pass

class SecurityPlugin(MiddlewarePlugin):
    # Only manages security
    pass
```

### 2. Handle errors gracefully

```python
async def initialize(self, config):
    try:
        self.resource = await connect_to_resource()
    except Exception as e:
        # Log error
        logger.error(f"Error initializing {self.name}: {e}")
        # Do not propagate (let other plugins work)
        self.resource = None

async def do_something(self):
    if self.resource is None:
        raise RuntimeError(f"{self.name} not correctly initialized")
    # ...
```

### 3. Implement health checks

```python
async def health_check(self):
    try:
        # Check that everything works
        await self.resource.ping()
        return {"status": "ok"}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "hint": "Check the configuration"
        }
```

### 4. Always cleanup

```python
async def shutdown(self):
    \"\"\"ALWAYS implement cleanup\"\"\"
    if self.resource:
        await self.resource.close()
        self.resource = None

    if self.temp_files:
        for f in self.temp_files:
            f.unlink()  # Delete temporary files
```

### 5. Document the plugin

```python
class MyPlugin(BasePlugin):
    \"\"\"
    Plugin to do X.

    Configuration (.env):
        MY_PLUGIN_URL: URL of the external service
        MY_PLUGIN_TIMEOUT: Timeout in seconds (default: 30)

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

## Complete examples

### Example 1: Logging plugin

```python
from plugins.base import BasePlugin
import logging
from pathlib import Path

class LoggingPlugin(BasePlugin):
    \"\"\"Plugin to manage structured logs\"\"\"

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

        # File handler with rotation
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

        print(f"✓ Logging to {self.log_file}")

    def log(self, level: str, message: str, **kwargs):
        \"\"\"Log with extra metadata\"\"\"
        extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} | {extra}" if extra else message

        getattr(self.logger, level.lower())(full_message)

    async def shutdown(self):
        if self.logger:
            for handler in self.logger.handlers:
                handler.close()
        print("✓ Logging shutdown")
```

### Example 2: Cache plugin

```python
from plugins.base import BasePlugin
from typing import Any, Optional
import hashlib
import json
import time

class CachePlugin(BasePlugin):
    \"\"\"Plugin to cache model responses\"\"\"

    name = "cache"
    version = "0.1.0"
    description = "LRU cache for model responses"

    def __init__(self):
        self.cache = {}
        self.max_size = 100
        self.ttl = 3600  # 1 hour

    async def initialize(self, config):
        self.max_size = config.get("cache_size", 100)
        self.ttl = config.get("cache_ttl", 3600)
        print(f"✓ Cache (size={self.max_size}, ttl={self.ttl}s)")

    def _hash_key(self, prompt: str, **params) -> str:
        \"\"\"Generate cache key\"\"\"
        data = {"prompt": prompt, **params}
        return hashlib.md5(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

    def get(self, prompt: str, **params) -> Optional[str]:
        \"\"\"Get from cache\"\"\"
        key = self._hash_key(prompt, **params)
        entry = self.cache.get(key)

        if entry is None:
            return None

        # Check TTL
        if time.time() - entry["timestamp"] > self.ttl:
            del self.cache[key]
            return None

        return entry["response"]

    def set(self, prompt: str, response: str, **params):
        \"\"\"Save to cache\"\"\"
        key = self._hash_key(prompt, **params)

        # Evict if cache is full (simple LRU)
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

**Usage:**

```python
# In the chat endpoint
cache_plugin = plugin_registry.get("cache")

# Try to get from cache
cached_response = cache_plugin.get(prompt, temperature=0.7)
if cached_response:
    return cached_response  # Cache hit!

# If not in cache, generate
response = await backend.generate(prompt)

# Save to cache
cache_plugin.set(prompt, response, temperature=0.7)

return response
```

---

## Future

### Planned plugins

1. **LM Studio bridge** (0.9)
2. **vLLM backend** (for very fast inference)
3. **Metrics collector** (Prometheus format)
4. **Telemetry** (optional, opt-in)
5. **Voice input/output** (STT/TTS)

### Event system

Decoupled communication between plugins:

```python
@event_bus.on("request_received")
async def on_request(data):
    # Logging, metrics, etc.
    pass
```

### Plugin marketplace (distant dream)

Community plugin repository:

```bash
./nexe plugin install community/my-cool-plugin
```

---

## Resources

### Related documentation

- **ARCHITECTURE.md** - General architecture
- **API.md** - How to integrate with the API

### Inspiration

- **Pytest plugins:** https://docs.pytest.org/en/stable/how-to/writing_plugins.html
- **FastAPI dependencies:** https://fastapi.tiangolo.com/tutorial/dependencies/
- **Plugin architecture patterns:** https://en.wikipedia.org/wiki/Plug-in_(computing)

---

## Next steps

1. **API.md** - REST API reference
2. **LIMITATIONS.md** - System limitations
3. **ROADMAP.md** - Future of NEXE

---

**Note:** The plugin system is experimental and may evolve. If you create interesting plugins, share them with the community!

**Philosophy:** Simplicity > Complexity. Do not over-engineer your plugins.
