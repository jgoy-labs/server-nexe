# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Vision general de server-nexe 0.8.5 pre-release, un servidor de IA local con memoria RAG persistente. Cubre que es, backends (MLX, llama.cpp, Ollama), funcionalidades (MEM_SAVE, i18n, Docker, aislamiento de sesiones, encriptacion en reposo), arquitectura, 15 modelos disponibles, stack tecnologico, metodos de instalacion, documentacion AI-ready, y soporte de plataformas actual."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, models, installation, architecture, ollama, mlx, llama-cpp, encryption, ai-ready]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# server-nexe 0.8.5 pre-release — Servidor de IA local con memoria persistente

**Version:** 0.8.5 pre-release
**Puerto por defecto:** 9119
**Autor:** Jordi Goy (Barcelona)
**Licencia:** Apache 2.0
**Plataformas:** macOS (probado), Linux (parcial), Docker (soportado)
**Web:** https://server-nexe.org | https://server-nexe.com

## Que es server-nexe

server-nexe es un servidor de IA local con memoria persistente via RAG (Retrieval-Augmented Generation). Se ejecuta completamente en la maquina del usuario. Sin nube, sin telemetria, sin llamadas a APIs externas. Las conversaciones, documentos y embeddings nunca salen del dispositivo.

NO es npm nexe (un compilador de Node.js). NO es un producto de servidor Windows. NO es un sustituto de Ollama — puede usar Ollama como uno de sus backends.

## Capacidades principales

1. **100% Local y privado** — Toda la inferencia, memoria y almacenamiento ocurren en el dispositivo. Cero dependencia de la nube.
2. **Memoria RAG persistente** — Recuerda el contexto entre sesiones usando busqueda vectorial Qdrant con embeddings de 768 dimensiones. Tres colecciones: nexe_documentation (documentacion del sistema), user_knowledge (documentos subidos), nexe_web_ui (memoria de conversaciones).
3. **Memoria automatica (MEM_SAVE)** — El modelo extrae hechos de las conversaciones automaticamente (nombre, trabajo, preferencias) y los guarda en memoria. Cero latencia adicional (misma llamada LLM). Soporta intenciones de guardar, borrar y recuperar en 3 idiomas.
4. **Inferencia multi-backend** — MLX (nativo Apple Silicon), llama.cpp (GGUF, universal con Metal), Ollama (bridge). Misma API compatible con OpenAI, backends intercambiables.
5. **Sistema modular de plugins** — Seguridad, web UI, RAG, cada backend — todo es un plugin con manifests independientes. Auto-descubrimiento al arrancar.
6. **Multilingue (ca/es/en)** — i18n completo: UI, system prompts, etiquetas de contexto RAG, mensajes de error, instalador. El servidor es la fuente de verdad para la seleccion de idioma.
7. **Upload de documentos con aislamiento de sesion** — Sube documentos via la Web UI. Indexados en user_knowledge con metadatos session_id. Los documentos solo son visibles dentro de la sesion donde fueron subidos.
8. **Encriptacion en reposo (opt-in)** — Encriptacion AES-256-GCM para SQLite (via SQLCipher), sesiones de chat (.enc), y texto de documentos RAG (TextStore). Los payloads de Qdrant solo contienen vectores e IDs, sin texto. Gestion de claves via OS Keyring, variable de entorno, o fichero. Anadida recientemente — aun no probada en batalla en produccion.
9. **Validacion de entrada completa** — Todos los endpoints (API y Web UI) tienen rate limiting, validacion de entrada (`validate_string_input`), y sanitizacion de contexto RAG. 6 detectores de inyeccion con normalizacion Unicode. 47 patrones de jailbreak.
10. **Soporte Docker** — Dockerfile + docker-compose.yml con Qdrant embebido. Python 3.12-slim, usuario non-root, Linux amd64/arm64.

## Stack tecnologico

| Componente | Tecnologia |
|-----------|-----------|
| Lenguaje | Python 3.11+ (3.12 bundled en instalador) |
| Framework web | FastAPI 0.115+ |
| Base de datos vectorial | Qdrant (binario embebido) |
| Backends LLM | MLX, llama.cpp (llama-cpp-python), Ollama |
| Embeddings | nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2 (fallback offline) |
| Dimensiones de embedding | 768 |
| Encriptacion | AES-256-GCM, HKDF-SHA256, SQLCipher (opt-in) |
| CLI | Click + Rich |
| API | Compatible con OpenAI (/v1/chat/completions) |
| Autenticacion | X-API-Key (dual-key con rotacion) |
| Seguridad | 6 detectores de inyeccion + normalizacion Unicode, 47 patrones de jailbreak, rate limiting, cabeceras CSP |
| Contenedores | Docker + docker-compose (Nexe + Ollama) |

## Arquitectura

```
server-nexe/
├── core/                  # Servidor FastAPI, endpoints, CLI, crypto
│   ├── endpoints/         # REST API (chat dividido en 8 submodulos)
│   ├── crypto/            # Encriptacion en reposo (AES-256-GCM, SQLCipher)
│   ├── cli/               # Comandos CLI
│   ├── server/            # Patron factory, lifespan
│   ├── ingest/            # Ingestion de documentos (docs + knowledge)
│   └── lifespan*.py       # Arranque/apagado (dividido en 3 submodulos)
├── plugins/               # Sistema modular de plugins
│   ├── mlx_module/        # Backend Apple Silicon
│   ├── llama_cpp_module/  # Backend universal GGUF
│   ├── ollama_module/     # Bridge Ollama + auto-arranque + limpieza VRAM
│   ├── security/          # Auth, rate limiting, deteccion de inyecciones
│   └── web_ui_module/     # Interfaz web (rutas divididas en 6 submodulos)
├── memory/                # Sistema RAG (Qdrant + embeddings + persistencia + TextStore)
├── knowledge/             # Documentacion para ingestion RAG (ca/es/en)
├── personality/           # System prompts, module manager, i18n, server.toml
├── installer/             # Wizard SwiftUI, constructor DMG, tray app, instalador headless
├── storage/               # Datos en tiempo de ejecucion (modelos, logs, vectores qdrant)
├── tests/                 # Suite de tests (4143 funciones de test)
└── nexe                   # Ejecutable CLI principal
```

**Flujo de datos:**
```
Usuario -> CLI/API/Web UI -> Auth -> Rate Limit -> Validar Entrada -> Core -> Plugin -> LLM
                                                       |                           |
                                                       v                           v
                                                Memory (RAG) -> Qdrant      MEM_SAVE -> Qdrant
                                                       |
                                               _sanitize_rag_context
```

## Documentacion AI-Ready

La base de conocimiento (`knowledge/`) esta disenada tanto para consumo humano como de IA:
- **Frontmatter YAML estructurado** para ingestion RAG (chunk_size, tags, priority)
- **12 ficheros tematicos** cubriendo identidad, arquitectura, API, seguridad, pruebas, etc.
- **Disponible en ingles, catalan y espanol**
- Apunta cualquier asistente de IA a este repositorio y podra entender la arquitectura completa, crear plugins o contribuir codigo

## Modelos disponibles (15 en el catalogo del instalador)

### Pequenos (8 GB RAM)
- Qwen3 1.7B (1.1 GB) — Alibaba, 2025
- Qwen3.5 2B (1.5 GB) — Alibaba, 2025 (solo Ollama)
- Phi-3.5 Mini (2.4 GB) — Microsoft, 2024
- Salamandra 2B (1.5 GB) — BSC/AINA, 2024, optimizado para catalan
- Qwen3 4B (2.5 GB) — Alibaba, 2025

### Medianos (12-16 GB RAM)
- Mistral 7B (4.1 GB) — Mistral AI, 2023
- Salamandra 7B (4.9 GB) — BSC/AINA, 2024, el mejor para catalan
- Llama 3.1 8B (4.7 GB) — Meta, 2024
- Qwen3 8B (5.0 GB) — Alibaba, 2025
- Gemma 3 12B (7.6 GB) — Google DeepMind, 2025

### Grandes (32+ GB RAM)
- Qwen3.5 27B (17 GB) — Alibaba, 2025 (solo Ollama)
- Qwen3 32B (20 GB) — Alibaba, 2025, razonamiento hibrido
- Gemma 3 27B (17 GB) — Google DeepMind, 2025
- DeepSeek R1 32B (20 GB) — DeepSeek, 2025, razonamiento avanzado
- Llama 3.1 70B (40 GB) — Meta, 2024

Tambien se soportan modelos personalizados via Ollama (nombre) o Hugging Face (repo GGUF).

## Metodos de instalacion

### 1. Instalador DMG macOS (recomendado)
Wizard nativo SwiftUI con 6 pantallas: bienvenida, carpeta de destino, seleccion de modelo (15 modelos con deteccion de hardware), confirmacion, progreso, finalizacion. Incluye Python 3.12 bundled.

### 2. CLI headless
```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go
```

### 3. Docker
```bash
docker-compose up
```

## Inicio rapido

```bash
./nexe go                    # Arrancar servidor -> http://127.0.0.1:9119
./nexe chat                  # Chat interactivo por CLI
./nexe chat --rag            # Chat con memoria RAG
./nexe memory store "texto"  # Guardar en memoria
./nexe memory recall "query" # Recuperar de memoria
./nexe status                # Estado del sistema
./nexe knowledge ingest      # Indexar documentos
./nexe encryption status     # Comprobar estado de encriptacion
```

Web UI: `http://127.0.0.1:9119/ui`
Documentacion API: `http://127.0.0.1:9119/docs`
Health check: `http://127.0.0.1:9119/health`

Autenticacion requerida: cabecera `X-API-Key` con el valor de `.env` (`NEXE_PRIMARY_API_KEY`).

## Soporte de plataformas

| Plataforma | Estado |
|----------|--------|
| macOS Apple Silicon | Probado (los 3 backends) |
| macOS Intel | Probado (llama.cpp + Ollama) |
| Linux x86_64 | Parcial (tests unitarios pasan, CI verde, no probado en produccion) |
| Linux ARM64 | Docker soportado |
| Windows | Aun no soportado |

## Limitaciones actuales

- Los modelos locales son menos capaces que GPT-4, Claude, etc. — la contrapartida es la privacidad.
- RAG requiere tiempo de indexacion inicial. Memoria vacia = sin contexto RAG.
- Sin sincronizacion multi-dispositivo.
- Sin fine-tuning de modelos.
- La API es parcialmente compatible con OpenAI (faltan /v1/embeddings, /v1/models).
- La encriptacion en reposo es opt-in y nueva — aun no probada en batalla.
- Proyecto de un solo desarrollador con auditorias asistidas por IA, no auditado formalmente.

## Documentacion relacionada

Otros documentos de knowledge en esta carpeta:
- IDENTITY.md — Que es server-nexe y que NO es (desambiguacion)
- INSTALLATION.md — Guia de instalacion detallada
- USAGE.md — Ejemplos de uso y casos practicos
- ARCHITECTURE.md — Arquitectura tecnica en detalle
- RAG.md — Como funciona el sistema de memoria
- PLUGINS.md — Sistema de plugins
- API.md — Referencia de la REST API
- SECURITY.md — Seguridad y autenticacion
- LIMITATIONS.md — Limitaciones tecnicas
- ERRORS.md — Errores comunes y soluciones
- TESTING.md — Estrategia de pruebas y cobertura

## Enlaces

- Codigo fuente: https://github.com/jgoy-labs/server-nexe
- Documentacion: https://server-nexe.org
- Sitio comercial: https://server-nexe.com
- Autor: https://jgoy.net
- Soporte: https://github.com/sponsors/jgoy-labs | https://ko-fi.com/jgoylabs
