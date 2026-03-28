# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "General overview of server-nexe 0.8.5 pre-release, a local AI server with persistent RAG memory. Covers what it is, backends (MLX, llama.cpp, Ollama), features (MEM_SAVE, i18n, Docker, session isolation, encryption at-rest), architecture, 17 available models, technology stack, installation methods, AI-ready documentation, and current platform support."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, models, installation, architecture, ollama, mlx, llama-cpp, encryption, ai-ready]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# server-nexe 0.8.5 pre-release — Local AI Server with Persistent Memory

**Version:** 0.8.5 pre-release
**Default port:** 9119
**Author:** Jordi Goy (Barcelona)
**License:** Apache 2.0
**Platforms:** macOS (tested), Linux (partial), Docker (supported)
**Website:** https://server-nexe.org | https://server-nexe.com

## What is server-nexe

server-nexe is a local AI server with persistent memory via RAG (Retrieval-Augmented Generation). It runs entirely on the user's machine. No cloud, no telemetry, no external API calls. Conversations, documents and embeddings never leave the device.

It is NOT npm nexe (a Node.js compiler). It is NOT a Windows server product. It is NOT a replacement for Ollama — it can use Ollama as one of its backends.

## Core capabilities

1. **100% Local and Private** — All inference, memory and storage happen on-device. Zero cloud dependency.
2. **Persistent RAG Memory** — Remembers context across sessions using Qdrant vector search with 768-dimensional embeddings. Three collections: nexe_documentation (system docs), user_knowledge (uploaded documents), nexe_web_ui (conversation memory).
3. **Automatic Memory (MEM_SAVE)** — The model extracts facts from conversations automatically (name, job, preferences) and saves them to memory. Zero extra latency (same LLM call). Supports save, delete and recall intents in 3 languages.
4. **Multi-Backend Inference** — MLX (Apple Silicon native), llama.cpp (GGUF, universal with Metal), Ollama (bridge). Same OpenAI-compatible API, switchable backends.
5. **Modular Plugin System** — Security, web UI, RAG, each backend — everything is a plugin with independent manifests. Auto-discovered at startup.
6. **Multilingual (ca/es/en)** — Full i18n: UI, system prompts, RAG context labels, error messages, installer. Server is source of truth for language selection.
7. **Document Upload with Session Isolation** — Upload documents via Web UI. Indexed into user_knowledge with session_id metadata. Documents only visible within the session they were uploaded to.
8. **Encryption at Rest (opt-in)** — AES-256-GCM encryption for SQLite (via SQLCipher), chat sessions (.enc), and RAG document text (TextStore). Qdrant payloads contain only vectors and IDs, no text. Key management via OS Keyring, env var, or file. Recently added — not yet battle-tested in production.
9. **Comprehensive Input Validation** — All endpoints (API and Web UI) have rate limiting, input validation (`validate_string_input`), and RAG context sanitization. 6 injection detectors with Unicode normalization. 69 jailbreak patterns.
10. **Docker Support** — Dockerfile + docker-compose.yml with embedded Qdrant. Python 3.12-slim, non-root user, Linux amd64/arm64.

## Technology stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ (bundled 3.12 in installer) |
| Web framework | FastAPI 0.128+ |
| Vector database | Qdrant (embedded binary) |
| LLM backends | MLX, llama.cpp (llama-cpp-python), Ollama |
| Embeddings | nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2 (offline fallback) |
| Embedding dimensions | 768 |
| Encryption | AES-256-GCM, HKDF-SHA256, SQLCipher (opt-in) |
| CLI | Click + Rich |
| API | OpenAI-compatible (/v1/chat/completions) |
| Authentication | X-API-Key (dual-key with rotation) |
| Security | 6 injection detectors + Unicode normalization, 69 jailbreak patterns, rate limiting, CSP headers |
| Containerization | Docker + docker-compose (Nexe + Ollama) |

## Architecture

```
server-nexe/
├── core/                  # FastAPI server, endpoints, CLI, crypto
│   ├── endpoints/         # REST API (chat split into 8 submodules)
│   ├── crypto/            # Encryption at rest (AES-256-GCM, SQLCipher)
│   ├── cli/               # CLI commands
│   ├── server/            # Factory pattern, lifespan
│   ├── ingest/            # Document ingestion (docs + knowledge)
│   └── lifespan*.py       # Startup/shutdown (split into 3 submodules)
├── plugins/               # Modular plugin system
│   ├── mlx_module/        # Apple Silicon backend
│   ├── llama_cpp_module/  # GGUF universal backend
│   ├── ollama_module/     # Ollama bridge + auto-start + VRAM cleanup
│   ├── security/          # Auth, rate limiting, injection detection
│   └── web_ui_module/     # Web interface (routes split into 6 submodules)
├── memory/                # RAG system (Qdrant + embeddings + persistence + TextStore)
├── knowledge/             # Documentation for RAG ingestion (ca/es/en)
├── personality/           # System prompts, module manager, i18n, server.toml
├── installer/             # SwiftUI wizard, DMG builder, tray app, headless installer
├── storage/               # Runtime data (models, logs, qdrant vectors)
├── tests/                 # Test suite (4131 test functions)
└── nexe                   # Main CLI executable
```

**Data flow:**
```
User -> CLI/API/Web UI -> Auth -> Rate Limit -> Validate Input -> Core -> Plugin -> LLM
                                                    |                           |
                                                    v                           v
                                             Memory (RAG) -> Qdrant      MEM_SAVE -> Qdrant
                                                    |
                                            _sanitize_rag_context
```

## AI-Ready Documentation

The knowledge base (`knowledge/`) is designed for both human and AI consumption:
- **Structured YAML frontmatter** for RAG ingestion (chunk_size, tags, priority)
- **12 thematic files** covering identity, architecture, API, security, testing, etc.
- **Available in English, Catalan, and Spanish**
- Point any AI assistant at this repository and it can understand the full architecture, create plugins, or contribute code

## Available models (17 in installer catalog)

### Small (8 GB RAM)
- Qwen3 1.7B (1.1 GB) — Alibaba, 2025
- Qwen3.5 2B (1.5 GB) — Alibaba, 2025 (Ollama only)
- Phi-3.5 Mini (2.4 GB) — Microsoft, 2024
- Salamandra 2B (1.5 GB) — BSC/AINA, 2024, optimized for Catalan
- Qwen3 4B (2.5 GB) — Alibaba, 2025

### Medium (12-16 GB RAM)
- Mistral 7B (4.1 GB) — Mistral AI, 2023
- Salamandra 7B (4.9 GB) — BSC/AINA, 2024, best for Catalan
- Llama 3.1 8B (4.7 GB) — Meta, 2024
- Qwen3 8B (5.0 GB) — Alibaba, 2025
- Gemma 3 12B (7.6 GB) — Google DeepMind, 2025

### Large (32+ GB RAM)
- Qwen3.5 27B (17 GB) — Alibaba, 2025 (Ollama only)
- Qwen3 32B (20 GB) — Alibaba, 2025, hybrid reasoning
- Gemma 3 27B (17 GB) — Google DeepMind, 2025
- DeepSeek R1 32B (20 GB) — DeepSeek, 2025, advanced reasoning
- Llama 3.1 70B (40 GB) — Meta, 2024

Custom models also supported via Ollama (name) or Hugging Face (GGUF repo).

## Installation methods

### 1. macOS DMG Installer (recommended)
SwiftUI native wizard with 6 screens: welcome, destination folder, model selection (17 models with hardware detection), confirmation, progress, completion. Bundles Python 3.12.

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

## Quick start

```bash
./nexe go                    # Start server -> http://127.0.0.1:9119
./nexe chat                  # Interactive CLI chat
./nexe chat --rag            # Chat with RAG memory
./nexe memory store "text"   # Save to memory
./nexe memory recall "query" # Recall from memory
./nexe status                # System status
./nexe knowledge ingest      # Index documents
./nexe encryption status     # Check encryption status
```

Web UI: `http://127.0.0.1:9119/ui`
API docs: `http://127.0.0.1:9119/docs`
Health check: `http://127.0.0.1:9119/health`

Authentication required: `X-API-Key` header with value from `.env` (`NEXE_PRIMARY_API_KEY`).

## Platform support

| Platform | Status |
|----------|--------|
| macOS Apple Silicon | Tested (all 3 backends) |
| macOS Intel | Tested (llama.cpp + Ollama) |
| Linux x86_64 | Partial (unit tests pass, CI green, not production-tested) |
| Linux ARM64 | Docker supported |
| Windows | Not yet supported |

## Current limitations

- Local models are less capable than GPT-4, Claude, etc. — the trade-off is privacy.
- RAG requires initial indexing time. Empty memory = no RAG context.
- No multi-device sync.
- No model fine-tuning.
- API is partially compatible with OpenAI (missing /v1/embeddings, /v1/models).
- Encryption at rest is opt-in and new — not yet battle-tested.
- Single developer project with AI-assisted audits, not formally audited.

## Related documentation

Other knowledge documents in this folder:
- IDENTITY.md — What server-nexe is and is NOT (disambiguation)
- INSTALLATION.md — Detailed installation guide
- USAGE.md — Usage examples and practical cases
- ARCHITECTURE.md — Technical architecture in detail
- RAG.md — How the memory system works
- PLUGINS.md — Plugin system
- API.md — REST API reference
- SECURITY.md — Security and authentication
- LIMITATIONS.md — Technical limitations
- ERRORS.md — Common errors and solutions
- TESTING.md — Test strategy and coverage

## Links

- Source code: https://github.com/jgoy-labs/server-nexe
- Documentation: https://server-nexe.org
- Commercial site: https://server-nexe.com
- Author: https://jgoy.net
- Support: https://github.com/sponsors/jgoy-labs | https://ko-fi.com/jgoylabs
