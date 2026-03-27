# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-architecture

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Arquitectura interna de server-nexe 0.8.2. Diseño de cinco capas: Interfaces, Core (factory FastAPI, endpoints divididos, lifespan dividido), Plugins (5 módulos con auto-descubrimiento), Servicios Base (memoria RAG 3 capas), Storage. Cubre refactoring modular (4 monolitos divididos en 20+ submódulos), module manager con lazy init, integración i18n y soporte Docker."
tags: [arquitectura, fastapi, plugins, qdrant, memoria, lifespan, cli, diseno, factory, modulos, refactoring, docker, i18n, module-manager]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Arquitectura — server-nexe 0.8.2

## Arquitectura de Cinco Capas

```
INTERFACES        CLI (./nexe) | API REST | Web UI
      |
CORE              Servidor FastAPI, endpoints, middleware, lifespan
      |
PLUGINS           MLX | llama.cpp | Ollama | Security | Web UI
      |
SERVICIOS BASE    Memory (RAG) | Qdrant | Embeddings | SQLite
      |
STORAGE           models/ | qdrant/ | vectors/ | logs/ | cache/
```

Principios de diseño: modularidad, backends como plugins, API-first, RAG nativo de primera clase, simplicidad.

## Estructura de Directorios (post-refactoring marzo 2026)

Cuatro ficheros monolíticos se dividieron en 20+ submódulos durante el refactoring de tech debt de marzo 2026:
- chat.py (1187 líneas) dividido en 8 submódulos
- routes.py (974 líneas) dividido en 6 submódulos
- lifespan.py (681 líneas) dividido en 3 submódulos
- tray.py (707 líneas) dividido en 2 submódulos

```
server-nexe/
├── core/
│   ├── app.py                    # Punto de entrada (delega a factory)
│   ├── config.py                 # Carga configuración TOML + .env
│   ├── lifespan.py               # Orquestador ciclo de vida (416 líneas)
│   ├── lifespan_services.py      # Auto-start servicios (Qdrant, Ollama)
│   ├── lifespan_tokens.py        # Generación bootstrap token
│   ├── lifespan_ollama.py        # Gestión ciclo de vida Ollama
│   ├── middleware.py              # CORS, CSRF, logging, cabeceras seguridad
│   ├── security_headers.py       # Cabeceras OWASP (CSP, HSTS, X-Frame)
│   ├── messages.py               # Claves i18n para core
│   ├── bootstrap_tokens.py       # Sistema bootstrap token (persistido DB)
│   ├── models.py                 # Modelos Pydantic
│   │
│   ├── endpoints/                # API REST
│   │   ├── chat.py               # POST /v1/chat/completions (orquestador)
│   │   ├── chat_schemas.py       # Modelos Pydantic (Message, ChatCompletionRequest)
│   │   ├── chat_sanitization.py  # Sanitización tokens SSE, truncamiento contexto
│   │   ├── chat_rag.py           # Constructor contexto RAG (3 colecciones)
│   │   ├── chat_memory.py        # Guardar conversación en memoria (MEM_SAVE)
│   │   ├── chat_engines/         # Generadores por backend
│   │   │   ├── routing.py        # Lógica selección motor
│   │   │   ├── ollama.py         # Generador streaming Ollama
│   │   │   ├── mlx.py            # Generador streaming MLX
│   │   │   └── llama_cpp.py      # Generador streaming llama.cpp
│   │   ├── root.py               # GET /, /health, /api/info
│   │   ├── bootstrap.py          # POST /bootstrap/init
│   │   ├── modules.py            # GET /modules
│   │   ├── system.py             # POST /admin/system/*
│   │   └── v1.py                 # Wrapper endpoints v1
│   │
│   ├── server/                   # Patrón factory (singleton cached)
│   │   ├── factory.py            # Fachada principal create_app() con double-check locking
│   │   ├── factory_app.py        # Crear instancia FastAPI
│   │   ├── factory_state.py      # Setup app.state
│   │   ├── factory_security.py   # SecurityLogger, validación producción
│   │   ├── factory_i18n.py       # Setup i18n + config
│   │   ├── factory_modules.py    # Descubrimiento y carga de módulos
│   │   ├── factory_routers.py    # Registro routers core
│   │   ├── runner.py             # Runner Uvicorn
│   │   └── exception_handlers.py # Patrones gestión de errores
│   │
│   ├── cli/                      # CLI Click con router dinámico
│   │   ├── cli.py                # DynamicGroup (intercepta CLIs de módulos)
│   │   ├── router.py             # CLIRouter (descubre CLIs vía manifest.toml)
│   │   ├── chat_cli.py           # Comando chat interactivo
│   │   └── client.py             # Cliente HTTP para API local
│   │
│   ├── ingest/                   # Ingesta de documentos
│   │   ├── ingest_docs.py        # docs/ → nexe_documentation (500/50 chars)
│   │   └── ingest_knowledge.py   # knowledge/ → user_knowledge (1500/200 chars)
│   │
│   ├── metrics/                  # Prometheus /metrics
│   ├── resilience/               # Circuit breaker, retry
│   └── paths/                    # Resolución de rutas
│
├── plugins/                      # 5 módulos plugin (auto-descubiertos)
│   ├── mlx_module/               # Backend Apple Silicon (MLX)
│   │   ├── module.py             # MLXModule + is_model_loaded()
│   │   ├── manifest.toml         # Metadatos del módulo
│   │   └── manifest.py           # Router FastAPI
│   │
│   ├── llama_cpp_module/         # Backend GGUF universal
│   │   ├── module.py             # LlamaCppModule + is_model_loaded()
│   │   └── manifest.toml
│   │
│   ├── ollama_module/            # Bridge Ollama
│   │   ├── module.py             # OllamaModule + auto-start + VRAM cleanup
│   │   ├── cli/                  # Subcomandos CLI Ollama
│   │   └── manifest.toml
│   │
│   ├── security/                 # Auth + detección de inyecciones
│   │   ├── core/                 # auth.py, rate_limiting.py, injection_detectors.py
│   │   ├── sanitizer/            # 69 patrones jailbreak
│   │   ├── security_logger/      # Logging auditoría RFC5424
│   │   └── manifest.toml
│   │
│   └── web_ui_module/            # Interfaz web
│       ├── api/                  # Routes divididos (6 ficheros)
│       │   ├── routes_auth.py    # Auth, backends, POST /ui/lang, Ollama auto-start
│       │   ├── routes_chat.py    # Streaming chat, MEM_SAVE, RAG, thinking tokens
│       │   ├── routes_files.py   # Subida documentos (aislamiento por sesión)
│       │   ├── routes_memory.py  # Guardar/recordar memoria
│       │   ├── routes_sessions.py # Gestión sesiones
│       │   └── routes_static.py  # Ficheros estáticos, cache-busting, i18n CSP-safe
│       ├── core/
│       │   ├── memory_helper.py  # Detección intenciones, auto-save, poda (716 líneas)
│       │   └── session_manager.py
│       ├── messages.py           # Claves i18n para web_ui
│       ├── ui/                   # HTML, CSS, JS
│       └── manifest.toml
│
├── memory/                       # Sistema RAG 3 subcapas
│   ├── embeddings/               # Generación vectores (Ollama + sentence-transformers)
│   ├── memory/                   # Gestión memoria (FlashMemory + RAMContext + Persistence)
│   │   └── constants.py          # DEFAULT_VECTOR_SIZE = 768
│   └── rag/                      # Orquestación RAG
│
├── personality/                  # Configuración del sistema
│   ├── server.toml               # Config principal (prompts, módulos, modelos)
│   ├── i18n/                     # Gestor i18n + traducciones (ca/es/en)
│   └── module_manager/           # FUENTE ÚNICA DE VERDAD para todos los módulos
│
├── installer/                    # Instalador macOS
│   ├── swift-wizard/             # Wizard SwiftUI (15 ficheros Swift, 6 pantallas)
│   ├── build_dmg.sh              # Constructor DMG con firma
│   ├── tray.py                   # App system tray (419 líneas)
│   ├── tray_translations.py      # i18n tray (ca/es/en)
│   └── tray_uninstaller.py       # Desinstalador con backup
│
├── knowledge/                    # Docs para ingesta RAG (ca/es/en)
├── storage/                      # Datos runtime (no en git)
├── tests/                        # 3901 tests, 0 fallos
├── Dockerfile                    # Python 3.12-slim + Qdrant embebido
├── docker-compose.yml            # Servicios Nexe + Ollama
└── nexe                          # Ejecutable CLI
```

## Patrón Factory

La app se crea vía un singleton factory con double-check locking:

- `core/app.py` llama a `create_app()` de `core/server/factory.py`
- Primera llamada (~0.5s): carga i18n, config, descubre módulos, registra routers
- Llamadas cached (<10ms): retorna instancia existente
- Factory dividido en 7 submódulos
- `reset_app_cache()` disponible para tests

## Gestor de Ciclo de Vida (Lifespan)

Gestiona el arranque y parada del servidor. Dividido en 3 submódulos:

**Secuencia de arranque:**
1. Cargar config de server.toml
2. Inicializar APIIntegrator (sistema de personalidad)
3. Auto-start Qdrant (binario embebido, puerto 6333)
4. Auto-start Ollama (si disponible, modo segundo plano)
5. Cargar módulos de memoria (Memory → RAG → Embeddings, orden correcto)
6. Inicializar módulos plugin (MLX, llama.cpp, Ollama, Security, Web UI)
7. Auto-ingestar knowledge/ (solo primera ejecución, fichero marcador)
8. Generar bootstrap token (128-bit, persistente SQLite, TTL 30min)

**Secuencia de parada:**
1. Descargar modelos Ollama (VRAM cleanup vía keep_alive:0)
2. Cerrar conexiones Qdrant
3. Terminar procesos hijos
4. Sincronizar estado a disco

## Module Manager

`personality/module_manager/` es la FUENTE ÚNICA DE VERDAD para todos los módulos. NO existe `plugins/base.py` ni `plugins/registry.py`.

**Componentes:** ConfigManager, PathDiscovery, ModuleDiscovery (escanea manifest.toml), ModuleLoader, ModuleRegistry, ModuleLifecycleManager (lazy asyncio.Lock para fix deadlock Python 3.12), SystemLifecycleManager.

**Formato manifest.toml** (cada plugin tiene uno):
```toml
[module]
name = "nombre_modulo"
version = "0.8.2"
type = "local_llm_option"

[module.entry]
module = "plugins.nombre_modulo.module"
class = "ClaseModulo"

[module.router]
prefix = "/modulo"
```

## Arquitectura CLI

CLI basado en Click con router dinámico:
- `DynamicGroup` intercepta comandos no definidos
- `CLIRouter` descubre CLIs de módulos vía manifest.toml
- CLIs de módulos se ejecutan en subproceso (aislamiento)
- Comandos: go, chat, status, modules, memory, knowledge, rag

## Arquitectura Memoria (3 subcapas)

```
Capa RAG (memory/rag/)                — orquesta búsqueda multi-colección
      |
Capa Memory (memory/memory/)          — FlashMemory + RAMContext + Persistence
      |
Capa Embeddings (memory/embeddings/)  — generación vectores + interfaz Qdrant
```

- FlashMemory: caché temporal con TTL (1800s)
- RAMContext: contexto sesión actual
- PersistenceManager: metadatos SQLite + vectores Qdrant
- Todos los vectores: 768 dimensiones (DEFAULT_VECTOR_SIZE centralizado)

## Arquitectura Endpoint Chat

`POST /v1/chat/completions` dividido en 8 submódulos:

1. **chat_schemas.py** — Modelos Pydantic (use_rag=True por defecto)
2. **chat_sanitization.py** — Sanitización SSE, truncamiento contexto (MAX_CONTEXT_CHARS=24000)
3. **chat_rag.py** — Constructor contexto RAG: busca nexe_documentation (0.4), user_knowledge (0.35), nexe_web_ui (0.3)
4. **chat_memory.py** — Parsing MEM_SAVE, guardar conversación en memoria
5. **chat_engines/routing.py** — Selección motor (auto, ollama, mlx, llama_cpp)
6. **chat_engines/ollama.py** — Streaming Ollama con soporte thinking tokens
7. **chat_engines/mlx.py** — Streaming MLX con gestión CancelledError
8. **chat_engines/llama_cpp.py** — Streaming llama.cpp

**Marcadores streaming inyectados:**
- `[MODEL:nombre]`, `[MODEL_LOADING]`/`[MODEL_READY]`, `[RAG_AVG:score]`, `[RAG_ITEM:score|colección|fuente]`, `[MEM:N]`, `[COMPACT:N]`

## System Prompt

El system prompt define la personalidad y comportamiento de Nexe. Vive en `personality/server.toml` bajo `[personality.prompt]`.

**6 variantes:** 3 idiomas (ca/es/en) × 2 tiers (small para modelos ≤4B, full para 7B+).

**Lógica de selección** (`core/endpoints/chat.py` → `_get_system_prompt()`):
1. `{lang}_{tier}` (ej: `ca_full`) — de server.toml
2. `{lang}_full` — fallback tier
3. `en_full` — fallback idioma
4. Prompt mínimo hardcoded — último recurso

**Tier seleccionado vía:** variable de entorno `NEXE_PROMPT_TIER` (defecto: "full"). Idioma vía `NEXE_LANG`.

**Diseño clave:** Nexe es un asistente personal general con memoria persistente, no solo un asistente técnico de Server Nexe. El prompt dice: "Ayudas con cualquier cosa — conversación, proyectos, ideas, problemas técnicos, redacción, análisis." Si preguntan sobre Server Nexe, el contexto RAG proporciona documentación técnica.

**Inyección contexto RAG:** Se inyecta en el **mensaje del usuario** (no en el system prompt) para preservar el prefix cache de MLX/llama.cpp. El system prompt se mantiene estable entre mensajes.

**Etiquetas contexto RAG** deben coincidir entre el system prompt y el código que las inyecta:

| Colección | Etiqueta CA | Etiqueta ES | Etiqueta EN |
|-----------|----------|----------|----------|
| nexe_documentation | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | SYSTEM DOCUMENTATION |
| user_knowledge | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | TECHNICAL DOCUMENTATION |
| nexe_web_ui | MEMORIA DE L'USUARI | MEMORIA DEL USUARIO | USER MEMORY |

**Para cambiar el system prompt:** Editar `personality/server.toml` sección `[personality.prompt]`. No hace falta cambiar código. Reiniciar servidor para aplicar. El primer mensaje post-reinicio invalida el prefix cache (coste único).

## Integración i18n

- Servidor fuente de verdad para idioma (POST /ui/lang)
- 3 idiomas: ca, es, en
- System prompts: 6 versiones (ca/es/en × small/full)
- HTTPException: claves i18n con fallback (core/messages.py, plugins/*/messages.py)
- Web UI: applyI18n() con data attributes, CSP-safe (data-nexe-lang)

## Arquitectura Docker

- **Dockerfile:** Python 3.12-slim, Qdrant embebido (linux-amd64/arm64), usuario no-root (nexe)
- **docker-compose.yml:** Nexe + Ollama como servicios separados
- **docker-entrypoint.sh:** Arranque secuencial (Qdrant → Nexe), health check polling

## Arquitectura de Tests

- 3901 tests superados, 0 fallos, 35 omitidos
- Tests colocados con módulos (cada módulo tiene carpeta tests/)
- conftest.py raíz para fixtures compartidas
- Closures refactorizadas a funciones para patchability (decisión clave del refactoring)
