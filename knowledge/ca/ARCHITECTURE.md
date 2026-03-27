# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-architecture

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Arquitectura interna de server-nexe 0.8.2. Disseny de cinc capes: Interfícies, Core (factory FastAPI, endpoints dividits, lifespan dividit), Plugins (5 mòduls amb auto-descobriment), Serveis Base (memòria RAG 3 capes), Storage. Cobreix refactoring modular (4 monòlits dividits en 20+ submòduls), module manager amb lazy init, integració i18n i suport Docker."
tags: [arquitectura, fastapi, plugins, qdrant, memoria, lifespan, cli, disseny, factory, moduls, refactoring, docker, i18n, module-manager]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Arquitectura — server-nexe 0.8.2

## Arquitectura de Cinc Capes

```
INTERFÍCIES       CLI (./nexe) | API REST | Web UI
      |
CORE              Servidor FastAPI, endpoints, middleware, lifespan
      |
PLUGINS           MLX | llama.cpp | Ollama | Security | Web UI
      |
SERVEIS BASE      Memory (RAG) | Qdrant | Embeddings | SQLite
      |
STORAGE           models/ | qdrant/ | vectors/ | logs/ | cache/
```

Principis de disseny: modularitat, backends com a plugins, API-first, RAG natiu de primera classe, simplicitat.

## Estructura de Directoris (post-refactoring març 2026)

Quatre fitxers monolítics es van dividir en 20+ submòduls durant el refactoring de tech debt de març 2026:
- chat.py (1187 línies) dividit en 8 submòduls
- routes.py (974 línies) dividit en 6 submòduls
- lifespan.py (681 línies) dividit en 3 submòduls
- tray.py (707 línies) dividit en 2 submòduls

```
server-nexe/
├── core/
│   ├── app.py                    # Punt d'entrada (delega a factory)
│   ├── config.py                 # Càrrega configuració TOML + .env
│   ├── lifespan.py               # Orquestrador cicle de vida (416 línies)
│   ├── lifespan_services.py      # Auto-start serveis (Qdrant, Ollama)
│   ├── lifespan_tokens.py        # Generació bootstrap token
│   ├── lifespan_ollama.py        # Gestió cicle de vida Ollama
│   ├── middleware.py              # CORS, CSRF, logging, capçaleres seguretat
│   ├── security_headers.py       # Capçaleres OWASP (CSP, HSTS, X-Frame)
│   ├── messages.py               # Claus i18n per core
│   ├── bootstrap_tokens.py       # Sistema bootstrap token (persistit DB)
│   ├── models.py                 # Models Pydantic
│   │
│   ├── endpoints/                # API REST
│   │   ├── chat.py               # POST /v1/chat/completions (orquestrador)
│   │   ├── chat_schemas.py       # Models Pydantic (Message, ChatCompletionRequest)
│   │   ├── chat_sanitization.py  # Sanitització tokens SSE, truncament context
│   │   ├── chat_rag.py           # Constructor context RAG (3 col·leccions)
│   │   ├── chat_memory.py        # Guardar conversa a memòria (MEM_SAVE)
│   │   ├── chat_engines/         # Generadors per backend
│   │   │   ├── routing.py        # Lògica selecció motor
│   │   │   ├── ollama.py         # Generador streaming Ollama
│   │   │   ├── mlx.py            # Generador streaming MLX
│   │   │   └── llama_cpp.py      # Generador streaming llama.cpp
│   │   ├── root.py               # GET /, /health, /api/info
│   │   ├── bootstrap.py          # POST /bootstrap/init
│   │   ├── modules.py            # GET /modules
│   │   ├── system.py             # POST /admin/system/*
│   │   └── v1.py                 # Wrapper endpoints v1
│   │
│   ├── server/                   # Patró factory (singleton cached)
│   │   ├── factory.py            # Façana principal create_app() amb double-check locking
│   │   ├── factory_app.py        # Crear instància FastAPI
│   │   ├── factory_state.py      # Setup app.state
│   │   ├── factory_security.py   # SecurityLogger, validació producció
│   │   ├── factory_i18n.py       # Setup i18n + config
│   │   ├── factory_modules.py    # Descobriment i càrrega de mòduls
│   │   ├── factory_routers.py    # Registre routers core
│   │   ├── runner.py             # Runner Uvicorn
│   │   └── exception_handlers.py # Patrons gestió d'errors
│   │
│   ├── cli/                      # CLI Click amb router dinàmic
│   │   ├── cli.py                # DynamicGroup (intercepta CLIs de mòduls)
│   │   ├── router.py             # CLIRouter (descobreix CLIs via manifest.toml)
│   │   ├── chat_cli.py           # Comanda chat interactiu
│   │   └── client.py             # Client HTTP per API local
│   │
│   ├── ingest/                   # Ingesta de documents
│   │   ├── ingest_docs.py        # docs/ → nexe_documentation (500/50 chars)
│   │   └── ingest_knowledge.py   # knowledge/ → user_knowledge (1500/200 chars)
│   │
│   ├── metrics/                  # Prometheus /metrics
│   ├── resilience/               # Circuit breaker, retry
│   └── paths/                    # Resolució de camins
│
├── plugins/                      # 5 mòduls plugin (auto-descoberts)
│   ├── mlx_module/               # Backend Apple Silicon (MLX)
│   │   ├── module.py             # MLXModule + is_model_loaded()
│   │   ├── manifest.toml         # Metadades del mòdul
│   │   └── manifest.py           # Router FastAPI
│   │
│   ├── llama_cpp_module/         # Backend GGUF universal
│   │   ├── module.py             # LlamaCppModule + is_model_loaded()
│   │   └── manifest.toml
│   │
│   ├── ollama_module/            # Bridge Ollama
│   │   ├── module.py             # OllamaModule + auto-start + VRAM cleanup
│   │   ├── cli/                  # Subcomandes CLI Ollama
│   │   └── manifest.toml
│   │
│   ├── security/                 # Auth + detecció d'injeccions
│   │   ├── core/                 # auth.py, rate_limiting.py, injection_detectors.py
│   │   ├── sanitizer/            # 69 patrons jailbreak
│   │   ├── security_logger/      # Logging auditoria RFC5424
│   │   └── manifest.toml
│   │
│   └── web_ui_module/            # Interfície web
│       ├── api/                  # Routes dividits (6 fitxers)
│       │   ├── routes_auth.py    # Auth, backends, POST /ui/lang, Ollama auto-start
│       │   ├── routes_chat.py    # Streaming xat, MEM_SAVE, RAG, thinking tokens
│       │   ├── routes_files.py   # Pujada documents (aïllament per sessió)
│       │   ├── routes_memory.py  # Guardar/recordar memòria
│       │   ├── routes_sessions.py # Gestió sessions
│       │   └── routes_static.py  # Fitxers estàtics, cache-busting, i18n CSP-safe
│       ├── core/
│       │   ├── memory_helper.py  # Detecció intencions, auto-save, poda (716 línies)
│       │   └── session_manager.py
│       ├── messages.py           # Claus i18n per web_ui
│       ├── ui/                   # HTML, CSS, JS
│       └── manifest.toml
│
├── memory/                       # Sistema RAG 3 subcapes
│   ├── embeddings/               # Generació vectors (Ollama + sentence-transformers)
│   ├── memory/                   # Gestió memòria (FlashMemory + RAMContext + Persistence)
│   │   └── constants.py          # DEFAULT_VECTOR_SIZE = 768
│   └── rag/                      # Orquestració RAG
│
├── personality/                  # Configuració del sistema
│   ├── server.toml               # Config principal (prompts, mòduls, models)
│   ├── i18n/                     # Gestor i18n + traduccions (ca/es/en)
│   └── module_manager/           # FONT ÚNICA DE VERITAT per tots els mòduls
│
├── installer/                    # Instal·lador macOS
│   ├── swift-wizard/             # Wizard SwiftUI (15 fitxers Swift, 6 pantalles)
│   ├── build_dmg.sh              # Constructor DMG amb signatura
│   ├── tray.py                   # App system tray (419 línies)
│   ├── tray_translations.py      # i18n tray (ca/es/en)
│   └── tray_uninstaller.py       # Desinstal·lador amb backup
│
├── knowledge/                    # Docs per ingesta RAG (ca/es/en)
├── storage/                      # Dades runtime (no a git)
├── tests/                        # 3901 tests, 0 fallades
├── Dockerfile                    # Python 3.12-slim + Qdrant embedit
├── docker-compose.yml            # Serveis Nexe + Ollama
└── nexe                          # Executable CLI
```

## Patró Factory

L'app es crea via un singleton factory amb double-check locking:

- `core/app.py` crida `create_app()` de `core/server/factory.py`
- Primera crida (~0.5s): carrega i18n, config, descobreix mòduls, registra routers
- Crides cached (<10ms): retorna instància existent
- Factory dividit en 7 submòduls
- `reset_app_cache()` disponible per tests

## Gestor de Cicle de Vida (Lifespan)

Gestiona l'arrencada i aturada del servidor. Dividit en 3 submòduls:

**Seqüència d'arrencada:**
1. Carregar config de server.toml
2. Inicialitzar APIIntegrator (sistema de personalitat)
3. Auto-start Qdrant (binari embedit, port 6333)
4. Auto-start Ollama (si disponible, mode segon pla)
5. Carregar mòduls de memòria (Memory → RAG → Embeddings, ordre correcte)
6. Inicialitzar mòduls plugin (MLX, llama.cpp, Ollama, Security, Web UI)
7. Auto-ingestar knowledge/ (només primera execució, fitxer marcador)
8. Generar bootstrap token (128-bit, persistent SQLite, TTL 30min)

**Seqüència d'aturada:**
1. Descarregar models Ollama (VRAM cleanup via keep_alive:0)
2. Tancar connexions Qdrant
3. Terminar processos fills
4. Sincronitzar estat a disc

## Module Manager

`personality/module_manager/` és la FONT ÚNICA DE VERITAT per a tots els mòduls. NO existeix `plugins/base.py` ni `plugins/registry.py`.

**Components:** ConfigManager, PathDiscovery, ModuleDiscovery (escaneja manifest.toml), ModuleLoader, ModuleRegistry, ModuleLifecycleManager (lazy asyncio.Lock per fix deadlock Python 3.12), SystemLifecycleManager.

**Format manifest.toml** (cada plugin en té un):
```toml
[module]
name = "nom_modul"
version = "0.8.2"
type = "local_llm_option"

[module.entry]
module = "plugins.nom_modul.module"
class = "ClasseModul"

[module.router]
prefix = "/modul"
```

## Arquitectura CLI

CLI basat en Click amb router dinàmic:
- `DynamicGroup` intercepta comandes no definides
- `CLIRouter` descobreix CLIs de mòduls via manifest.toml
- CLIs de mòduls s'executen en subprocés (aïllament)
- Comandes: go, chat, status, modules, memory, knowledge, rag

## Arquitectura Memòria (3 subcapes)

```
Capa RAG (memory/rag/)                — orquestra cerca multi-col·lecció
      |
Capa Memory (memory/memory/)          — FlashMemory + RAMContext + Persistence
      |
Capa Embeddings (memory/embeddings/)  — generació vectors + interfície Qdrant
```

- FlashMemory: cache temporal amb TTL (1800s)
- RAMContext: context sessió actual
- PersistenceManager: metadades SQLite + vectors Qdrant
- Tots els vectors: 768 dimensions (DEFAULT_VECTOR_SIZE centralitzat)

## Arquitectura Endpoint Chat

`POST /v1/chat/completions` dividit en 8 submòduls:

1. **chat_schemas.py** — Models Pydantic (use_rag=True per defecte)
2. **chat_sanitization.py** — Sanitització SSE, truncament context (MAX_CONTEXT_CHARS=24000)
3. **chat_rag.py** — Constructor context RAG: cerca nexe_documentation (0.4), user_knowledge (0.35), nexe_web_ui (0.3)
4. **chat_memory.py** — Parsing MEM_SAVE, guardar conversa a memòria
5. **chat_engines/routing.py** — Selecció motor (auto, ollama, mlx, llama_cpp)
6. **chat_engines/ollama.py** — Streaming Ollama amb suport thinking tokens
7. **chat_engines/mlx.py** — Streaming MLX amb gestió CancelledError
8. **chat_engines/llama_cpp.py** — Streaming llama.cpp

**Marcadors streaming injectats:**
- `[MODEL:nom]`, `[MODEL_LOADING]`/`[MODEL_READY]`, `[RAG_AVG:score]`, `[RAG_ITEM:score|col·lecció|font]`, `[MEM:N]`, `[COMPACT:N]`

## System Prompt

El system prompt defineix la personalitat i comportament de Nexe. Viu a `personality/server.toml` sota `[personality.prompt]`.

**6 variants:** 3 idiomes (ca/es/en) × 2 tiers (small per models ≤4B, full per 7B+).

**Lògica de selecció** (`core/endpoints/chat.py` → `_get_system_prompt()`):
1. `{lang}_{tier}` (ex: `ca_full`) — de server.toml
2. `{lang}_full` — fallback tier
3. `en_full` — fallback idioma
4. Prompt mínim hardcoded — últim recurs

**Tier seleccionat via:** variable d'entorn `NEXE_PROMPT_TIER` (defecte: "full"). Idioma via `NEXE_LANG`.

**Disseny clau:** Nexe és un assistent personal general amb memòria persistent, no només un assistent tècnic de Server Nexe. El prompt diu: "Ajudes amb qualsevol cosa — conversa, projectes, idees, problemes tècnics, redacció, anàlisi." Si pregunten sobre Server Nexe, el context RAG proporciona documentació tècnica.

**Injecció context RAG:** S'injecta al **missatge de l'usuari** (no al system prompt) per preservar el prefix cache de MLX/llama.cpp. El system prompt es manté estable entre missatges.

**Etiquetes context RAG** han de coincidir entre el system prompt i el codi que les injecta:

| Col·lecció | Etiqueta CA | Etiqueta ES | Etiqueta EN |
|-----------|----------|----------|----------|
| nexe_documentation | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | SYSTEM DOCUMENTATION |
| user_knowledge | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | TECHNICAL DOCUMENTATION |
| nexe_web_ui | MEMORIA DE L'USUARI | MEMORIA DEL USUARIO | USER MEMORY |

**Per canviar el system prompt:** Editar `personality/server.toml` secció `[personality.prompt]`. No cal canviar codi. Reiniciar servidor per aplicar. El primer missatge post-reinici invalida el prefix cache (cost únic).

## Integració i18n

- Servidor font de veritat per idioma (POST /ui/lang)
- 3 idiomes: ca, es, en
- System prompts: 6 versions (ca/es/en × small/full)
- HTTPException: claus i18n amb fallback (core/messages.py, plugins/*/messages.py)
- Web UI: applyI18n() amb data attributes, CSP-safe (data-nexe-lang)

## Arquitectura Docker

- **Dockerfile:** Python 3.12-slim, Qdrant embedit (linux-amd64/arm64), usuari no-root (nexe)
- **docker-compose.yml:** Nexe + Ollama com serveis separats
- **docker-entrypoint.sh:** Arrencada seqüencial (Qdrant → Nexe), health check polling

## Arquitectura de Tests

- 3901 tests superats, 0 fallades, 35 omesos
- Tests col·locats amb mòduls (cada mòdul té carpeta tests/)
- conftest.py arrel per fixtures compartides
- Closures refactoritzades a funcions per patchability (decisió clau del refactoring)
