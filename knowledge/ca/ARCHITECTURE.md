# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-architecture

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Visió general de l'arquitectura interna de NEXE 0.8. Tres capes: Interfaces → Core → Plugins → Serveis Base. Cobreix Factory Pattern, lifespan manager, sistema de memòria en 3 capes, CLI i decisions de disseny."
tags: [arquitectura, fastapi, plugins, qdrant, memory, lifespan, cli, disseny]
chunk_size: 1500
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Arquitectura - NEXE 0.8

> **📝 Document actualitzat:** 2026-02-04
> **⚠️ IMPORTANT:** Aquest document ha estat revisat i actualitzat per reflectir el **codi real** de Nexe 0.8.
> Les versions anteriors contenien descripcions simplificades o obsoletes. Aquesta versió és **precisa i honesta** amb la implementació actual.

Aquesta documentació explica com està construït NEXE internament. És útil si vols:
- Entendre com funciona el sistema
- Contribuir al projecte
- Crear plugins o extensions
- Debugar problemes
- Aprendre sobre arquitectura de sistemes d'IA

## Visió general

NEXE està dissenyat amb una **arquitectura modular en tres capes**:

```
┌─────────────────────────────────────────────────────┐
│                    INTERFÍCIES                      │
│  CLI (./nexe) │ API REST │ Web UI                  │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                       CORE                          │
│  Servidor │ Endpoints │ Middleware │ Lifespan      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                     PLUGINS                         │
│  MLX │ llama.cpp │ Ollama │ Security │ Web UI      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                   SERVEIS BASE                      │
│  Memory (RAG) │ Qdrant │ Embeddings │ SQLite       │
└─────────────────────────────────────────────────────┘
```

### Principis de disseny

1. **Modularitat:** Components desacoblats i intercanviables
2. **Plugin-based:** Els backends són plugins que es carreguen dinàmicament
3. **API-first:** Tot accessible via API REST
4. **RAG natiu:** La memòria és de primera classe, no un afegit
5. **Simplicitat:** Codi llegible, evitar sobre-enginyeria

---

## Estructura de directoris

```
server-nexe/
├── core/                      # Nucli del sistema
│   ├── __init__.py
│   ├── app.py                 # Entry point FastAPI
│   ├── config.py              # Configuració global (TOML + .env)
│   ├── container.py           # Dependency injection container
│   ├── dependencies.py        # FastAPI dependencies (rate limiting)
│   ├── lifespan.py            # Gestió cicle vida (arrenca Qdrant/Ollama)
│   ├── middleware.py          # Middleware HTTP (CORS, CSRF, logging)
│   ├── models.py              # Models Pydantic
│   ├── resources.py           # Gestió de recursos
│   ├── security_headers.py    # Headers seguretat OWASP
│   ├── utils.py               # Utilitats generals
│   ├── bootstrap_tokens.py    # Sistema tokens bootstrap (DB persist)
│   ├── request_size_limiter.py # Protecció DoS (100MB limit)
│   │
│   ├── cli/                   # Interfície línia comandes (Click)
│   │   ├── __init__.py
│   │   ├── cli.py             # CLI principal (Click + DynamicGroup)
│   │   ├── router.py          # Router dinàmic (descobreix CLIs mòduls)
│   │   ├── chat_cli.py        # Comanda chat interactiu
│   │   ├── log_viewer.py      # Veure logs en temps real
│   │   ├── output.py          # Formatació sortida CLI
│   │   └── client.py          # Client HTTP per API local
│   │
│   ├── endpoints/             # API REST endpoints
│   │   ├── __init__.py
│   │   ├── chat.py            # POST /v1/chat/completions (RAG + streaming)
│   │   ├── root.py            # GET /, /health, /api/info
│   │   ├── system.py          # POST /admin/system/* (restart, status)
│   │   ├── modules.py         # GET /modules (info mòduls carregats)
│   │   ├── bootstrap.py       # POST /bootstrap/init, GET /bootstrap/info
│   │   └── v1.py              # Wrapper endpoints v1
│   │
│   ├── server/                # Factory pattern (singleton cached)
│   │   ├── __init__.py
│   │   ├── factory.py         # Façade principal create_app()
│   │   ├── factory_app.py     # Crear instància FastAPI
│   │   ├── factory_state.py   # Setup app.state
│   │   ├── factory_security.py # SecurityLogger, validació prod
│   │   ├── factory_i18n.py    # I18n + config setup
│   │   ├── factory_modules.py # Descobriment i càrrega mòduls
│   │   ├── factory_routers.py # Registre routers core
│   │   ├── runner.py          # Uvicorn server runner
│   │   └── helpers.py         # Utilitats factory
│   │
│   ├── loader/                # Càrrega dinàmica mòduls
│   │   ├── __init__.py
│   │   └── module_loader.py   # Loader de mòduls Python
│   │
│   ├── metrics/               # Mètriques Prometheus
│   │   ├── __init__.py
│   │   ├── endpoint.py        # /metrics, /metrics/json
│   │   ├── collector.py       # Col·lector mètriques
│   │   └── registry.py        # Registry Prometheus
│   │
│   ├── ingest/                # Ingestió documents knowledge/
│   │   ├── __init__.py
│   │   └── ingest_knowledge.py # Auto-ingest .md, .txt, .pdf
│   │
│   ├── paths/                 # Gestió paths projecte
│   │   ├── __init__.py
│   │   └── path_resolver.py
│   │
│   └── resilience/            # Resiliència (retry, timeout)
│       ├── __init__.py
│       └── retry.py
│
├── plugins/                   # Mòduls de plugins (sense base.py/registry.py)
│   ├── __init__.py
│   │
│   ├── mlx_module/            # Backend MLX (Apple Silicon)
│   │   ├── __init__.py
│   │   ├── manifest.toml      # Metadata mòdul (v0.8 format)
│   │   ├── module.py          # MLXModule class
│   │   ├── chat.py            # MLXChatNode (workflow)
│   │   ├── config.py          # MLXConfig (Metal detection)
│   │   └── manifest.py        # Lazy loader + router FastAPI
│   │
│   ├── llama_cpp_module/      # Backend llama.cpp
│   │   ├── __init__.py
│   │   ├── manifest.toml
│   │   ├── module.py          # LlamaCppModule
│   │   └── manifest.py
│   │
│   ├── ollama_module/         # Backend Ollama (bridge HTTP)
│   │   ├── __init__.py
│   │   ├── manifest.toml
│   │   ├── module.py          # OllamaModule
│   │   ├── client.py          # AsyncHTTP client a Ollama
│   │   └── manifest.py
│   │
│   ├── security/              # Plugin seguretat complet
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
├── memory/                    # Sistema RAG (3 subcapes)
│   ├── __init__.py
│   │
│   ├── embeddings/            # Subcapa: Generació vectors
│   │   ├── __init__.py
│   │   ├── module.py          # EmbeddingsModule (singleton)
│   │   ├── manifest.toml
│   │   ├── core/              # Core embedding logic
│   │   │   ├── vectorstore.py     # Interface Qdrant
│   │   │   ├── cached_embedder.py # Cache + async encoder
│   │   │   ├── async_encoder.py   # Batch encoding
│   │   │   └── chunker.py         # Split text/code
│   │   ├── chunkers/          # Chunking strategies
│   │   │   ├── text_chunker.py    # Semantic chunks
│   │   │   └── code_chunker.py    # Code-aware chunks
│   │   └── api/               # REST API
│   │       └── v1.py              # POST /v1/embeddings (501)
│   │
│   ├── memory/                # Subcapa: Memory management
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
│   ├── rag/                   # Subcapa: RAG orchestration
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
├── personality/               # Personalitat i configuració sistema
│   ├── __init__.py
│   ├── server.toml            # Configuració principal (TOML)
│   ├── integration.py         # APIIntegrator
│   │
│   ├── i18n/                  # Internacionalització
│   │   ├── i18n_manager.py
│   │   └── translations/      # ca.json, en.json, es.json
│   │
│   ├── module_manager/        # SINGLE SOURCE OF TRUTH per mòduls
│   │   ├── module_manager.py  # ModuleManager façade
│   │   ├── registry.py        # ModuleRegistry
│   │   ├── discovery.py       # Module discovery
│   │   ├── path_discovery.py  # Path resolution
│   │   ├── config_manager.py  # Config + manifests
│   │   ├── module_lifecycle.py # Lifecycle individual
│   │   └── system_lifecycle.py # System lifecycle
│   │
│   ├── models/                # Model selection system
│   │   ├── selector.py        # Hardware detection + recomanacions
│   │   └── registry.py        # Verified models registry
│   │
│   ├── events/                # Event system
│   │   └── event_system.py
│   │
│   └── metrics/               # Metrics collector
│       └── metrics_collector.py
│
├── knowledge/                 # Documents auto-ingestats (RAG)
│   ├── ARCHITECTURE.md        # (aquest document)
│   ├── SECURITY.md
│   ├── API.md
│   └── ...                    # Ingestat automàticament a Qdrant
│
├── storage/                   # Persistència (NO al git)
│   ├── qdrant/                # Qdrant local storage
│   ├── vectors/               # Vector DBs
│   │   ├── qdrant_local/
│   │   └── metadata_memory.db # SQLite metadata
│   ├── models/                # Models LLM descarregats
│   ├── system-logs/           # Security logs (SIEM)
│   │   └── security/
│   └── .knowledge_ingested    # Marker file (auto-ingest)
│
├── dev-tools/                 # Eines desenvolupament
│   └── ...
│
├── nexe                       # Executable CLI (#!/usr/bin/env bash)
├── qdrant                     # Binari Qdrant (auto-descarregat)
├── requirements.txt           # Dependències Python
├── install_nexe.py            # Instal·lador automàtic
├── setup.sh                   # Setup script
├── conftest.py                # Configuració pytest
└── pytest.ini                 # Config pytest
```

---

## Components principals

### 1. Core

El nucli del sistema, basat en **FastAPI**.

#### app.py + Factory Pattern

**IMPORTANT**: L'app NO es crea directament a app.py. S'usa un **factory pattern** amb **singleton cached**:

**core/app.py** (entry point):
```python
"""Entry point - delegates to factory"""
from core.server.factory import create_app

app = create_app()  # Singleton cached (0.58s → <0.01s)
```

**core/server/factory.py** (factory real):
```python
from pathlib import Path
from fastapi import FastAPI
import threading

_app_instance: Optional[FastAPI] = None
_app_lock = threading.Lock()

def create_app(project_root: Optional[Path] = None, force_reload: bool = False) -> FastAPI:
    """
    Application factory - Singleton cached amb double-check locking.

    Rendiment:
    - First call (cold): ~0.5-0.6s (i18n, config, module discovery)
    - Cached calls (warm): <0.01s (retorna instància existent)
    """
    global _app_instance

    # Double-check locking pattern
    if _app_instance is not None and not force_reload:
        return _app_instance

    with _app_lock:
        if _app_instance is not None and not force_reload:
            return _app_instance

        # Crear app via submòduls factory
        i18n, config, module_manager = setup_i18n_and_config(project_root)
        app = create_fastapi_instance(i18n, config)
        setup_app_state(app, i18n, config, project_root, module_manager)
        setup_security_logger(app, project_root, i18n)
        discover_and_load_modules(app, module_manager, project_root, i18n)
        register_core_routers(app, i18n)

        _app_instance = app
        return app
```

**Avantatges del Factory Pattern:**
- **Performance**: Singleton cache evita rebuild (0.58s → 10ms)
- **Thread-safe**: Double-check locking pattern
- **Testable**: `reset_app_cache()` per tests
- **Modular**: Separat en factory_app.py, factory_state.py, factory_modules.py, etc.

#### lifespan.py

**Gestor complex de cicle de vida** (~635 línies) que s'encarrega de:

1. **Auto-start serveis externs** (Qdrant, Ollama)
2. **Inicialització mòduls** (Memory, RAG, Embeddings, plugins)
3. **Bootstrap tokens** (generació + persistència DB)
4. **Auto-ingest knowledge/** (primera execució)
5. **Cleanup Ollama** (unload models de RAM)
6. **Graceful shutdown**

**Exemple simplificat:**

```python
from contextlib import asynccontextmanager
import subprocess
from pathlib import Path

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    logger.info("LIFESPAN STARTUP TRIGGERED")

    # 1. Auto-start Qdrant (binari local, NO Docker)
    qdrant_bin = project_root / "qdrant"
    if qdrant_bin.exists():
        process = subprocess.Popen([str(qdrant_bin), "--disable-telemetry"], ...)
        server_state.qdrant_process = process
        # Wait for Qdrant ready (asyncio.sleep, no time.sleep!)
        for i in range(30):
            await asyncio.sleep(0.5)
            if await check_qdrant_health():
                break

    # 2. Auto-start Ollama (si disponible)
    if shutil.which("ollama"):
        process = subprocess.Popen(["ollama", "serve"], ...)
        server_state.ollama_process = process

    # 3. Cleanup Ollama (unload models de sessions prèvies)
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

    # 6. Auto-ingest knowledge/ (només primera execució)
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

    yield  # Servidor funcionant

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

**Característiques clau:**
- **Gestió de processos**: Arrenca i atura binaris Qdrant/Ollama
- **Async-aware**: Usa `asyncio.sleep()` en comptes de `time.sleep()` per no bloquejar event loop
- **Bootstrap tokens**: Generació alta entropia (128 bits) + persistència SQLite
- **Auto-ingest intel·ligent**: Només primera execució (marker file)
- **Graceful shutdown**: Cleanup adequat de tots els recursos

#### endpoints/

Cada endpoint és un router de FastAPI:

**Exemple: endpoints/chat.py**

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
    # 1. Si RAG activat, consultar memòria
    context = []
    if request.use_rag:
        context = await memory_manager.search(
            query=request.messages[-1].content,
            limit=5
        )

    # 2. Construir prompt amb context
    prompt = build_prompt(request.messages, context)

    # 3. Generar resposta amb el backend
    response = await backend.generate(
        prompt=prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens
    )

    # 4. Retornar en format OpenAI
    return ChatCompletionResponse(
        choices=[{"message": {"content": response}}],
        usage={"total_tokens": len(response.split())}
    )
```

#### middleware.py

Middleware HTTP per logging, seguretat, etc:

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

Interfície de línia de comandes amb **Click** i **router dinàmic**:

**core/cli/cli.py** (CLI principal):
```python
import click
from .router import CLIRouter

class DynamicGroup(click.Group):
    """
    Click Group que intercepta comandos no definits i els redirigeix
    al router per invocar CLIs de mòduls via subprocess.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._router = CLIRouter()

    def get_command(self, ctx: click.Context, cmd_name: str):
        # 1. Primer busca en comandos registrats (go, status, modules)
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        # 2. Si no el troba, busca en CLIs de mòduls
        cli_info = self._router.get_cli(cmd_name)
        if cli_info is None:
            return None

        # 3. Crear comando dinàmic que delega al CLI del mòdul
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
    """Arrencar el sistema Nexe complet (Qdrant + Servidor)."""
    subprocess.run([sys.executable, "-m", "core.app"], ...)

@app.command()
def modules():
    """Llistar mòduls amb CLI disponibles."""
    router = CLIRouter()
    clis = router.discover_all()
    print_modules_table(clis)
```

**core/cli/router.py** (Router dinàmic):
```python
from pathlib import Path
import subprocess

class CLIRouter:
    """
    Router que descobreix i executa CLIs de mòduls Nexe.

    Estratègia:
    1. Descobreix via manifest.toml ([module.cli])
    2. Executa via subprocess per aïllament
    """
    def discover_all(self) -> List[CLIInfo]:
        # Escaneja plugins/, memory/, personality/ per manifest.toml
        for manifest_path in quadrant_path.rglob("manifest.toml"):
            cli_data = parse_manifest(manifest_path)
            if cli_data:
                self._cache[cli_data.alias] = cli_data
        return list(self._cache.values())

    def execute(self, alias: str, args: List[str]) -> int:
        """Executa CLI de mòdul via subprocess."""
        cli_info = self.get_cli(alias)
        cmd = [sys.executable, "-m", cli_info.entry_point] + args
        result = subprocess.run(cmd, cwd=project_root)
        return result.returncode
```

**Exemples d'ús:**
```bash
./nexe go                  # Arrenca servidor
./nexe chat                # CLI dinàmic → core.cli.chat_cli
./nexe chat --rag          # Chat amb RAG
./nexe memory store "data" # CLI dinàmic → memory.memory.cli
./nexe rag search "query"  # CLI dinàmic → memory.rag.cli
./nexe modules             # Llista CLIs disponibles
```

**Avantatges del router dinàmic:**
- **Descobriment automàtic**: Escaneja manifest.toml de tots els mòduls
- **Aïllament**: Cada CLI corre en subprocess separat
- **Extensible**: Afegir nou CLI = afegir manifest.toml
- **No hardcoded**: No cal registrar manualment cada CLI

### 2. Sistema de Mòduls (NO plugins/base.py!)

**IMPORTANT**: NO existeix `plugins/base.py` ni `plugins/registry.py`. El sistema real usa **ModuleManager** a `personality/module_manager/`.

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

    Gestiona tots els mòduls:
    - Plugin modules (plugins/*)
    - Memory modules (memory/*)
    - Core modules (core/*)

    Components:
    - ConfigManager: Gestió configuració + manifests
    - PathDiscovery: Descobriment paths mòduls
    - ModuleDiscovery: Lògica descobriment
    - ModuleLoader: Càrrega dinàmica
    - ModuleRegistry: Registre + indexació
    - ModuleLifecycleManager: Cicle vida individual
    - SystemLifecycleManager: Cicle vida sistema
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
        """Descobreix nous mòduls escanejant manifest.toml"""
        return await self.discovery.discover_all()

    async def load_module(self, module_id: str) -> ModuleInfo:
        """Carrega un mòdul dinàmicament"""
        return await self.module_lifecycle.load_module(module_id)

    async def load_memory_modules(self, config: Dict) -> Dict[str, Any]:
        """Carrega Memory, RAG, Embeddings (ordre correcte)"""
        loaded = {}
        for module_id in ["memory", "rag", "embeddings"]:
            instance = await self.load_module(module_id)
            loaded[module_id] = instance
        return loaded
```

**Descobriment de mòduls:**

```python
# personality/module_manager/discovery.py
class ModuleDiscovery:
    def discover_all(self) -> List[str]:
        """Escaneja plugins/, memory/, personality/ per manifest.toml"""
        discovered = []
        for quadrant in ["plugins", "memory", "personality"]:
            for manifest_path in (base_path / quadrant).rglob("manifest.toml"):
                module_info = self._parse_manifest(manifest_path)
                if module_info:
                    discovered.append(module_info.module_id)
        return discovered

    def _parse_manifest(self, path: Path) -> Optional[ModuleInfo]:
        """Parseja manifest.toml (format TOML)"""
        data = tomllib.load(path.open("rb"))
        return ModuleInfo(
            module_id=data["module"]["name"],
            version=data["module"]["version"],
            entry_point=data["module"]["entry"],
            ...
        )
```

**Format manifest.toml:**

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

**Avantatges ModuleManager:**
- **Unificat**: Tots els mòduls (plugins, memory, core) van pel mateix sistema
- **Descobriment automàtic**: Escaneja manifest.toml
- **Lifecycle gestionat**: Initialize, shutdown, health checks
- **Registry centralitzat**: Un sol registre per tot
- **NO hardcoded**: No cal registrar manualment mòduls

#### Exemple: Mòdul MLX

**plugins/mlx_module/module.py:**

```python
from typing import Dict, Any, Optional

class MLXModule:
    """
    MLX Module - Motor d'inferència per Apple Silicon.

    Features:
    - Prefix matching real (TTFT instantani)
    - Optimitzat Metal (M1/M2/M3/M4)
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
        Inicialitza el mòdul MLX.

        Args:
            context: {"config": Dict, "project_root": Path}

        Returns:
            True si inicialització correcta
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
        """Cleanup del mòdul."""
        if self.model:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
        self._initialized = False
        return True

    def get_health(self) -> Dict[str, Any]:
        """Health check del mòdul."""
        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "model_loaded": self.model is not None,
            "version": self.version
        }

    def get_info(self) -> Dict[str, Any]:
        """Informació del mòdul."""
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "description": self.manifest.get("description", ""),
            "capabilities": self.manifest.get("capabilities", {}),
        }
```

**plugins/mlx_module/manifest.py** (Router FastAPI):

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

# Router registrat automàticament via ModuleManager
```

**Avantatges estructura nova:**
- **manifest.toml**: Metadata declarativa (descobriment automàtic)
- **module.py**: Lògica del mòdul (initialize, shutdown, health)
- **manifest.py**: Router FastAPI (lazy loaded)
- **Singleton**: Cada mòdul és singleton (get_instance())
- **Lifecycle gestionat**: ModuleManager controla initialize/shutdown

#### Exemple: Mòdul Ollama (Bridge)

**plugins/ollama_module/module.py:**

```python
import httpx
from typing import Dict, Any

class OllamaModule:
    """
    Ollama Module - Bridge HTTP a servidor Ollama local.

    Features:
    - Client async HTTP a Ollama API
    - Auto-verificació models disponibles
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
        """Inicialitza client Ollama."""
        config = context.get("config", {})
        model_name = config.get("plugins", {}).get("models", {}).get("primary")

        # Create async HTTP client
        self.client = httpx.AsyncClient(timeout=30.0)

        # Verificar Ollama disponible
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
        """Cleanup client."""
        if self.client:
            await self.client.aclose()
            self.client = None
        self._initialized = False
        return True

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generar via Ollama API."""
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

**Característiques Bridge Ollama:**
- **HTTP client async**: httpx.AsyncClient
- **Auto-verificació**: Comprova models disponibles a /api/tags
- **No carrega model**: Ollama gestiona la càrrega internament
- **Lifecycle**: Initialize crea client, shutdown tanca client

### 3. Memory (RAG)

**Sistema de memòria en 3 subcapes**: Embeddings, Memory, RAG.

#### Arquitectura del RAG (3 layers)

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

    Singleton que gestiona:
    - Flash Memory (cache temporal resultats)
    - RAM Context (context sessió actual)
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
        """Inicialitza Memory Module."""
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
        """Ingereix entry via pipeline."""
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
        """Guarda a SQLite + Qdrant."""
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
        """Cerca vectorial a Qdrant."""
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
    Interface unificada a Qdrant.

    Features:
    - Local mode (Qdrant local, no server)
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
        """Crear col·lecció si no existeix"""
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
        """Inserir múltiples vectors (batch)"""
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(self, query_vector: list[float], limit: int, threshold: float):
        """Cerca vectorial (similarity search)"""
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
    Embedding model amb cache i batch support.

    Features:
    - LRU cache (evita re-encode mateix text)
    - Async batch encoding
    - Multiple models (paraphrase-multilingual, all-MiniLM)
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    @lru_cache(maxsize=1024)
    def _encode_cached(self, text: str) -> tuple:
        """Encode amb cache (tuple per hashable)"""
        embedding = self.model.encode(text, convert_to_tensor=False)
        return tuple(embedding.tolist())

    async def encode(self, text: str) -> list[float]:
        """Encode single text (async wrapper)"""
        result = self._encode_cached(text.strip())
        return list(result)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode batch (més eficient que múltiples calls)"""
        # Normalize texts
        texts_clean = [t.strip() for t in texts]

        # Batch encode (NO cache aquí, massa gran)
        embeddings = self.model.encode(texts_clean, convert_to_tensor=False)
        return embeddings.tolist()
```

**Chunkers (Text + Code):**

```python
# memory/embeddings/chunkers/text_chunker.py
class TextChunker:
    """Semantic text chunking (preserva sentències)"""

    def chunk(self, text: str, max_size: int = 512) -> list[str]:
        """Split text en chunks semàntics"""
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
    """Code-aware chunking (preserva funcions/classes)"""

    def chunk(self, code: str, language: str) -> list[str]:
        """Split code preservant estructura"""
        # Detect functions/classes
        blocks = self._parse_code_blocks(code, language)
        return [block.content for block in blocks]
```

---

## Flux de dades

### Flux de chat sense RAG

```
1. Usuari → ./nexe chat
          ↓
2. CLI → POST /v1/chat/completions
          ↓
3. Endpoint → Get backend plugin
          ↓
4. Backend (MLX/llama.cpp/Ollama) → Generate
          ↓
5. Response → Format OpenAI
          ↓
6. CLI ← Mostrar resposta
```

### Flux de chat amb RAG

```
1. Usuari → ./nexe chat --rag
          ↓
2. CLI → POST /v1/chat/completions (use_rag=true)
          ↓
3. Endpoint → MemoryManager.search(query)
          ↓
4. MemoryManager → Generate embedding
          ↓
5. VectorStore (Qdrant) → Search similar vectors
          ↓
6. Endpoint ← Top-K resultats
          ↓
7. Endpoint → Build prompt amb context
          ↓
8. Backend → Generate amb context augmentat
          ↓
9. Response → Format OpenAI
          ↓
10. CLI ← Mostrar resposta
```

### Flux de guardar a memòria

```
1. Usuari → ./nexe memory store "text"
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

## Decisions arquitectòniques

### Per què FastAPI?

- **Async native:** Ideal per I/O amb Qdrant, models
- **Type hints:** Validació automàtica amb Pydantic
- **OpenAPI:** Documentació automàtica
- **Performance:** Molt ràpid (basat en Starlette + Uvicorn)
- **Ecosistema:** Gran comunitat Python

### Per què Qdrant?

- **Performance:** Molt ràpid per cerca vectorial
- **Embedded mode:** Pot córrer sense servidor extern
- **Persistence:** Guarda dades a disc
- **HNSW index:** Algorisme eficient per ANN search
- **Filtratge:** Permet filtrar per metadata

**Alternatives considerades:**
- FAISS: Més complex, menys features
- Chroma: Massa "pesada" per projecte local
- Milvus: Overkill per un projecte petit

### Per què sistema de plugins?

- **Flexibilitat:** Afegir backends sense modificar core
- **Testabilitat:** Cada plugin es pot testar aïlladament
- **Mantenibilitat:** Canvis en un plugin no afecten altres
- **Extensibilitat:** Fàcil afegir funcionalitats (LM Studio, etc.)

### Per què sentence-transformers?

- **Mida:** Models petits (~90MB)
- **Qualitat:** Bons embeddings per cerca semàntica
- **Offline:** No requereix API externa
- **Multilingüe:** Funciona bé en català amb all-MiniLM-L6-v2

**Alternativa futura:**
- Usar embeddings del mateix LLM (si és possible)

---

## Consideracions de performance

### Bottlenecks identificats

1. **Generació LLM:** El més lent (segons model)
   - Solució: Usar models petits o GPU

2. **Embeddings:** Pot ser lent amb molts documents
   - Solució: Batch processing, cache

3. **Cerca vectorial:** Ràpid amb Qdrant HNSW
   - No és bottleneck actual

### Optimitzacions aplicades

- **Lazy loading:** Models es carreguen només quan es necessiten
- **Connection pooling:** Reutilitzar connexions a Qdrant
- **Async everywhere:** No bloquejar l'event loop
- **Batch embeddings:** Generar múltiples embeddings alhora

### Consum de memòria

**Components:**
- Model LLM: 2-40 GB segons model
- Qdrant: ~100-500 MB segons documents
- Embedding model: ~90 MB
- FastAPI + Python: ~100-200 MB
- **Total:** Variable segons configuració

---

## Seguretat

### Capes de seguretat (Multi-layer)

#### 1. API Key Authentication (Dual-key support)

**Header suportat:** `X-API-Key` (NO Bearer token!)

**Configuració (variables d'entorn):**

```bash
# Dual-key rotation support
export NEXE_PRIMARY_API_KEY="new-key-2026"
export NEXE_PRIMARY_KEY_EXPIRES="2026-06-30T00:00:00Z"  # ISO 8601
export NEXE_SECONDARY_API_KEY="old-key-2025"
export NEXE_SECONDARY_KEY_EXPIRES="2026-01-31T00:00:00Z"

# Backward compatibility (NEXE_ADMIN_API_KEY)
export NEXE_ADMIN_API_KEY="single-key"

# Development mode (opcional, només dev)
export NEXE_ENV="development"  # Bypassa auth en dev
```

**Implementació:**

```python
# plugins/security/core/auth_dependencies.py
async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None)
) -> str:
    """
    FastAPI Dependency per validar API key.

    - Fail-closed: Si no dev mode, API key obligatòria
    - Dual-key: Accepta primary O secondary
    - Expiry check: Valida dates expiració
    - Metrics: Prometheus metrics per auth attempts
    """
    keys_config = load_api_keys()

    # Dev mode bypass (NOMÉS en NEXE_ENV=development)
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

**Usage als endpoints:**

```python
from fastapi import Depends
from plugins.security.core.auth_dependencies import require_api_key

@router.post("/admin/system/restart")
async def restart(api_key: str = Depends(require_api_key)):
    """Protected endpoint (requires valid API key)"""
    return {"status": "restarting"}
```

#### 2. Rate Limiting (Advanced)

**Limiters disponibles:**

```python
# core/dependencies.py
from slowapi import Limiter
from slowapi.util import get_remote_address, get_api_key

limiter_global = Limiter(key_func=get_remote_address)     # Per IP
limiter_by_key = Limiter(key_func=get_api_key)            # Per API key
limiter_composite = Limiter(key_func=composite_key_func)  # IP + key
limiter_by_endpoint = Limiter(key_func=endpoint_key_func) # Endpoint-specific
```

**Exemples d'ús:**

```python
# Rate limit per IP
@router.post("/bootstrap/init")
@limiter_global.limit("3/5minute")  # 3 intents per 5 min per IP
@limiter_global.limit("10/5minute", key_func=lambda: "global")  # 10 global
async def bootstrap_init(token: str):
    ...

# Rate limit per endpoint
@router.post("/security/scan")
@limiter_by_endpoint.limit("2/minute")
async def security_scan():
    ...
```

**Headers de resposta:**

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
    cookie_secure=True,  # Només HTTPS (prod)
    cookie_samesite="strict",
    exempt_urls=[
        r"/v1/.*",      # API endpoints (stateless)
        r"/health",
        r"/metrics",
    ]
)
```

#### 5. CORS (Strict)

**NO permet wildcards (*):**

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
        "style-src 'self' 'unsafe-inline'; "  # Web UI necessita inline CSS
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

### Amenaces mitigades

✅ **Prompt injection**: Sanitització RAG content, patterns detectats
✅ **Path traversal**: validate_safe_path() en tots els file ops
✅ **DoS**: Request size limit 100MB, rate limiting
✅ **CSRF**: starlette-csrf middleware
✅ **XSS**: CSP headers, no unsafe-inline per scripts
✅ **Brute force**: Rate limiting (3 intents/5min per IP)

### Amenaces residuals

⚠️ **Advanced prompt injection**: LLMs poden ser enganyats amb prompts sofisticats
⚠️ **Model extraction**: Si API pública, possibles atacs d'extracció
⚠️ **Side-channel timing**: API keys usen secrets.compare_digest() però altres vectors possibles

---

## Testing

### Estratègia de testing

```
server-nexe/
├── tests/
│   ├── unit/                  # Tests unitaris
│   │   ├── test_memory.py
│   │   ├── test_embeddings.py
│   │   └── test_plugins.py
│   │
│   ├── integration/           # Tests d'integració
│   │   ├── test_api.py
│   │   └── test_rag_flow.py
│   │
│   └── e2e/                   # Tests end-to-end
│       └── test_full_flow.py
│
├── conftest.py                # Fixtures pytest
└── pytest.ini                 # Config pytest
```

**Executar tests:**
```bash
pytest tests/
```

---

## Logging

### Nivells de log

- **DEBUG:** Tot (verbose)
- **INFO:** Events importants
- **WARNING:** Coses inesperades però no crítiques
- **ERROR:** Errors que requereixen atenció
- **CRITICAL:** Sistema inoperatiu

### Configuració

Al `.env`:
```
LOG_LEVEL=INFO
LOG_FILE=logs/nexe.log
```

### Veure logs

```bash
# En temps real
tail -f logs/nexe.log

# Últimes 100 línies
tail -n 100 logs/nexe.log

# Filtrar errors
grep ERROR logs/nexe.log
```

---

## Monitoratge

### Mètriques disponibles

- **Requests:** Total, per endpoint, errors
- **Latència:** P50, P95, P99 per endpoint
- **Model:** Tokens generats, temps d'inferència
- **Memòria:** RAM usada, vectors a Qdrant
- **Sistema:** CPU, disc, uptime

### Endpoints de mètriques

**Prometheus (text format):**
```bash
curl http://localhost:9119/metrics
```

**Resposta (Prometheus format):**
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

**Resposta (JSON):**
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

## Escalabilitat

### Límits actuals

- **Single instance:** No distribuït
- **Single model:** Un model actiu alhora
- **Local only:** No replicació

### Millores futures (hipotètiques)

- **Model switching:** Canviar models sense reiniciar
- **Multiple backends:** Múltiples models simultanis
- **Distributed Qdrant:** Clúster per més dades
- **Load balancing:** Múltiples instàncies NEXE

Però... **és un projecte local i educatiu**, no cal sobre-enginyeria.

---

## Següents passos

Per aprofundir més:

1. **RAG.md** - Detalls del sistema de memòria
2. **PLUGINS.md** - Com crear plugins
3. **API.md** - Referència completa de l'API
4. **LIMITATIONS.md** - Limitacions tècniques

---

## Actualitzacions d'aquest document

**Data actualització:** 2026-02-04
**Versió:** 0.8.1 (actualitzat per reflectir codi real)

### Canvis principals vs versió anterior:

1. **Estructura directoris actualitzada**
   - Afegits: `core/bootstrap_tokens.py`, `plugins/security_logger/`, `personality/module_manager/`
   - Corregits paths: `storage/` en lloc de `snapshots/`, `storage/vectors/` per DBs
   - Afegida subcapa `memory/` amb 3 layers (embeddings, memory, rag)

2. **Factory Pattern documentat**
   - `core/server/factory.py` com a factory real (singleton cached)
   - Rendiment: 0.58s → <10ms en calls posteriors
   - Factory submòduls: factory_app, factory_state, factory_modules, etc.

3. **Lifespan.py complex**
   - Gestor de processos (arrenca Qdrant, Ollama binaris)
   - Bootstrap tokens (generació + persistència DB)
   - Auto-ingest knowledge/ (primera execució)
   - 635 línies vs exemple simplificat anterior

4. **CLI amb Click (NO Typer)**
   - DynamicGroup + CLIRouter per descobriment automàtic
   - Subprocessos per aïllament
   - Descobriment via manifest.toml

5. **ModuleManager (NO BasePlugin/registry)**
   - SINGLE SOURCE OF TRUTH a `personality/module_manager/`
   - NO existeix `plugins/base.py` ni `plugins/registry.py`
   - Descobriment via manifest.toml (format TOML)
   - Lifecycle gestionat: initialize, shutdown, health

6. **Sistema Memory en 3 capes**
   - Embeddings Layer: vectorstore, cached embedder, chunkers
   - Memory Layer: FlashMemory, RAMContext, PersistenceManager
   - RAG Layer: orchestration, RAG sources

7. **Seguretat detallada**
   - X-API-Key header (NO Bearer token)
   - Dual-key support (PRIMARY + SECONDARY)
   - CSRF protection (starlette-csrf)
   - RAG sanitization (prompt injection patterns)
   - Security Logger (SIEM logs)
   - Path traversal protection

8. **Endpoints corregits**
   - `/api/info` (NO `/info`)
   - `/admin/system/*` (NO `/system/*`)
   - `/v1/memory/store` (NO `/memory/store`)
   - `/bootstrap/init`, `/bootstrap/info` (nous)

9. **Mètriques Prometheus**
   - `/metrics` → Prometheus text format
   - `/metrics/json` → JSON summary

### Discrepàncies corregides:

| Aspecte anterior | Realitat codi |
|------------------|---------------|
| CLI amb Typer | CLI amb Click + DynamicGroup |
| plugins/base.py, plugins/registry.py | personality/module_manager/module_manager.py |
| memory/manager.py | memory/memory/module.py (3 subcapes) |
| Qdrant snapshots/ | storage/qdrant/ |
| API key Bearer token | X-API-Key header |
| Single API key | Dual-key (PRIMARY + SECONDARY) |
| /info, /system/* | /api/info, /admin/system/* |
| Lifespan simplificat | Lifespan 635 línies (gestor processos) |

---

**Nota:** Aquesta arquitectura és la v0.8. Pot evolucionar en futures versions.

**Filosofia:** Simplicitat > Complexitat. No afegir capes innecessàries.

**Manteniment:** Document actualitzat per reflectir el codi real. Si trobes discrepàncies, reporta-les a l'equip.
