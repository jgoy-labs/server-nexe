# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-architecture

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Overview of NEXE 0.8 internal architecture. Three layers: Interfaces → Core → Plugins → Base Services. Covers Factory Pattern, lifespan manager, 3-layer memory system, CLI and design decisions."
tags: [architecture, fastapi, plugins, qdrant, memory, lifespan, cli, design]
chunk_size: 1500
priority: P2

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Architecture - NEXE 0.8

> **📝 Document updated:** 2026-02-04
> **⚠️ IMPORTANT:** This document has been reviewed and updated to reflect the **actual code** of Nexe 0.8.
> Previous versions contained simplified or outdated descriptions. This version is **accurate and honest** about the current implementation.

This documentation explains how NEXE is built internally. It is useful if you want to:
- Understand how the system works
- Contribute to the project
- Create plugins or extensions
- Debug problems
- Learn about AI systems architecture

## Overview

NEXE is designed with a **modular five-layer architecture**:

```
┌─────────────────────────────────────────────────────┐
│                    INTERFACES                       │
│  CLI (./nexe) │ REST API │ Web UI                  │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                       CORE                          │
│  Server │ Endpoints │ Middleware │ Lifespan        │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                     PLUGINS                         │
│  MLX │ llama.cpp │ Ollama │ Security │ Web UI      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                  BASE SERVICES                      │
│  Memory (RAG) │ Qdrant │ Embeddings │ SQLite       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                     STORAGE                         │
│  models/ │ qdrant/ │ vectors/ │ logs/ │ cache/     │
└─────────────────────────────────────────────────────┘
```

### Design principles

1. **Modularity:** Decoupled and interchangeable components
2. **Plugin-based:** Backends are plugins loaded dynamically
3. **API-first:** Everything accessible via REST API
4. **Native RAG:** Memory is first-class, not an add-on
5. **Simplicity:** Readable code, avoid over-engineering

---

## Directory structure

```
server-nexe/
├── core/                      # System core
│   ├── __init__.py
│   ├── app.py                 # Entry point FastAPI
│   ├── config.py              # Global configuration (TOML + .env)
│   ├── container.py           # Dependency injection container
│   ├── dependencies.py        # FastAPI dependencies (rate limiting)
│   ├── lifespan.py            # Lifecycle management (starts Qdrant/Ollama)
│   ├── middleware.py          # HTTP Middleware (CORS, CSRF, logging)
│   ├── models.py              # Pydantic models
│   ├── resources.py           # Resource management
│   ├── security_headers.py    # OWASP security headers
│   ├── utils.py               # General utilities
│   ├── bootstrap_tokens.py    # Bootstrap token system (DB persist)
│   ├── request_size_limiter.py # DoS protection (100MB limit)
│   │
│   ├── cli/                   # Command line interface (Click)
│   │   ├── __init__.py
│   │   ├── cli.py             # Main CLI (Click + DynamicGroup)
│   │   ├── router.py          # Dynamic router (discovers module CLIs)
│   │   ├── chat_cli.py        # Interactive chat command
│   │   ├── log_viewer.py      # View logs in real time
│   │   ├── output.py          # CLI output formatting
│   │   └── client.py          # HTTP client for local API
│   │
│   ├── endpoints/             # API REST endpoints
│   │   ├── __init__.py
│   │   ├── chat.py            # POST /v1/chat/completions (RAG + streaming)
│   │   ├── root.py            # GET /, /health, /api/info
│   │   ├── system.py          # POST /admin/system/* (restart, status)
│   │   ├── modules.py         # GET /modules (loaded modules info)
│   │   ├── bootstrap.py       # POST /bootstrap/init, GET /bootstrap/info
│   │   └── v1.py              # v1 endpoints wrapper
│   │
│   ├── server/                # Factory pattern (singleton cached)
│   │   ├── __init__.py
│   │   ├── factory.py         # Main facade create_app()
│   │   ├── factory_app.py     # Create FastAPI instance
│   │   ├── factory_state.py   # Setup app.state
│   │   ├── factory_security.py # SecurityLogger, prod validation
│   │   ├── factory_i18n.py    # I18n + config setup
│   │   ├── factory_modules.py # Module discovery and loading
│   │   ├── factory_routers.py # Core routers registration
│   │   ├── runner.py          # Uvicorn server runner
│   │   └── helpers.py         # Factory utilities
│   │
│   ├── loader/                # Dynamic module loading
│   │   ├── __init__.py
│   │   └── module_loader.py   # Python module loader
│   │
│   ├── metrics/               # Prometheus metrics
│   │   ├── __init__.py
│   │   ├── endpoint.py        # /metrics, /metrics/json
│   │   ├── collector.py       # Metrics collector
│   │   └── registry.py        # Prometheus registry
│   │
│   ├── ingest/                # Document ingestion knowledge/
│   │   ├── __init__.py
│   │   └── ingest_knowledge.py # Auto-ingest .md, .txt, .pdf
│   │
│   ├── paths/                 # Project path management
│   │   ├── __init__.py
│   │   └── path_resolver.py
│   │
│   └── resilience/            # Resilience (retry, timeout)
│       ├── __init__.py
│       └── retry.py
│
├── plugins/                   # Plugin modules (no base.py/registry.py)
│   ├── __init__.py
│   │
│   ├── mlx_module/            # MLX backend (Apple Silicon)
│   │   ├── __init__.py
│   │   ├── manifest.toml      # Module metadata (v0.8 format)
│   │   ├── module.py          # MLXModule class
│   │   ├── chat.py            # MLXChatNode (workflow)
│   │   ├── config.py          # MLXConfig (Metal detection)
│   │   └── manifest.py        # Lazy loader + router FastAPI
│   │
│   ├── llama_cpp_module/      # llama.cpp backend
│   │   ├── __init__.py
│   │   ├── manifest.toml
│   │   ├── module.py          # LlamaCppModule
│   │   └── manifest.py
│   │
│   ├── ollama_module/         # Ollama backend (HTTP bridge)
│   │   ├── __init__.py
│   │   ├── manifest.toml
│   │   ├── module.py          # OllamaModule
│   │   ├── client.py          # AsyncHTTP client to Ollama
│   │   └── manifest.py
│   │
│   ├── security/              # Full security plugin
│   │   ├── __init__.py
│   │   ├── manifest.toml
│   │   ├── manifest.py        # Router /security/*
│   │   ├── core/              # Auth, validation, sanitization
│   │   │   ├── auth.py            # API key verification
│   │   │   ├── auth_dependencies.py # FastAPI Depends
│   │   │   ├── auth_config.py     # Dual-key config
│   │   │   ├── auth_models.py     # KeyStatus, ApiKeyData
│   │   │   ├── input_validators.py # Input validation
│   │   │   ├── input_sanitizers.py # RAG sanitization
│   │   │   ├── injection_detectors.py # Prompt injection
│   │   │   ├── rate_limiting.py    # Rate limiters
│   │   │   └── validators.py       # Path traversal protection
│   │   └── tests/             # Security tests
│   │
│   ├── security_logger/       # SIEM logging
│   │   ├── __init__.py
│   │   ├── manifest.toml
│   │   └── logger.py          # SecurityEventLogger
│   │
│   └── web_ui_module/         # Web UI
│       ├── __init__.py
│       ├── manifest.toml
│       ├── module.py
│       └── static/            # HTML, CSS, JS, assets
│
├── memory/                    # RAG system (3 sublayers)
│   ├── __init__.py
│   │
│   ├── embeddings/            # Sublayer: Vector generation
│   │   ├── __init__.py
│   │   ├── module.py          # EmbeddingsModule (singleton)
│   │   ├── manifest.toml
│   │   ├── core/              # Core embedding logic
│   │   │   ├── vectorstore.py     # Qdrant interface
│   │   │   ├── cached_embedder.py # Cache + async encoder
│   │   │   ├── async_encoder.py   # Batch encoding
│   │   │   └── chunker.py         # Split text/code
│   │   ├── chunkers/          # Chunking strategies
│   │   │   ├── text_chunker.py    # Semantic chunks
│   │   │   └── code_chunker.py    # Code-aware chunks
│   │   └── api/               # REST API
│   │       └── v1.py              # POST /v1/embeddings (501)
│   │
│   ├── memory/                # Sublayer: Memory management
│   │   ├── __init__.py
│   │   ├── module.py          # MemoryModule (FlashMemory + RAMContext)
│   │   ├── manifest.toml
│   │   ├── engines/           # Memory engines
│   │   │   ├── flash_memory.py    # Temporary cache (TTL)
│   │   │   ├── ram_context.py     # Current session context
│   │   │   └── persistence.py     # SQLite + Qdrant persist
│   │   ├── pipeline/          # Ingestion pipeline
│   │   │   └── ingestion.py       # Document → embedding → store
│   │   ├── api/               # REST API
│   │   │   ├── __init__.py
│   │   │   ├── v1.py              # POST /v1/memory/store|search
│   │   │   ├── operations.py      # CRUD operations
│   │   │   ├── collections.py     # Collection management
│   │   │   └── documents.py       # Document operations
│   │   ├── workflow/          # Workflow nodes
│   │   │   ├── memory_store_node.py   # Store operation
│   │   │   └── memory_recall_node.py  # Retrieve operation
│   │   └── cli.py             # CLI: ./nexe memory
│   │
│   ├── rag/                   # Sublayer: RAG orchestration
│   │   ├── __init__.py
│   │   ├── module.py          # RAGModule
│   │   ├── manifest.toml
│   │   ├── workflow/          # RAG workflow
│   │   │   └── rag_search_node.py # Search implementation
│   │   ├── api/               # REST API
│   │   │   ├── __init__.py
│   │   │   └── v1.py              # POST /v1/rag/search
│   │   ├── routers/           # UI routers
│   │   │   ├── endpoints.py       # API endpoints
│   │   │   └── ui.py              # UI endpoints
│   │   └── cli.py             # CLI: ./nexe rag
│   │
│   ├── rag_sources/           # Pluggable RAG sources
│   │   ├── __init__.py
│   │   ├── base.py            # SearchRequest, SearchHit models
│   │   └── personality/       # Personality docs source
│   │
│   └── shared/                # Shared utilities
│       └── models.py          # Common models
│
├── personality/               # Personality and system configuration
│   ├── __init__.py
│   ├── server.toml            # Main configuration (TOML)
│   ├── integration.py         # APIIntegrator
│   │
│   ├── i18n/                  # Internationalization
│   │   ├── i18n_manager.py
│   │   └── translations/      # ca.json, en.json, es.json
│   │
│   ├── module_manager/        # SINGLE SOURCE OF TRUTH for modules
│   │   ├── module_manager.py  # ModuleManager facade
│   │   ├── registry.py        # ModuleRegistry
│   │   ├── discovery.py       # Module discovery
│   │   ├── path_discovery.py  # Path resolution
│   │   ├── config_manager.py  # Config + manifests
│   │   ├── module_lifecycle.py # Individual lifecycle
│   │   └── system_lifecycle.py # System lifecycle
│   │
│   ├── models/                # Model selection system
│   │   ├── selector.py        # Hardware detection + recommendations
│   │   └── registry.py        # Verified models registry
│   │
│   ├── events/                # Event system
│   │   └── event_system.py
│   │
│   └── metrics/               # Metrics collector
│       └── metrics_collector.py
│
├── knowledge/                 # Auto-ingested documents (RAG)
│   ├── ARCHITECTURE.md        # (this document)
│   ├── SECURITY.md
│   ├── API.md
│   └── ...                    # Automatically ingested into Qdrant
│
├── storage/                   # Persistence (NOT in git)
│   ├── qdrant/                # Qdrant local storage
│   ├── vectors/               # Vector DBs
│   │   ├── qdrant_local/
│   │   └── metadata_memory.db # SQLite metadata
│   ├── models/                # Downloaded LLM models
│   ├── system-logs/           # Security logs (SIEM)
│   │   └── security/
│   └── .knowledge_ingested    # Marker file (auto-ingest)
│
├── dev-tools/                 # Development tools
│   └── ...
│
├── nexe                       # CLI executable (#!/usr/bin/env bash)
├── qdrant                     # Qdrant binary (auto-downloaded)
├── requirements.txt           # Python dependencies
├── install_nexe.py            # Automatic installer
├── setup.sh                   # Setup script
├── conftest.py                # pytest configuration
└── pytest.ini                 # pytest config
```

---

## Main components

### 1. Core

The system core, based on **FastAPI**.

#### app.py + Factory Pattern

**IMPORTANT**: The app is NOT created directly in app.py. A **factory pattern** with **singleton cached** is used:

**core/app.py** (entry point):
```python
"""Entry point - delegates to factory"""
from core.server.factory import create_app

app = create_app()  # Singleton cached (0.58s → <0.01s)
```

**core/server/factory.py** (actual factory):
```python
from pathlib import Path
from fastapi import FastAPI
import threading

_app_instance: Optional[FastAPI] = None
_app_lock = threading.Lock()

def create_app(project_root: Optional[Path] = None, force_reload: bool = False) -> FastAPI:
    """
    Application factory - Singleton cached with double-check locking.

    Performance:
    - First call (cold): ~0.5-0.6s (i18n, config, module discovery)
    - Cached calls (warm): <0.01s (returns existing instance)
    """
    global _app_instance

    # Double-check locking pattern
    if _app_instance is not None and not force_reload:
        return _app_instance

    with _app_lock:
        if _app_instance is not None and not force_reload:
            return _app_instance

        # Create app via factory submodules
        i18n, config, module_manager = setup_i18n_and_config(project_root)
        app = create_fastapi_instance(i18n, config)
        setup_app_state(app, i18n, config, project_root, module_manager)
        setup_security_logger(app, project_root, i18n)
        discover_and_load_modules(app, module_manager, project_root, i18n)
        register_core_routers(app, i18n)

        _app_instance = app
        return app
```

**Advantages of the Factory Pattern:**
- **Performance**: Singleton cache avoids rebuild (0.58s → 10ms)
- **Thread-safe**: Double-check locking pattern
- **Testable**: `reset_app_cache()` for tests
- **Modular**: Split into factory_app.py, factory_state.py, factory_modules.py, etc.

#### lifespan.py

**Complex lifecycle manager** (~635 lines) that handles:

1. **Auto-start external services** (Qdrant, Ollama)
2. **Module initialization** (Memory, RAG, Embeddings, plugins)
3. **Bootstrap tokens** (generation + DB persistence)
4. **Auto-ingest knowledge/** (first run)
5. **Cleanup Ollama** (unload models from RAM)
6. **Graceful shutdown**

**Simplified example:**

```python
from contextlib import asynccontextmanager
import subprocess
from pathlib import Path

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    logger.info("LIFESPAN STARTUP TRIGGERED")

    # 1. Auto-start Qdrant (local binary, NO Docker)
    qdrant_bin = project_root / "qdrant"
    if qdrant_bin.exists():
        process = subprocess.Popen([str(qdrant_bin), "--disable-telemetry"], ...)
        server_state.qdrant_process = process
        # Wait for Qdrant ready (asyncio.sleep, no time.sleep!)
        for i in range(30):
            await asyncio.sleep(0.5)
            if await check_qdrant_health():
                break

    # 2. Auto-start Ollama (if available)
    if shutil.which("ollama"):
        process = subprocess.Popen(["ollama", "serve"], ...)
        server_state.ollama_process = process

    # 3. Cleanup Ollama (unload models from previous sessions)
    loaded_models = await get_ollama_loaded_models()
    for model in loaded_models:
        await ollama_unload(model)

    # 4. Load memory modules via ModuleManager
    loaded = await module_manager.load_memory_modules(config)
    for module_id, instance in loaded.items():
        app.state.modules[module_id] = instance

    # 5. Initialize plugin modules (MLX, LlamaCpp, Ollama, Security, etc.)
    for module_name, instance in app.state.modules.items():
        if hasattr(instance, 'initialize'):
            await instance.initialize({"config": config, "project_root": project_root})

    # 6. Auto-ingest knowledge/ (first run only)
    knowledge_path = project_root / "knowledge"
    ingested_marker = project_root / "storage" / ".knowledge_ingested"
    if not ingested_marker.exists():
        await ingest_knowledge(knowledge_path)
        ingested_marker.touch()

    # 7. Generate bootstrap token (persistent DB)
    token = generate_bootstrap_token()  # Nexe-XXXXXXXXXXXXXXXX (128 bits)
    set_bootstrap_token(token, ttl_minutes=30)
    print(f"Bootstrap Token: {token}")

    logger.info("✅ SERVER.NEXE READY")

    yield  # Server running

    # === SHUTDOWN ===
    logger.info("System shutdown initiated...")

    # Unload Ollama models
    for model in await get_ollama_loaded_models():
        await ollama_unload(model)

    # Stop processes
    if server_state.qdrant_process:
        server_state.qdrant_process.terminate()
    if server_state.ollama_process:
        server_state.ollama_process.terminate()

    logger.info("Nexe 0.8 stopped successfully")
```

**Key features:**
- **Process management**: Starts and stops Qdrant/Ollama binaries
- **Async-aware**: Uses `asyncio.sleep()` instead of `time.sleep()` to avoid blocking the event loop
- **Bootstrap tokens**: High-entropy generation (128 bits) + SQLite persistence
- **Smart auto-ingest**: First run only (marker file)
- **Graceful shutdown**: Proper cleanup of all resources

#### endpoints/

Each endpoint is a FastAPI router:

**Example: endpoints/chat.py**

```python
from fastapi import APIRouter, Depends
from core.models import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter(prefix="/v1", tags=["chat"])

@router.post("/chat/completions")
async def chat_completion(
    request: ChatCompletionRequest,
    backend = Depends(get_backend),
    memory_manager = Depends(get_memory_manager)
):
    # 1. If RAG enabled, query memory
    context = []
    if request.use_rag:
        context = await memory_manager.search(
            query=request.messages[-1].content,
            limit=5
        )

    # 2. Build prompt with context
    prompt = build_prompt(request.messages, context)

    # 3. Generate response with the backend
    response = await backend.generate(
        prompt=prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens
    )

    # 4. Return in OpenAI format
    return ChatCompletionResponse(
        choices=[{"message": {"content": response}}],
        usage={"total_tokens": len(response.split())}
    )
```

#### middleware.py

HTTP middleware for logging, security, etc:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Log request
        logger.info(f"{request.method} {request.url}")

        # Process
        response = await call_next(request)

        # Log response
        logger.info(f"Status: {response.status_code}")

        return response

def setup_middleware(app):
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(CORSMiddleware, ...)
    app.add_middleware(SecurityHeadersMiddleware)
```

#### CLI (cli/)

Command line interface with **Click** and **dynamic router**:

**core/cli/cli.py** (main CLI):
```python
import click
from .router import CLIRouter

class DynamicGroup(click.Group):
    """
    Click Group that intercepts undefined commands and redirects
    them to the router to invoke module CLIs via subprocess.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._router = CLIRouter()

    def get_command(self, ctx: click.Context, cmd_name: str):
        # 1. First looks in registered commands (go, status, modules)
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        # 2. If not found, looks in module CLIs
        cli_info = self._router.get_cli(cmd_name)
        if cli_info is None:
            return None

        # 3. Create dynamic command that delegates to the module CLI
        @click.command(name=cmd_name)
        @click.argument('args', nargs=-1, type=click.UNPROCESSED)
        @click.pass_context
        def dynamic_cmd(ctx, args):
            exit_code = self._router.execute(cmd_name, list(args))
            ctx.exit(exit_code)

        return dynamic_cmd

@click.group(cls=DynamicGroup, invoke_without_command=True)
@click.option('--version', '-V', is_flag=True)
@click.pass_context
def app(ctx, version, no_banner):
    """Nexe CLI Central - Nexe 0.8 Module Orchestrator"""
    if version:
        click.echo("Nexe CLI v1.0.0")
        ctx.exit(0)

@app.command()
@click.pass_context
def go(ctx):
    """Start the full Nexe system (Qdrant + Server)."""
    subprocess.run([sys.executable, "-m", "core.app"], ...)

@app.command()
def modules():
    """List modules with available CLIs."""
    router = CLIRouter()
    clis = router.discover_all()
    print_modules_table(clis)
```

**core/cli/router.py** (dynamic router):
```python
from pathlib import Path
import subprocess

class CLIRouter:
    """
    Router that discovers and executes Nexe module CLIs.

    Strategy:
    1. Discovers via manifest.toml ([module.cli])
    2. Executes via subprocess for isolation
    """
    def discover_all(self) -> List[CLIInfo]:
        # Scans plugins/, memory/, personality/ for manifest.toml
        for manifest_path in quadrant_path.rglob("manifest.toml"):
            cli_data = parse_manifest(manifest_path)
            if cli_data:
                self._cache[cli_data.alias] = cli_data
        return list(self._cache.values())

    def execute(self, alias: str, args: List[str]) -> int:
        """Executes module CLI via subprocess."""
        cli_info = self.get_cli(alias)
        cmd = [sys.executable, "-m", cli_info.entry_point] + args
        result = subprocess.run(cmd, cwd=project_root)
        return result.returncode
```

**Usage examples:**
```bash
./nexe go                  # Start server
./nexe chat                # Dynamic CLI → core.cli.chat_cli
./nexe chat --rag          # Chat with RAG
./nexe memory store "data" # Dynamic CLI → memory.memory.cli
./nexe rag search "query"  # Dynamic CLI → memory.rag.cli
./nexe modules             # List available CLIs
```

**Advantages of the dynamic router:**
- **Automatic discovery**: Scans manifest.toml from all modules
- **Isolation**: Each CLI runs in a separate subprocess
- **Extensible**: Adding a new CLI = adding manifest.toml
- **Not hardcoded**: No need to manually register each CLI

### 2. Module System (NOT plugins/base.py!)

**IMPORTANT**: `plugins/base.py` and `plugins/registry.py` do NOT exist. The real system uses **ModuleManager** in `personality/module_manager/`.

#### ModuleManager (SINGLE SOURCE OF TRUTH)

**personality/module_manager/module_manager.py:**

```python
from personality.data.models import ModuleInfo, ModuleState
from personality.loading.loader import ModuleLoader
from .registry import ModuleRegistry
from .discovery import ModuleDiscovery

class ModuleManager:
    """
    UNIFIED Module Manager for Nexe 0.8 (SINGLE SOURCE OF TRUTH).

    Manages all modules:
    - Plugin modules (plugins/*)
    - Memory modules (memory/*)
    - Core modules (core/*)

    Components:
    - ConfigManager: Configuration + manifests management
    - PathDiscovery: Module path discovery
    - ModuleDiscovery: Discovery logic
    - ModuleLoader: Dynamic loading
    - ModuleRegistry: Registry + indexing
    - ModuleLifecycleManager: Individual lifecycle
    - SystemLifecycleManager: System lifecycle
    """

    def __init__(self, config_path: Path = None):
        self.config_manager = ConfigManager(config_path, i18n)
        self.registry = ModuleRegistry(i18n)
        self.loader = ModuleLoader(i18n)
        self.path_discovery = PathDiscovery(config, i18n)
        self.discovery = ModuleDiscovery(...)
        self.module_lifecycle = ModuleLifecycleManager(...)
        self._modules: Dict[str, ModuleInfo] = {}

    async def discover_modules(self) -> List[str]:
        """Discovers new modules by scanning manifest.toml"""
        return await self.discovery.discover_all()

    async def load_module(self, module_id: str) -> ModuleInfo:
        """Loads a module dynamically"""
        return await self.module_lifecycle.load_module(module_id)

    async def load_memory_modules(self, config: Dict) -> Dict[str, Any]:
        """Loads Memory, RAG, Embeddings (correct order)"""
        loaded = {}
        for module_id in ["memory", "rag", "embeddings"]:
            instance = await self.load_module(module_id)
            loaded[module_id] = instance
        return loaded
```

**Module discovery:**

```python
# personality/module_manager/discovery.py
class ModuleDiscovery:
    def discover_all(self) -> List[str]:
        """Scans plugins/, memory/, personality/ for manifest.toml"""
        discovered = []
        for quadrant in ["plugins", "memory", "personality"]:
            for manifest_path in (base_path / quadrant).rglob("manifest.toml"):
                module_info = self._parse_manifest(manifest_path)
                if module_info:
                    discovered.append(module_info.module_id)
        return discovered

    def _parse_manifest(self, path: Path) -> Optional[ModuleInfo]:
        """Parses manifest.toml (TOML format)"""
        data = tomllib.load(path.open("rb"))
        return ModuleInfo(
            module_id=data["module"]["name"],
            version=data["module"]["version"],
            entry_point=data["module"]["entry"],
            ...
        )
```

**manifest.toml format:**

```toml
# plugins/mlx_module/manifest.toml
[module]
name = "mlx_module"
version = "0.8.0"
type = "local_llm_option"
description = "Motor MLX per Apple Silicon"
location = "plugins/mlx_module/"

[module.entry]
module = "plugins.mlx_module.module"
class = "MLXModule"

[module.router]
prefix = "/mlx"

[module.cli]
command_name = "mlx"
entry_point = "plugins.mlx_module.cli"
```

**ModuleManager advantages:**
- **Unified**: All modules (plugins, memory, core) go through the same system
- **Automatic discovery**: Scans manifest.toml
- **Managed lifecycle**: Initialize, shutdown, health checks
- **Centralized registry**: A single registry for everything
- **NOT hardcoded**: No need to manually register modules

#### Example: MLX Module

**plugins/mlx_module/module.py:**

```python
from typing import Dict, Any, Optional

class MLXModule:
    """
    MLX Module - Inference engine for Apple Silicon.

    Features:
    - Real prefix matching (instant TTFT)
    - Metal optimized (M1/M2/M3/M4)
    - Streaming support
    """

    def __init__(self):
        from .constants import MANIFEST, MODULE_ID
        self.module_id = MODULE_ID
        self.manifest = MANIFEST
        self.name = MANIFEST["name"]
        self.version = MANIFEST["version"]

        self.model = None
        self.tokenizer = None
        self._initialized = False

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """
        Initializes the MLX module.

        Args:
            context: {"config": Dict, "project_root": Path}

        Returns:
            True if initialization is successful
        """
        if self._initialized:
            return True

        config = context.get("config", {})
        model_path = config.get("plugins", {}).get("models", {}).get("primary")

        if model_path:
            from mlx_lm import load
            self.model, self.tokenizer = load(model_path)
            self._initialized = True
            return True

        return False

    async def shutdown(self) -> bool:
        """Module cleanup."""
        if self.model:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
        self._initialized = False
        return True

    def get_health(self) -> Dict[str, Any]:
        """Module health check."""
        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "model_loaded": self.model is not None,
            "version": self.version
        }

    def get_info(self) -> Dict[str, Any]:
        """Module information."""
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": self.manifest.get("description", ""),
            "capabilities": self.manifest.get("capabilities", {}),
        }
```

**plugins/mlx_module/manifest.py** (FastAPI Router):

```python
from fastapi import APIRouter
from .chat import MLXChatNode

router = APIRouter(prefix="/mlx", tags=["mlx"])

@router.get("/health")
async def health():
    """Health check endpoint"""
    module = MLXModule.get_instance()
    return module.get_health()

@router.get("/info")
async def info():
    """Module info endpoint"""
    module = MLXModule.get_instance()
    return module.get_info()

# Router automatically registered via ModuleManager
```

**Advantages of the new structure:**
- **manifest.toml**: Declarative metadata (automatic discovery)
- **module.py**: Module logic (initialize, shutdown, health)
- **manifest.py**: FastAPI router (lazy loaded)
- **Singleton**: Each module is singleton (get_instance())
- **Managed lifecycle**: ModuleManager controls initialize/shutdown

#### Example: Ollama Module (Bridge)

**plugins/ollama_module/module.py:**

```python
import httpx
from typing import Dict, Any

class OllamaModule:
    """
    Ollama Module - HTTP bridge to local Ollama server.

    Features:
    - Async HTTP client to Ollama API
    - Auto-verification of available models
    - Streaming support
    """

    def __init__(self):
        from .constants import MANIFEST, MODULE_ID
        self.module_id = MODULE_ID
        self.manifest = MANIFEST
        self.name = MANIFEST["name"]

        self.base_url = "http://localhost:11434"
        self.client = None
        self.model = None
        self._initialized = False

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initializes Ollama client."""
        config = context.get("config", {})
        model_name = config.get("plugins", {}).get("models", {}).get("primary")

        # Create async HTTP client
        self.client = httpx.AsyncClient(timeout=30.0)

        # Verify Ollama is available
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            models = response.json()["models"]

            if model_name and model_name in [m["name"] for m in models]:
                self.model = model_name
                self._initialized = True
                return True
            else:
                # Model not found, but Ollama is available
                self._initialized = True
                return True

        except Exception as e:
            logger.warning(f"Ollama not available: {e}")
            return False

    async def shutdown(self) -> bool:
        """Client cleanup."""
        if self.client:
            await self.client.aclose()
            self.client = None
        self._initialized = False
        return True

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate via Ollama API."""
        response = await self.client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": kwargs.get("temperature", 0.7),
                    "num_predict": kwargs.get("max_tokens", 512)
                }
            }
        )
        return response.json()["response"]
```

**Ollama Bridge features:**
- **Async HTTP client**: httpx.AsyncClient
- **Auto-verification**: Checks available models at /api/tags
- **Does not load model**: Ollama manages loading internally
- **Lifecycle**: Initialize creates client, shutdown closes client

### 3. Memory (RAG)

**3-sublayer memory system**: Embeddings, Memory, RAG.

#### RAG Architecture (3 layers)

```
┌─────────────────────────────────────────┐
│   RAG Layer (memory/rag/)               │
│   - Orchestration search                │
│   - API /v1/rag/search                  │
│   - RAG sources (personality, files)    │
└─────────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│   Memory Layer (memory/memory/)         │
│   - FlashMemory (cache TTL)             │
│   - RAMContext (session)                │
│   - PersistenceManager (SQLite+Qdrant)  │
│   - API /v1/memory/store|search         │
└─────────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│   Embeddings Layer (memory/embeddings/) │
│   - CachedEmbedder (async batch)        │
│   - VectorStore (Qdrant interface)      │
│   - Chunkers (text, code)               │
└─────────────────────────────────────────┘
```

#### MemoryModule (Singleton)

**memory/memory/module.py:**

```python
from .engines.flash_memory import FlashMemory
from .engines.ram_context import RAMContext
from .engines.persistence import PersistenceManager

class MemoryModule:
    """
    Memory Module - Flash Memory + RAM Context + Persistence.

    Singleton that manages:
    - Flash Memory (temporary result cache)
    - RAM Context (current session context)
    - Persistence (SQLite + Qdrant)
    """

    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """Get Singleton instance (thread-safe)"""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def __init__(self):
        if MemoryModule._instance is not None:
            raise RuntimeError("MemoryModule is Singleton. Use get_instance()")

        self.module_id = "{{NEXE_MEMORY}}"
        self.name = "memory"

        self._flash_memory = None
        self._ram_context = None
        self._persistence = None
        self._pipeline = None

    async def initialize(self, config: Dict[str, Any]) -> bool:
        """Initializes Memory Module."""
        # Setup paths (storage/vectors/)
        vectors_path = project_root / "storage" / "vectors"
        db_path = vectors_path / "metadata_memory.db"
        qdrant_path = vectors_path / "qdrant_local"

        # Initialize engines
        self._flash_memory = FlashMemory(default_ttl_seconds=1800)
        self._ram_context = RAMContext(flash_memory=self._flash_memory)
        self._persistence = PersistenceManager(
            db_path=db_path,
            qdrant_path=qdrant_path,
            collection_name="nexe_memory",
            vector_size=768
        )
        self._pipeline = IngestionPipeline(...)

        # Preload recent entries to RAM
        recent_entries = await self._persistence.get_recent(limit=50)
        for entry in recent_entries:
            await self._flash_memory.store(entry)

        return True

    async def ingest(self, entry: MemoryEntry) -> bool:
        """Ingests entry via pipeline."""
        return await self._pipeline.ingest(entry)
```

**PersistenceManager (SQLite + Qdrant):**

```python
# memory/memory/engines/persistence.py
class PersistenceManager:
    """Dual persistence: SQLite (metadata) + Qdrant (vectors)"""

    def __init__(self, db_path, qdrant_path, collection_name, vector_size):
        self.db_path = db_path
        self.qdrant_client = QdrantClient(path=str(qdrant_path))
        self.collection_name = collection_name

        # Create collection if not exists
        self._ensure_collection(vector_size)

    async def store(self, entry: MemoryEntry):
        """Saves to SQLite + Qdrant."""
        # 1. Save metadata to SQLite
        conn = sqlite3.connect(self.db_path)
        cursor.execute("INSERT INTO memories VALUES (?, ?, ?)", ...)
        conn.commit()

        # 2. Save vector to Qdrant
        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[{
                "id": entry.id,
                "vector": entry.embedding,
                "payload": {"text": entry.text, "metadata": entry.metadata}
            }]
        )

    async def search(self, query_vector, limit, threshold):
        """Vector search in Qdrant."""
        results = self.qdrant_client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=threshold
        )
        return results
```

#### VectorStore (Qdrant Interface)

**memory/embeddings/core/vectorstore.py:**

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from pathlib import Path

class VectorStore:
    """
    Unified interface to Qdrant.

    Features:
    - Local mode (local Qdrant, no server)
    - Auto-create collections
    - Batch operations
    """

    def __init__(self, qdrant_path: Path, collection_name: str, vector_size: int):
        # Local Qdrant (no server needed!)
        self.client = QdrantClient(path=str(qdrant_path))
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._ensure_collection()

    def _ensure_collection(self):
        """Create collection if it does not exist"""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,  # 768 per paraphrase-multilingual
                    distance=Distance.COSINE
                )
            )

    def upsert_batch(self, points: list[PointStruct]):
        """Insert multiple vectors (batch)"""
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(self, query_vector: list[float], limit: int, threshold: float):
        """Vector search (similarity search)"""
        return self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=threshold
        )
```

#### Embeddings (Cached + Async)

**memory/embeddings/core/cached_embedder.py:**

```python
from sentence_transformers import SentenceTransformer
from functools import lru_cache

class CachedEmbedder:
    """
    Embedding model with cache and batch support.

    Features:
    - LRU cache (avoids re-encoding the same text)
    - Async batch encoding
    - Multiple models (paraphrase-multilingual, all-MiniLM)
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    @lru_cache(maxsize=1024)
    def _encode_cached(self, text: str) -> tuple:
        """Encode with cache (tuple for hashable)"""
        embedding = self.model.encode(text, convert_to_tensor=False)
        return tuple(embedding.tolist())

    async def encode(self, text: str) -> list[float]:
        """Encode single text (async wrapper)"""
        result = self._encode_cached(text.strip())
        return list(result)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode batch (more efficient than multiple calls)"""
        # Normalize texts
        texts_clean = [t.strip() for t in texts]

        # Batch encode (NO cache here, too large)
        embeddings = self.model.encode(texts_clean, convert_to_tensor=False)
        return embeddings.tolist()
```

**Chunkers (Text + Code):**

```python
# memory/embeddings/chunkers/text_chunker.py
class TextChunker:
    """Semantic text chunking (preserves sentences)"""

    def chunk(self, text: str, max_size: int = 512) -> list[str]:
        """Split text into semantic chunks"""
        sentences = self._split_sentences(text)
        chunks = []
        current_chunk = []
        current_size = 0

        for sentence in sentences:
            if current_size + len(sentence) > max_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_size = len(sentence)
            else:
                current_chunk.append(sentence)
                current_size += len(sentence)

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

# memory/embeddings/chunkers/code_chunker.py
class CodeChunker:
    """Code-aware chunking (preserves functions/classes)"""

    def chunk(self, code: str, language: str) -> list[str]:
        """Split code preserving structure"""
        # Detect functions/classes
        blocks = self._parse_code_blocks(code, language)
        return [block.content for block in blocks]
```

---

## Data flow

### Chat flow without RAG

```
1. User → ./nexe chat
          ↓
2. CLI → POST /v1/chat/completions
          ↓
3. Endpoint → Get backend plugin
          ↓
4. Backend (MLX/llama.cpp/Ollama) → Generate
          ↓
5. Response → Format OpenAI
          ↓
6. CLI ← Display response
```

### Chat flow with RAG

```
1. User → ./nexe chat --rag
          ↓
2. CLI → POST /v1/chat/completions (use_rag=true)
          ↓
3. Endpoint → MemoryManager.search(query)
          ↓
4. MemoryManager → Generate embedding
          ↓
5. VectorStore (Qdrant) → Search similar vectors
          ↓
6. Endpoint ← Top-K results
          ↓
7. Endpoint → Build prompt with context
          ↓
8. Backend → Generate with augmented context
          ↓
9. Response → Format OpenAI
          ↓
10. CLI ← Display response
```

### Memory save flow

```
1. User → ./nexe memory store "text"
          ↓
2. CLI → POST /memory/store
          ↓
3. Endpoint → MemoryManager.store(text)
          ↓
4. MemoryManager → Generate embedding
          ↓
5. VectorStore → Insert vector + payload
          ↓
6. Qdrant → Persist to disk
          ↓
7. CLI ← Confirmation (ID)
```

---

## Architectural decisions

### Why FastAPI?

- **Native async:** Ideal for I/O with Qdrant, models
- **Type hints:** Automatic validation with Pydantic
- **OpenAPI:** Automatic documentation
- **Performance:** Very fast (based on Starlette + Uvicorn)
- **Ecosystem:** Large Python community

### Why Qdrant?

- **Performance:** Very fast for vector search
- **Embedded mode:** Can run without external server
- **Persistence:** Saves data to disk
- **HNSW index:** Efficient algorithm for ANN search
- **Filtering:** Allows filtering by metadata

**Alternatives considered:**
- FAISS: More complex, fewer features
- Chroma: Too "heavy" for a local project
- Milvus: Overkill for a small project

### Why a plugin system?

- **Flexibility:** Add backends without modifying the core
- **Testability:** Each plugin can be tested in isolation
- **Maintainability:** Changes in one plugin do not affect others
- **Extensibility:** Easy to add functionalities (new plugins, backends, etc.)

### Why sentence-transformers?

- **Size:** Small models (~90MB)
- **Quality:** Good embeddings for semantic search
- **Offline:** Does not require external API
- **Multilingual:** Works well in Catalan with all-MiniLM-L6-v2

**Future alternative:**
- Use embeddings from the LLM itself (if possible)

---

## Performance considerations

### Identified bottlenecks

1. **LLM generation:** The slowest (depending on model)
   - Solution: Use small models or GPU

2. **Embeddings:** Can be slow with many documents
   - Solution: Batch processing, cache

3. **Vector search:** Fast with Qdrant HNSW
   - Not a current bottleneck

### Applied optimizations

- **Lazy loading:** Models are loaded only when needed
- **Connection pooling:** Reuse connections to Qdrant
- **Async everywhere:** Do not block the event loop
- **Batch embeddings:** Generate multiple embeddings at once

### Memory usage

**Components:**
- LLM model: 2-40 GB depending on model
- Qdrant: ~100-500 MB depending on documents
- Embedding model: ~90 MB
- FastAPI + Python: ~100-200 MB
- **Total:** Variable depending on configuration

---

## Security

### Security layers (Multi-layer)

#### 1. API Key Authentication (Dual-key support)

**Supported header:** `X-API-Key` (NOT Bearer token!)

**Configuration (environment variables):**

```bash
# Dual-key rotation support
export NEXE_PRIMARY_API_KEY="new-key-2026"
export NEXE_PRIMARY_KEY_EXPIRES="2026-06-30T00:00:00Z"  # ISO 8601
export NEXE_SECONDARY_API_KEY="old-key-2025"
export NEXE_SECONDARY_KEY_EXPIRES="2026-01-31T00:00:00Z"

# Backward compatibility (single key)
export NEXE_ADMIN_API_KEY="single-key"

# Development mode (optional, dev only)
export NEXE_ENV="development"  # Bypasses auth in dev
```

**Implementation:**

```python
# plugins/security/core/auth_dependencies.py
async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None)
) -> str:
    """
    FastAPI Dependency to validate API key.

    - Fail-closed: If not dev mode, API key is required
    - Dual-key: Accepts primary OR secondary
    - Expiry check: Validates expiry dates
    - Metrics: Prometheus metrics for auth attempts
    """
    keys_config = load_api_keys()

    # Dev mode bypass (ONLY in NEXE_ENV=development)
    if is_dev_mode():
        return "dev-bypass"

    # Validate key
    if not x_api_key:
        raise HTTPException(401, "API key required (X-API-Key header)")

    # Check primary key
    if keys_config.primary and keys_config.primary.is_valid:
        if secrets.compare_digest(x_api_key, keys_config.primary.key):
            record_auth_attempt("primary", "success")
            return x_api_key

    # Check secondary key (rotation grace period)
    if keys_config.secondary and keys_config.secondary.is_valid:
        if secrets.compare_digest(x_api_key, keys_config.secondary.key):
            record_auth_attempt("secondary", "success")
            return x_api_key

    # Key invalid
    record_auth_failure("invalid_key")
    raise HTTPException(401, "Invalid API key")
```

**Usage in endpoints:**

```python
from fastapi import Depends
from plugins.security.core.auth_dependencies import require_api_key

@router.post("/admin/system/restart")
async def restart(api_key: str = Depends(require_api_key)):
    """Protected endpoint (requires valid API key)"""
    return {"status": "restarting"}
```

#### 2. Rate Limiting (Advanced)

**Available limiters:**

```python
# core/dependencies.py
from slowapi import Limiter
from slowapi.util import get_remote_address, get_api_key

limiter_global = Limiter(key_func=get_remote_address)     # Per IP
limiter_by_key = Limiter(key_func=get_api_key)            # Per API key
limiter_composite = Limiter(key_func=composite_key_func)  # IP + key
limiter_by_endpoint = Limiter(key_func=endpoint_key_func) # Endpoint-specific
```

**Usage examples:**

```python
# Rate limit per IP
@router.post("/bootstrap/init")
@limiter_global.limit("3/5minute")  # 3 attempts per 5 min per IP
@limiter_global.limit("10/5minute", key_func=lambda: "global")  # 10 global
async def bootstrap_init(token: str):
    ...

# Rate limit per endpoint
@router.post("/security/scan")
@limiter_by_endpoint.limit("2/minute")
async def security_scan():
    ...
```

**Response headers:**

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 8
X-RateLimit-Reset: 1738684800  # Unix timestamp
```

#### 3. Input Validation & Sanitization

**RAG Content Sanitization:**

```python
# core/endpoints/chat.py
_RAG_INJECTION_PATTERNS = [
    r'\[/?INST\]',                    # Instruction markers
    r'<\|/?system\|>',                # System role markers
    r'###\s*(system|user|assistant)', # Role headers
]

def sanitize_rag_content(text: str) -> str:
    """Remove prompt injection patterns from RAG context"""
    for pattern in _RAG_INJECTION_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    return text[:MAX_RAG_CONTEXT_LENGTH]  # 4000 chars max
```

**Path Traversal Protection:**

```python
# plugins/security/core/validators.py
def validate_safe_path(requested_path: Path, base_path: Path) -> Path:
    """
    Validate path is within base_path (no ../../../etc/passwd).

    Raises:
        ValueError: If path traversal detected
    """
    resolved = requested_path.resolve()
    if not str(resolved).startswith(str(base_path.resolve())):
        raise ValueError(f"Path traversal detected: {requested_path}")
    return resolved
```

#### 4. CSRF Protection

**Middleware:** `starlette-csrf`

```python
# core/middleware.py
from starlette_wtf import CSRFProtectMiddleware

app.add_middleware(
    CSRFProtectMiddleware,
    secret=os.getenv("NEXE_CSRF_SECRET", secrets.token_hex(32)),
    cookie_name="nexe_csrf_token",
    cookie_secure=True,  # HTTPS only (prod)
    cookie_samesite="strict",
    exempt_urls=[
        r"/v1/.*",      # API endpoints (stateless)
        r"/health",
        r"/metrics",
    ]
)
```

#### 5. CORS (Strict)

**Does NOT allow wildcards (*):**

```python
# core/middleware.py
cors_origins = config.get("cors_origins", ["http://localhost:3000"])

# SECURITY FIX: Reject wildcard (CVE-like)
if "*" in cors_origins:
    raise ValueError("CORS wildcard (*) not allowed. Use explicit origins.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,  # Explicit list only
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    allow_credentials=True,
)
```

#### 6. Security Headers (OWASP)

```python
# core/security_headers.py
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "  # Web UI needs inline CSS
        "img-src 'self' data:; "
        "font-src 'self' data:;"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), "
        "payment=(), usb=(), magnetometer=()"
    ),
}
```

#### 7. Request Size Limiting (DoS Protection)

```python
# core/request_size_limiter.py
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE_MB", "100")) * 1024 * 1024

class RequestSizeLimiterMiddleware:
    async def __call__(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE:
            return JSONResponse(
                {"error": "Request too large (max 100MB)"},
                status_code=413
            )
        return await call_next(request)
```

#### 8. Security Logger (SIEM)

```python
# plugins/security_logger/logger.py
class SecurityEventLogger:
    """Logs security events to storage/system-logs/security/"""

    def log_auth_attempt(self, ip: str, success: bool, key_type: str):
        ...

    def log_rate_limit(self, ip: str, endpoint: str):
        ...

    def log_injection_attempt(self, ip: str, pattern: str, content: str):
        ...

    def log_path_traversal(self, ip: str, path: str):
        ...
```

**Log format (JSON):**

```json
{
  "timestamp": "2026-02-04T12:34:56Z",
  "event_type": "auth_failure",
  "ip": "192.168.1.100",
  "details": {"reason": "invalid_key", "endpoint": "/admin/system/restart"}
}
```

### Mitigated threats

✅ **Prompt injection**: RAG content sanitization, detected patterns
✅ **Path traversal**: validate_safe_path() on all file operations
✅ **DoS**: Request size limit 100MB, rate limiting
✅ **CSRF**: starlette-csrf middleware
✅ **XSS**: CSP headers, no unsafe-inline for scripts
✅ **Brute force**: Rate limiting (3 attempts/5min per IP)

### Residual threats

⚠️ **Advanced prompt injection**: LLMs can be tricked with sophisticated prompts
⚠️ **Model extraction**: If public API, possible extraction attacks
⚠️ **Side-channel timing**: API keys use secrets.compare_digest() but other vectors are possible

---

## Testing

### Testing strategy

```
server-nexe/
├── tests/
│   ├── unit/                  # Unit tests
│   │   ├── test_memory.py
│   │   ├── test_embeddings.py
│   │   └── test_plugins.py
│   │
│   ├── integration/           # Integration tests
│   │   ├── test_api.py
│   │   └── test_rag_flow.py
│   │
│   └── e2e/                   # End-to-end tests
│       └── test_full_flow.py
│
├── conftest.py                # pytest fixtures
└── pytest.ini                 # pytest config
```

**Run tests:**
```bash
pytest tests/
```

---

## Logging

### Log levels

- **DEBUG:** Everything (verbose)
- **INFO:** Important events
- **WARNING:** Unexpected but non-critical things
- **ERROR:** Errors requiring attention
- **CRITICAL:** System inoperative

### Configuration

In the `.env` file:
```
LOG_LEVEL=INFO
LOG_FILE=logs/nexe.log
```

### View logs

```bash
# In real time
tail -f logs/nexe.log

# Last 100 lines
tail -n 100 logs/nexe.log

# Filter errors
grep ERROR logs/nexe.log
```

---

## Monitoring

### Available metrics

- **Requests:** Total, per endpoint, errors
- **Latency:** P50, P95, P99 per endpoint
- **Model:** Generated tokens, inference time
- **Memory:** RAM used, vectors in Qdrant
- **System:** CPU, disk, uptime

### Metrics endpoints

**Prometheus (text format):**
```bash
curl http://localhost:9119/metrics
```

**Response (Prometheus format):**
```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="POST",endpoint="/v1/chat/completions"} 1523

# HELP http_request_duration_seconds HTTP request latency
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.1"} 450
http_request_duration_seconds_bucket{le="0.5"} 1200
http_request_duration_seconds_bucket{le="1.0"} 1500

# HELP auth_attempts_total Authentication attempts
# TYPE auth_attempts_total counter
auth_attempts_total{key_type="primary",result="success"} 234
auth_attempts_total{key_type="primary",result="failure"} 12

# HELP memory_vectors_total Total vectors in Qdrant
# TYPE memory_vectors_total gauge
memory_vectors_total{collection="user_knowledge"} 342
```

**JSON summary (human-friendly):**
```bash
curl http://localhost:9119/metrics/json
```

**Response (JSON):**
```json
{
  "system": {
    "uptime_seconds": 86400,
    "memory_used_mb": 2048,
    "cpu_percent": 15.4
  },
  "http": {
    "requests_total": 1523,
    "requests_errors": 12,
    "latency_p50_ms": 245,
    "latency_p95_ms": 1820,
    "latency_p99_ms": 3200
  },
  "auth": {
    "attempts_total": 246,
    "failures_total": 12,
    "primary_key_valid": true,
    "secondary_key_valid": true
  },
  "memory": {
    "vectors_total": 342,
    "collections": ["user_knowledge", "nexe_memory"]
  },
  "models": {
    "tokens_generated": 45230,
    "inference_count": 856
  }
}
```

---

## Scalability

### Current limits

- **Single instance:** Not distributed
- **Single model:** One active model at a time
- **Local only:** No replication

### Future improvements (hypothetical)

- **Model switching:** Change models without restarting
- **Multiple backends:** Multiple simultaneous models
- **Distributed Qdrant:** Cluster for more data
- **Load balancing:** Multiple NEXE instances

But... **this is a local and educational project**, no need for over-engineering.

---

## Next steps

To go deeper:

1. **RAG.md** - Memory system details
2. **PLUGINS.md** - How to create plugins
3. **API.md** - Complete API reference
4. **LIMITATIONS.md** - Technical limitations

---

## Document updates

**Update date:** 2026-02-04
**Version:** 0.8.1 (updated to reflect actual code)

### Main changes vs previous version:

1. **Updated directory structure**
   - Added: `core/bootstrap_tokens.py`, `plugins/security_logger/`, `personality/module_manager/`
   - Corrected paths: `storage/` instead of `snapshots/`, `storage/vectors/` for DBs
   - Added `memory/` sublayer with 3 layers (embeddings, memory, rag)

2. **Factory Pattern documented**
   - `core/server/factory.py` as real factory (singleton cached)
   - Performance: 0.58s → <10ms on subsequent calls
   - Factory submodules: factory_app, factory_state, factory_modules, etc.

3. **Complex lifespan.py**
   - Process manager (starts Qdrant, Ollama binaries)
   - Bootstrap tokens (generation + DB persistence)
   - Auto-ingest knowledge/ (first run)
   - 635 lines vs previous simplified example

4. **CLI with Click (NOT Typer)**
   - DynamicGroup + CLIRouter for automatic discovery
   - Subprocesses for isolation
   - Discovery via manifest.toml

5. **ModuleManager (NOT BasePlugin/registry)**
   - SINGLE SOURCE OF TRUTH in `personality/module_manager/`
   - `plugins/base.py` and `plugins/registry.py` do NOT exist
   - Discovery via manifest.toml (TOML format)
   - Managed lifecycle: initialize, shutdown, health

6. **Memory system in 3 layers**
   - Embeddings Layer: vectorstore, cached embedder, chunkers
   - Memory Layer: FlashMemory, RAMContext, PersistenceManager
   - RAG Layer: orchestration, RAG sources

7. **Detailed security**
   - X-API-Key header (NOT Bearer token)
   - Dual-key support (PRIMARY + SECONDARY)
   - CSRF protection (starlette-csrf)
   - RAG sanitization (prompt injection patterns)
   - Security Logger (SIEM logs)
   - Path traversal protection

8. **Corrected endpoints**
   - `/api/info` (NOT `/info`)
   - `/admin/system/*` (NOT `/system/*`)
   - `/v1/memory/store` (NOT `/memory/store`)
   - `/bootstrap/init`, `/bootstrap/info` (new)

9. **Prometheus metrics**
   - `/metrics` → Prometheus text format
   - `/metrics/json` → JSON summary

### Corrected discrepancies:

| Previous aspect | Code reality |
|-----------------|--------------|
| CLI with Typer | CLI with Click + DynamicGroup |
| plugins/base.py, plugins/registry.py | personality/module_manager/module_manager.py |
| memory/manager.py | memory/memory/module.py (3 sublayers) |
| Qdrant snapshots/ | storage/qdrant/ |
| API key Bearer token | X-API-Key header |
| Single API key | Dual-key (PRIMARY + SECONDARY) |
| /info, /system/* | /api/info, /admin/system/* |
| Simplified lifespan | Lifespan 635 lines (process manager) |

---

**Note:** This architecture is v0.8. It may evolve in future versions.

**Philosophy:** Simplicity > Complexity. Do not add unnecessary layers.

**Maintenance:** Document updated to reflect actual code. If you find discrepancies, report them to the team.
