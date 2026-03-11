# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-architecture

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Visión general de la arquitectura interna de NEXE 0.8. Tres capas: Interfaces → Core → Plugins → Servicios Base. Cubre Factory Pattern, lifespan manager, sistema de memoria en 3 capas, CLI y decisiones de diseño."
tags: [arquitectura, fastapi, plugins, qdrant, memory, lifespan, cli, diseño]
chunk_size: 1500
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Arquitectura - NEXE 0.8

> **📝 Documento actualizado:** 2026-02-04
> **⚠️ IMPORTANTE:** Este documento ha sido revisado y actualizado para reflejar el **código real** de Nexe 0.8.
> Las versiones anteriores contenían descripciones simplificadas u obsoletas. Esta versión es **precisa y honesta** con la implementación actual.

Esta documentación explica cómo está construido NEXE internamente. Es útil si quieres:
- Entender cómo funciona el sistema
- Contribuir al proyecto
- Crear plugins o extensiones
- Depurar problemas
- Aprender sobre arquitectura de sistemas de IA

## Visión general

NEXE está diseñado con una **arquitectura modular en cinco capas**:

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
                        ↓
┌─────────────────────────────────────────────────────┐
│                     STORAGE                         │
│  models/ │ qdrant/ │ vectors/ │ logs/ │ cache/     │
└─────────────────────────────────────────────────────┘
```

### Principios de diseño

1. **Modularidad:** Componentes desacoplados e intercambiables
2. **Plugin-based:** Los backends son plugins que se cargan dinámicamente
3. **API-first:** Todo accesible vía API REST
4. **RAG nativo:** La memoria es de primera clase, no un añadido
5. **Simplicidad:** Código legible, evitar sobre-ingeniería

---

## Estructura de directorios

```
server-nexe/
├── core/                      # Núcleo del sistema
│   ├── __init__.py
│   ├── app.py                 # Entry point FastAPI
│   ├── config.py              # Configuración global (TOML + .env)
│   ├── container.py           # Dependency injection container
│   ├── dependencies.py        # FastAPI dependencies (rate limiting)
│   ├── lifespan.py            # Gestión ciclo de vida (arranca Qdrant/Ollama)
│   ├── middleware.py          # Middleware HTTP (CORS, CSRF, logging)
│   ├── models.py              # Modelos Pydantic
│   ├── resources.py           # Gestión de recursos
│   ├── security_headers.py    # Headers seguridad OWASP
│   ├── utils.py               # Utilidades generales
│   ├── bootstrap_tokens.py    # Sistema tokens bootstrap (DB persist)
│   ├── request_size_limiter.py # Protección DoS (100MB limit)
│   │
│   ├── cli/                   # Interfaz línea de comandos (Click)
│   │   ├── __init__.py
│   │   ├── cli.py             # CLI principal (Click + DynamicGroup)
│   │   ├── router.py          # Router dinámico (descubre CLIs módulos)
│   │   ├── chat_cli.py        # Comando chat interactivo
│   │   ├── log_viewer.py      # Ver logs en tiempo real
│   │   ├── output.py          # Formateo salida CLI
│   │   └── client.py          # Cliente HTTP para API local
│   │
│   ├── endpoints/             # API REST endpoints
│   │   ├── __init__.py
│   │   ├── chat.py            # POST /v1/chat/completions (RAG + streaming)
│   │   ├── root.py            # GET /, /health, /api/info
│   │   ├── system.py          # POST /admin/system/* (restart, status)
│   │   ├── modules.py         # GET /modules (info módulos cargados)
│   │   ├── bootstrap.py       # POST /bootstrap/init, GET /bootstrap/info
│   │   └── v1.py              # Wrapper endpoints v1
│   │
│   ├── server/                # Factory pattern (singleton cached)
│   │   ├── __init__.py
│   │   ├── factory.py         # Fachada principal create_app()
│   │   ├── factory_app.py     # Crear instancia FastAPI
│   │   ├── factory_state.py   # Setup app.state
│   │   ├── factory_security.py # SecurityLogger, validación prod
│   │   ├── factory_i18n.py    # I18n + config setup
│   │   ├── factory_modules.py # Descubrimiento y carga módulos
│   │   ├── factory_routers.py # Registro routers core
│   │   ├── runner.py          # Uvicorn server runner
│   │   └── helpers.py         # Utilidades factory
│   │
│   ├── loader/                # Carga dinámica módulos
│   │   ├── __init__.py
│   │   └── module_loader.py   # Loader de módulos Python
│   │
│   ├── metrics/               # Métricas Prometheus
│   │   ├── __init__.py
│   │   ├── endpoint.py        # /metrics, /metrics/json
│   │   ├── collector.py       # Colector métricas
│   │   └── registry.py        # Registry Prometheus
│   │
│   ├── ingest/                # Ingestión documentos knowledge/
│   │   ├── __init__.py
│   │   └── ingest_knowledge.py # Auto-ingest .md, .txt, .pdf
│   │
│   ├── paths/                 # Gestión paths proyecto
│   │   ├── __init__.py
│   │   └── path_resolver.py
│   │
│   └── resilience/            # Resiliencia (retry, timeout)
│       ├── __init__.py
│       └── retry.py
│
├── plugins/                   # Módulos de plugins (sin base.py/registry.py)
│   ├── __init__.py
│   │
│   ├── mlx_module/            # Backend MLX (Apple Silicon)
│   │   ├── __init__.py
│   │   ├── manifest.toml      # Metadata módulo (formato v0.8)
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
│   ├── security/              # Plugin seguridad completo
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
├── memory/                    # Sistema RAG (3 subcapas)
│   ├── __init__.py
│   │
│   ├── embeddings/            # Subcapa: Generación vectores
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
├── personality/               # Personalidad y configuración del sistema
│   ├── __init__.py
│   ├── server.toml            # Configuración principal (TOML)
│   ├── integration.py         # APIIntegrator
│   │
│   ├── i18n/                  # Internacionalización
│   │   ├── i18n_manager.py
│   │   └── translations/      # ca.json, en.json, es.json
│   │
│   ├── module_manager/        # SINGLE SOURCE OF TRUTH para módulos
│   │   ├── module_manager.py  # ModuleManager fachada
│   │   ├── registry.py        # ModuleRegistry
│   │   ├── discovery.py       # Module discovery
│   │   ├── path_discovery.py  # Path resolution
│   │   ├── config_manager.py  # Config + manifests
│   │   ├── module_lifecycle.py # Lifecycle individual
│   │   └── system_lifecycle.py # System lifecycle
│   │
│   ├── models/                # Model selection system
│   │   ├── selector.py        # Hardware detection + recomendaciones
│   │   └── registry.py        # Verified models registry
│   │
│   ├── events/                # Event system
│   │   └── event_system.py
│   │
│   └── metrics/               # Metrics collector
│       └── metrics_collector.py
│
├── knowledge/                 # Documentos auto-ingestados (RAG)
│   ├── ARCHITECTURE.md        # (este documento)
│   ├── SECURITY.md
│   ├── API.md
│   └── ...                    # Ingestado automáticamente en Qdrant
│
├── storage/                   # Persistencia (NO en git)
│   ├── qdrant/                # Qdrant local storage
│   ├── vectors/               # Vector DBs
│   │   ├── qdrant_local/
│   │   └── metadata_memory.db # SQLite metadata
│   ├── models/                # Modelos LLM descargados
│   ├── system-logs/           # Security logs (SIEM)
│   │   └── security/
│   └── .knowledge_ingested    # Marker file (auto-ingest)
│
├── dev-tools/                 # Herramientas de desarrollo
│   └── ...
│
├── nexe                       # Ejecutable CLI (#!/usr/bin/env bash)
├── qdrant                     # Binario Qdrant (auto-descargado)
├── requirements.txt           # Dependencias Python
├── install_nexe.py            # Instalador automático
├── setup.sh                   # Setup script
├── conftest.py                # Configuración pytest
└── pytest.ini                 # Config pytest
```

---

## Componentes principales

### 1. Core

El núcleo del sistema, basado en **FastAPI**.

#### app.py + Factory Pattern

**IMPORTANTE**: La app NO se crea directamente en app.py. Se usa un **factory pattern** con **singleton cached**:

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
    Application factory - Singleton cached con double-check locking.

    Rendimiento:
    - First call (cold): ~0.5-0.6s (i18n, config, module discovery)
    - Cached calls (warm): <0.01s (retorna instancia existente)
    """
    global _app_instance

    # Double-check locking pattern
    if _app_instance is not None and not force_reload:
        return _app_instance

    with _app_lock:
        if _app_instance is not None and not force_reload:
            return _app_instance

        # Crear app via submódulos factory
        i18n, config, module_manager = setup_i18n_and_config(project_root)
        app = create_fastapi_instance(i18n, config)
        setup_app_state(app, i18n, config, project_root, module_manager)
        setup_security_logger(app, project_root, i18n)
        discover_and_load_modules(app, module_manager, project_root, i18n)
        register_core_routers(app, i18n)

        _app_instance = app
        return app
```

**Ventajas del Factory Pattern:**
- **Performance**: Singleton cache evita rebuild (0.58s → 10ms)
- **Thread-safe**: Double-check locking pattern
- **Testable**: `reset_app_cache()` para tests
- **Modular**: Separado en factory_app.py, factory_state.py, factory_modules.py, etc.

#### lifespan.py

**Gestor complejo de ciclo de vida** (~635 líneas) que se encarga de:

1. **Auto-start servicios externos** (Qdrant, Ollama)
2. **Inicialización módulos** (Memory, RAG, Embeddings, plugins)
3. **Bootstrap tokens** (generación + persistencia DB)
4. **Auto-ingest knowledge/** (primera ejecución)
5. **Cleanup Ollama** (unload modelos de RAM)
6. **Graceful shutdown**

**Ejemplo simplificado:**

```python
from contextlib import asynccontextmanager
import subprocess
from pathlib import Path

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    logger.info("LIFESPAN STARTUP TRIGGERED")

    # 1. Auto-start Qdrant (binario local, NO Docker)
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

    # 3. Cleanup Ollama (unload modelos de sesiones previas)
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

    # 6. Auto-ingest knowledge/ (solo primera ejecución)
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

    yield  # Servidor funcionando

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

**Características clave:**
- **Gestión de procesos**: Arranca y detiene binarios Qdrant/Ollama
- **Async-aware**: Usa `asyncio.sleep()` en lugar de `time.sleep()` para no bloquear el event loop
- **Bootstrap tokens**: Generación alta entropía (128 bits) + persistencia SQLite
- **Auto-ingest inteligente**: Solo primera ejecución (marker file)
- **Graceful shutdown**: Cleanup adecuado de todos los recursos

#### endpoints/

Cada endpoint es un router de FastAPI:

**Ejemplo: endpoints/chat.py**

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
    # 1. Si RAG activado, consultar memoria
    context = []
    if request.use_rag:
        context = await memory_manager.search(
            query=request.messages[-1].content,
            limit=5
        )

    # 2. Construir prompt con contexto
    prompt = build_prompt(request.messages, context)

    # 3. Generar respuesta con el backend
    response = await backend.generate(
        prompt=prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens
    )

    # 4. Retornar en formato OpenAI
    return ChatCompletionResponse(
        choices=[{"message": {"content": response}}],
        usage={"total_tokens": len(response.split())}
    )
```

#### middleware.py

Middleware HTTP para logging, seguridad, etc:

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

Interfaz de línea de comandos con **Click** y **router dinámico**:

**core/cli/cli.py** (CLI principal):
```python
import click
from .router import CLIRouter

class DynamicGroup(click.Group):
    """
    Click Group que intercepta comandos no definidos y los redirige
    al router para invocar CLIs de módulos via subprocess.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._router = CLIRouter()

    def get_command(self, ctx: click.Context, cmd_name: str):
        # 1. Primero busca en comandos registrados (go, status, modules)
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        # 2. Si no lo encuentra, busca en CLIs de módulos
        cli_info = self._router.get_cli(cmd_name)
        if cli_info is None:
            return None

        # 3. Crear comando dinámico que delega al CLI del módulo
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
    """Arrancar el sistema Nexe completo (Qdrant + Servidor)."""
    subprocess.run([sys.executable, "-m", "core.app"], ...)

@app.command()
def modules():
    """Listar módulos con CLI disponibles."""
    router = CLIRouter()
    clis = router.discover_all()
    print_modules_table(clis)
```

**core/cli/router.py** (Router dinámico):
```python
from pathlib import Path
import subprocess

class CLIRouter:
    """
    Router que descubre y ejecuta CLIs de módulos Nexe.

    Estrategia:
    1. Descubre via manifest.toml ([module.cli])
    2. Ejecuta via subprocess para aislamiento
    """
    def discover_all(self) -> List[CLIInfo]:
        # Escanea plugins/, memory/, personality/ por manifest.toml
        for manifest_path in quadrant_path.rglob("manifest.toml"):
            cli_data = parse_manifest(manifest_path)
            if cli_data:
                self._cache[cli_data.alias] = cli_data
        return list(self._cache.values())

    def execute(self, alias: str, args: List[str]) -> int:
        """Ejecuta CLI de módulo via subprocess."""
        cli_info = self.get_cli(alias)
        cmd = [sys.executable, "-m", cli_info.entry_point] + args
        result = subprocess.run(cmd, cwd=project_root)
        return result.returncode
```

**Ejemplos de uso:**
```bash
./nexe go                  # Arranca servidor
./nexe chat                # CLI dinámico → core.cli.chat_cli
./nexe chat --rag          # Chat con RAG
./nexe memory store "data" # CLI dinámico → memory.memory.cli
./nexe rag search "query"  # CLI dinámico → memory.rag.cli
./nexe modules             # Lista CLIs disponibles
```

**Ventajas del router dinámico:**
- **Descubrimiento automático**: Escanea manifest.toml de todos los módulos
- **Aislamiento**: Cada CLI corre en subprocess separado
- **Extensible**: Añadir nuevo CLI = añadir manifest.toml
- **No hardcoded**: No hace falta registrar manualmente cada CLI

### 2. Sistema de Módulos (NO plugins/base.py!)

**IMPORTANTE**: NO existe `plugins/base.py` ni `plugins/registry.py`. El sistema real usa **ModuleManager** en `personality/module_manager/`.

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

    Gestiona todos los módulos:
    - Plugin modules (plugins/*)
    - Memory modules (memory/*)
    - Core modules (core/*)

    Componentes:
    - ConfigManager: Gestión configuración + manifests
    - PathDiscovery: Descubrimiento paths módulos
    - ModuleDiscovery: Lógica descubrimiento
    - ModuleLoader: Carga dinámica
    - ModuleRegistry: Registro + indexación
    - ModuleLifecycleManager: Ciclo de vida individual
    - SystemLifecycleManager: Ciclo de vida del sistema
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
        """Descubre nuevos módulos escaneando manifest.toml"""
        return await self.discovery.discover_all()

    async def load_module(self, module_id: str) -> ModuleInfo:
        """Carga un módulo dinámicamente"""
        return await self.module_lifecycle.load_module(module_id)

    async def load_memory_modules(self, config: Dict) -> Dict[str, Any]:
        """Carga Memory, RAG, Embeddings (orden correcto)"""
        loaded = {}
        for module_id in ["memory", "rag", "embeddings"]:
            instance = await self.load_module(module_id)
            loaded[module_id] = instance
        return loaded
```

**Descubrimiento de módulos:**

```python
# personality/module_manager/discovery.py
class ModuleDiscovery:
    def discover_all(self) -> List[str]:
        """Escanea plugins/, memory/, personality/ por manifest.toml"""
        discovered = []
        for quadrant in ["plugins", "memory", "personality"]:
            for manifest_path in (base_path / quadrant).rglob("manifest.toml"):
                module_info = self._parse_manifest(manifest_path)
                if module_info:
                    discovered.append(module_info.module_id)
        return discovered

    def _parse_manifest(self, path: Path) -> Optional[ModuleInfo]:
        """Parsea manifest.toml (formato TOML)"""
        data = tomllib.load(path.open("rb"))
        return ModuleInfo(
            module_id=data["module"]["name"],
            version=data["module"]["version"],
            entry_point=data["module"]["entry"],
            ...
        )
```

**Formato manifest.toml:**

```toml
# plugins/mlx_module/manifest.toml
[module]
name = "mlx_module"
version = "0.8.0"
type = "local_llm_option"
description = "Motor MLX para Apple Silicon"
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

**Ventajas ModuleManager:**
- **Unificado**: Todos los módulos (plugins, memory, core) pasan por el mismo sistema
- **Descubrimiento automático**: Escanea manifest.toml
- **Lifecycle gestionado**: Initialize, shutdown, health checks
- **Registry centralizado**: Un solo registro para todo
- **NO hardcoded**: No hace falta registrar manualmente módulos

#### Ejemplo: Módulo MLX

**plugins/mlx_module/module.py:**

```python
from typing import Dict, Any, Optional

class MLXModule:
    """
    MLX Module - Motor de inferencia para Apple Silicon.

    Features:
    - Prefix matching real (TTFT instantáneo)
    - Optimizado Metal (M1/M2/M3/M4)
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
        Inicializa el módulo MLX.

        Args:
            context: {"config": Dict, "project_root": Path}

        Returns:
            True si inicialización correcta
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
        """Cleanup del módulo."""
        if self.model:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
        self._initialized = False
        return True

    def get_health(self) -> Dict[str, Any]:
        """Health check del módulo."""
        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "model_loaded": self.model is not None,
            "version": self.version
        }

    def get_info(self) -> Dict[str, Any]:
        """Información del módulo."""
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

# Router registrado automáticamente via ModuleManager
```

**Ventajas nueva estructura:**
- **manifest.toml**: Metadata declarativa (descubrimiento automático)
- **module.py**: Lógica del módulo (initialize, shutdown, health)
- **manifest.py**: Router FastAPI (lazy loaded)
- **Singleton**: Cada módulo es singleton (get_instance())
- **Lifecycle gestionado**: ModuleManager controla initialize/shutdown

#### Ejemplo: Módulo Ollama (Bridge)

**plugins/ollama_module/module.py:**

```python
import httpx
from typing import Dict, Any

class OllamaModule:
    """
    Ollama Module - Bridge HTTP a servidor Ollama local.

    Features:
    - Cliente async HTTP a Ollama API
    - Auto-verificación modelos disponibles
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
        """Inicializa cliente Ollama."""
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
        """Cleanup cliente."""
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

**Características Bridge Ollama:**
- **HTTP client async**: httpx.AsyncClient
- **Auto-verificación**: Comprueba modelos disponibles en /api/tags
- **No carga modelo**: Ollama gestiona la carga internamente
- **Lifecycle**: Initialize crea cliente, shutdown cierra cliente

### 3. Memory (RAG)

**Sistema de memoria en 3 subcapas**: Embeddings, Memory, RAG.

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
    - Flash Memory (cache temporal de resultados)
    - RAM Context (contexto de sesión actual)
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
        """Inicializa Memory Module."""
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
        """Ingesta entry via pipeline."""
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
        """Guarda en SQLite + Qdrant."""
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
        """Búsqueda vectorial en Qdrant."""
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
    Interfaz unificada a Qdrant.

    Features:
    - Local mode (Qdrant local, sin servidor)
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
        """Crear colección si no existe"""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,  # 768 para paraphrase-multilingual
                    distance=Distance.COSINE
                )
            )

    def upsert_batch(self, points: list[PointStruct]):
        """Insertar múltiples vectores (batch)"""
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def search(self, query_vector: list[float], limit: int, threshold: float):
        """Búsqueda vectorial (similarity search)"""
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
    Modelo de embedding con cache y soporte batch.

    Features:
    - LRU cache (evita re-encode mismo texto)
    - Async batch encoding
    - Multiple models (paraphrase-multilingual, all-MiniLM)
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    @lru_cache(maxsize=1024)
    def _encode_cached(self, text: str) -> tuple:
        """Encode con cache (tuple para hashable)"""
        embedding = self.model.encode(text, convert_to_tensor=False)
        return tuple(embedding.tolist())

    async def encode(self, text: str) -> list[float]:
        """Encode texto individual (async wrapper)"""
        result = self._encode_cached(text.strip())
        return list(result)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode batch (más eficiente que múltiples calls)"""
        # Normalize texts
        texts_clean = [t.strip() for t in texts]

        # Batch encode (NO cache aquí, demasiado grande)
        embeddings = self.model.encode(texts_clean, convert_to_tensor=False)
        return embeddings.tolist()
```

**Chunkers (Text + Code):**

```python
# memory/embeddings/chunkers/text_chunker.py
class TextChunker:
    """Semantic text chunking (preserva frases)"""

    def chunk(self, text: str, max_size: int = 512) -> list[str]:
        """Split texto en chunks semánticos"""
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
    """Code-aware chunking (preserva funciones/clases)"""

    def chunk(self, code: str, language: str) -> list[str]:
        """Split código preservando estructura"""
        # Detect functions/classes
        blocks = self._parse_code_blocks(code, language)
        return [block.content for block in blocks]
```

---

## Flujo de datos

### Flujo de chat sin RAG

```
1. Usuario → ./nexe chat
          ↓
2. CLI → POST /v1/chat/completions
          ↓
3. Endpoint → Get backend plugin
          ↓
4. Backend (MLX/llama.cpp/Ollama) → Generate
          ↓
5. Response → Format OpenAI
          ↓
6. CLI ← Mostrar respuesta
```

### Flujo de chat con RAG

```
1. Usuario → ./nexe chat --rag
          ↓
2. CLI → POST /v1/chat/completions (use_rag=true)
          ↓
3. Endpoint → MemoryManager.search(query)
          ↓
4. MemoryManager → Generate embedding
          ↓
5. VectorStore (Qdrant) → Search similar vectors
          ↓
6. Endpoint ← Top-K resultados
          ↓
7. Endpoint → Build prompt con contexto
          ↓
8. Backend → Generate con contexto aumentado
          ↓
9. Response → Format OpenAI
          ↓
10. CLI ← Mostrar respuesta
```

### Flujo de guardar en memoria

```
1. Usuario → ./nexe memory store "texto"
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
7. CLI ← Confirmación (ID)
```

---

## Decisiones arquitectónicas

### ¿Por qué FastAPI?

- **Async nativo:** Ideal para I/O con Qdrant, modelos
- **Type hints:** Validación automática con Pydantic
- **OpenAPI:** Documentación automática
- **Performance:** Muy rápido (basado en Starlette + Uvicorn)
- **Ecosistema:** Gran comunidad Python

### ¿Por qué Qdrant?

- **Performance:** Muy rápido para búsqueda vectorial
- **Embedded mode:** Puede correr sin servidor externo
- **Persistence:** Guarda datos en disco
- **HNSW index:** Algoritmo eficiente para ANN search
- **Filtrado:** Permite filtrar por metadata

**Alternativas consideradas:**
- FAISS: Más complejo, menos features
- Chroma: Demasiado "pesada" para proyecto local
- Milvus: Overkill para un proyecto pequeño

### ¿Por qué sistema de plugins?

- **Flexibilidad:** Añadir backends sin modificar core
- **Testabilidad:** Cada plugin se puede testear de forma aislada
- **Mantenibilidad:** Cambios en un plugin no afectan a otros
- **Extensibilidad:** Fácil añadir funcionalidades (nuevos plugins, backends, etc.)

### ¿Por qué sentence-transformers?

- **Tamaño:** Modelos pequeños (~90MB)
- **Calidad:** Buenos embeddings para búsqueda semántica
- **Offline:** No requiere API externa
- **Multilingüe:** Funciona bien en español con all-MiniLM-L6-v2

**Alternativa futura:**
- Usar embeddings del mismo LLM (si es posible)

---

## Consideraciones de performance

### Bottlenecks identificados

1. **Generación LLM:** Lo más lento (según modelo)
   - Solución: Usar modelos pequeños o GPU

2. **Embeddings:** Puede ser lento con muchos documentos
   - Solución: Batch processing, cache

3. **Búsqueda vectorial:** Rápido con Qdrant HNSW
   - No es bottleneck actual

### Optimizaciones aplicadas

- **Lazy loading:** Los modelos se cargan solo cuando se necesitan
- **Connection pooling:** Reutilizar conexiones a Qdrant
- **Async everywhere:** No bloquear el event loop
- **Batch embeddings:** Generar múltiples embeddings a la vez

### Consumo de memoria

**Componentes:**
- Modelo LLM: 2-40 GB según modelo
- Qdrant: ~100-500 MB según documentos
- Modelo embedding: ~90 MB
- FastAPI + Python: ~100-200 MB
- **Total:** Variable según configuración

---

## Seguridad

### Capas de seguridad (Multi-layer)

#### 1. API Key Authentication (Dual-key support)

**Header soportado:** `X-API-Key` (NO Bearer token!)

**Configuración (variables de entorno):**

```bash
# Dual-key rotation support
export NEXE_PRIMARY_API_KEY="new-key-2026"
export NEXE_PRIMARY_KEY_EXPIRES="2026-06-30T00:00:00Z"  # ISO 8601
export NEXE_SECONDARY_API_KEY="old-key-2025"
export NEXE_SECONDARY_KEY_EXPIRES="2026-01-31T00:00:00Z"

# Backward compatibility (single key)
export NEXE_ADMIN_API_KEY="single-key"

# Development mode (opcional, solo dev)
export NEXE_ENV="development"  # Bypassa auth en dev
```

**Implementación:**

```python
# plugins/security/core/auth_dependencies.py
async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None)
) -> str:
    """
    FastAPI Dependency para validar API key.

    - Fail-closed: Si no dev mode, API key obligatoria
    - Dual-key: Acepta primary O secondary
    - Expiry check: Valida fechas de expiración
    - Metrics: Prometheus metrics para auth attempts
    """
    keys_config = load_api_keys()

    # Dev mode bypass (SOLO en NEXE_ENV=development)
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

**Uso en los endpoints:**

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

limiter_global = Limiter(key_func=get_remote_address)     # Por IP
limiter_by_key = Limiter(key_func=get_api_key)            # Por API key
limiter_composite = Limiter(key_func=composite_key_func)  # IP + key
limiter_by_endpoint = Limiter(key_func=endpoint_key_func) # Endpoint-specific
```

**Ejemplos de uso:**

```python
# Rate limit por IP
@router.post("/bootstrap/init")
@limiter_global.limit("3/5minute")  # 3 intentos por 5 min por IP
@limiter_global.limit("10/5minute", key_func=lambda: "global")  # 10 global
async def bootstrap_init(token: str):
    ...

# Rate limit por endpoint
@router.post("/security/scan")
@limiter_by_endpoint.limit("2/minute")
async def security_scan():
    ...
```

**Headers de respuesta:**

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
    cookie_secure=True,  # Solo HTTPS (prod)
    cookie_samesite="strict",
    exempt_urls=[
        r"/v1/.*",      # API endpoints (stateless)
        r"/health",
        r"/metrics",
    ]
)
```

#### 5. CORS (Strict)

**NO permite wildcards (*):**

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
        "style-src 'self' 'unsafe-inline'; "  # Web UI necesita inline CSS
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
    """Registra eventos de seguridad en storage/system-logs/security/"""

    def log_auth_attempt(self, ip: str, success: bool, key_type: str):
        ...

    def log_rate_limit(self, ip: str, endpoint: str):
        ...

    def log_injection_attempt(self, ip: str, pattern: str, content: str):
        ...

    def log_path_traversal(self, ip: str, path: str):
        ...
```

**Formato log (JSON):**

```json
{
  "timestamp": "2026-02-04T12:34:56Z",
  "event_type": "auth_failure",
  "ip": "192.168.1.100",
  "details": {"reason": "invalid_key", "endpoint": "/admin/system/restart"}
}
```

### Amenazas mitigadas

✅ **Prompt injection**: Sanitización RAG content, patrones detectados
✅ **Path traversal**: validate_safe_path() en todas las operaciones de fichero
✅ **DoS**: Request size limit 100MB, rate limiting
✅ **CSRF**: starlette-csrf middleware
✅ **XSS**: CSP headers, no unsafe-inline para scripts
✅ **Brute force**: Rate limiting (3 intentos/5min por IP)

### Amenazas residuales

⚠️ **Advanced prompt injection**: Los LLMs pueden ser engañados con prompts sofisticados
⚠️ **Model extraction**: Si API pública, posibles ataques de extracción
⚠️ **Side-channel timing**: Las API keys usan secrets.compare_digest() pero otros vectores posibles

---

## Testing

### Estrategia de testing

```
server-nexe/
├── tests/
│   ├── unit/                  # Tests unitarios
│   │   ├── test_memory.py
│   │   ├── test_embeddings.py
│   │   └── test_plugins.py
│   │
│   ├── integration/           # Tests de integración
│   │   ├── test_api.py
│   │   └── test_rag_flow.py
│   │
│   └── e2e/                   # Tests end-to-end
│       └── test_full_flow.py
│
├── conftest.py                # Fixtures pytest
└── pytest.ini                 # Config pytest
```

**Ejecutar tests:**
```bash
pytest tests/
```

---

## Logging

### Niveles de log

- **DEBUG:** Todo (verbose)
- **INFO:** Eventos importantes
- **WARNING:** Cosas inesperadas pero no críticas
- **ERROR:** Errores que requieren atención
- **CRITICAL:** Sistema inoperativo

### Configuración

En `.env`:
```
LOG_LEVEL=INFO
LOG_FILE=logs/nexe.log
```

### Ver logs

```bash
# En tiempo real
tail -f logs/nexe.log

# Últimas 100 líneas
tail -n 100 logs/nexe.log

# Filtrar errores
grep ERROR logs/nexe.log
```

---

## Monitorización

### Métricas disponibles

- **Requests:** Total, por endpoint, errores
- **Latencia:** P50, P95, P99 por endpoint
- **Modelo:** Tokens generados, tiempo de inferencia
- **Memoria:** RAM usada, vectores en Qdrant
- **Sistema:** CPU, disco, uptime

### Endpoints de métricas

**Prometheus (text format):**
```bash
curl http://localhost:9119/metrics
```

**Respuesta (Prometheus format):**
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

**Respuesta (JSON):**
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

## Escalabilidad

### Límites actuales

- **Single instance:** No distribuido
- **Single model:** Un modelo activo a la vez
- **Local only:** Sin replicación

### Mejoras futuras (hipotéticas)

- **Model switching:** Cambiar modelos sin reiniciar
- **Multiple backends:** Múltiples modelos simultáneos
- **Distributed Qdrant:** Clúster para más datos
- **Load balancing:** Múltiples instancias NEXE

Pero... **es un proyecto local y educativo**, no hace falta sobre-ingeniería.

---

## Siguientes pasos

Para profundizar más:

1. **RAG.md** - Detalles del sistema de memoria
2. **PLUGINS.md** - Cómo crear plugins
3. **API.md** - Referencia completa de la API
4. **LIMITATIONS.md** - Limitaciones técnicas

---

## Actualizaciones de este documento

**Fecha actualización:** 2026-02-04
**Versión:** 0.8.1 (actualizado para reflejar código real)

### Cambios principales vs versión anterior:

1. **Estructura de directorios actualizada**
   - Añadidos: `core/bootstrap_tokens.py`, `plugins/security_logger/`, `personality/module_manager/`
   - Paths corregidos: `storage/` en lugar de `snapshots/`, `storage/vectors/` para DBs
   - Añadida subcapa `memory/` con 3 layers (embeddings, memory, rag)

2. **Factory Pattern documentado**
   - `core/server/factory.py` como factory real (singleton cached)
   - Rendimiento: 0.58s → <10ms en calls posteriores
   - Factory submódulos: factory_app, factory_state, factory_modules, etc.

3. **Lifespan.py complejo**
   - Gestor de procesos (arranca binarios Qdrant, Ollama)
   - Bootstrap tokens (generación + persistencia DB)
   - Auto-ingest knowledge/ (primera ejecución)
   - 635 líneas vs ejemplo simplificado anterior

4. **CLI con Click (NO Typer)**
   - DynamicGroup + CLIRouter para descubrimiento automático
   - Subprocesos para aislamiento
   - Descubrimiento via manifest.toml

5. **ModuleManager (NO BasePlugin/registry)**
   - SINGLE SOURCE OF TRUTH en `personality/module_manager/`
   - NO existe `plugins/base.py` ni `plugins/registry.py`
   - Descubrimiento via manifest.toml (format TOML)
   - Lifecycle gestionado: initialize, shutdown, health

6. **Sistema Memory en 3 capas**
   - Embeddings Layer: vectorstore, cached embedder, chunkers
   - Memory Layer: FlashMemory, RAMContext, PersistenceManager
   - RAG Layer: orchestration, RAG sources

7. **Seguridad detallada**
   - Header X-API-Key (NO Bearer token)
   - Dual-key support (PRIMARY + SECONDARY)
   - CSRF protection (starlette-csrf)
   - RAG sanitization (patrones prompt injection)
   - Security Logger (SIEM logs)
   - Path traversal protection

8. **Endpoints corregidos**
   - `/api/info` (NO `/info`)
   - `/admin/system/*` (NO `/system/*`)
   - `/v1/memory/store` (NO `/memory/store`)
   - `/bootstrap/init`, `/bootstrap/info` (nuevos)

9. **Métricas Prometheus**
   - `/metrics` → Prometheus text format
   - `/metrics/json` → JSON summary

### Discrepancias corregidas:

| Aspecto anterior | Realidad código |
|------------------|-----------------|
| CLI con Typer | CLI con Click + DynamicGroup |
| plugins/base.py, plugins/registry.py | personality/module_manager/module_manager.py |
| memory/manager.py | memory/memory/module.py (3 subcapas) |
| Qdrant snapshots/ | storage/qdrant/ |
| API key Bearer token | Header X-API-Key |
| Single API key | Dual-key (PRIMARY + SECONDARY) |
| /info, /system/* | /api/info, /admin/system/* |
| Lifespan simplificado | Lifespan 635 líneas (gestor procesos) |

---

**Nota:** Esta arquitectura es la v0.8. Puede evolucionar en versiones futuras.

**Filosofía:** Simplicidad > Complejidad. No añadir capas innecesarias.

**Mantenimiento:** Documento actualizado para reflejar el código real. Si encuentras discrepancias, repórtalas al equipo.
