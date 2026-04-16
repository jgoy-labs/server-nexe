# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-overview
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "server-nexe is a local AI server with persistent RAG memory created by Jordi Goy. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Features: MEM_SAVE, i18n (ca/es/en), session isolation, encryption at-rest. Models by RAM tiers (8GB to 64GB), 2 installation methods (DMG, CLI), AI-ready documentation. macOS tested, Linux partial."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, models, installation, architecture, ollama, mlx, llama-cpp, encryption, ai-ready, jordi-goy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy"
expires: null
---

# server-nexe 0.9.7 — Local AI Server with Persistent Memory

**Version:** 0.9.7
**Default port:** 9119
**Author:** Jordi Goy (Barcelona)
**License:** Apache 2.0
**Platforms:** macOS (tested), Linux (partial)
**Website:** https://server-nexe.org | https://server-nexe.com

## What is server-nexe

server-nexe is a local AI server with persistent memory via RAG (Retrieval-Augmented Generation). It runs entirely on the user's machine. No cloud, no telemetry, no external API calls. Conversations, documents and embeddings never leave the device.

It is NOT npm nexe (a Node.js compiler). It is NOT a Windows server product. It is NOT a replacement for Ollama — it can use Ollama as one of its backends.

## Design Intent

What started as a learning-by-doing project and a giant spaghetti monster evolved, through several refactors, towards the goal of building a minimal, agnostic, modular core where security and memory are solved at the base — so that building on top is fast and comfortable — in human-AI collaboration. Whether that worked is for the community to say (the AI says yes, but what did you expect 🤪).

## Core capabilities

1. **100% Local and Private** — All inference, memory and storage happen on-device. Zero cloud dependency.
2. **Persistent RAG Memory** — Remembers context across sessions using Qdrant vector search with 768-dimensional embeddings. Three collections: nexe_documentation (system docs), user_knowledge (uploaded documents), personal_memory (conversation memory).
3. **Automatic Memory (MEM_SAVE)** — The model extracts facts from conversations automatically (name, job, preferences) and saves them to memory. Zero extra latency (same LLM call). Supports save, delete and recall intents in 3 languages.
4. **Multi-Backend Inference** — MLX (Apple Silicon native), llama.cpp (GGUF, universal with Metal), Ollama (bridge). Same OpenAI-compatible API, switchable backends.
5. **Modular Plugin System** — Security, web UI, RAG, each backend — everything is a plugin with independent manifests. Auto-discovered at startup.
6. **Multilingual (ca/es/en)** — Full i18n: UI, system prompts, RAG context labels, error messages, installer. Server is source of truth for language selection.
7. **Document Upload with Session Isolation** — Upload documents via Web UI. Indexed into user_knowledge with session_id metadata. Documents only visible within the session they were uploaded to.
8. **Encryption at Rest (default `auto`)** — AES-256-GCM encryption for SQLite (via SQLCipher), chat sessions (.enc), and RAG document text (TextStore). Activates automatically if sqlcipher3 is available. Key management via OS Keyring, env var, or file. Recently added — not yet battle-tested in production.
9. **Comprehensive Input Validation** — All endpoints (API and Web UI) have rate limiting, input validation (`validate_string_input`), and RAG context sanitization. 6 injection detectors with Unicode normalization. 47 jailbreak patterns.

## Technology stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ (bundled 3.12 in installer) |
| Web framework | FastAPI 0.115+ |
| Vector database | Qdrant (embedded, no external process required) |
| LLM backends | MLX, llama.cpp (llama-cpp-python), Ollama |
| Embeddings | nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2 (offline fallback) |
| Embedding dimensions | 768 |
| Encryption | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | OpenAI-compatible (/v1/chat/completions) |
| Authentication | X-API-Key (dual-key with rotation) |
| Security | 6 injection detectors + Unicode normalization, 47 jailbreak patterns, rate limiting, CSP headers |

## Architecture

```
server-nexe/
├── core/                  # FastAPI server, endpoints, CLI, crypto
│   ├── endpoints/         # REST API (chat split into 8 submodules)
│   ├── crypto/            # Encryption at rest (AES-256-GCM, SQLCipher)
│   ├── cli/               # CLI commands
│   ├── server/            # Factory pattern, lifespan
│   ├── ingest/            # Document ingestion (docs + knowledge)
│   └── lifespan*.py       # Startup/shutdown (split into 4 submodules)
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
├── tests/                 # Test suite (4770 test functions)
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

## Available models (by RAM tier)

16 empirically tested models, 4 tiers. Each tier has 2 recommended models (one for Ollama, one for MLX). Icons: 👁 = vision (images), 🧠 = thinking (step-by-step reasoning).

### tier_8 (8 GB RAM)
- 👁 🧠 **Gemma 3 4B** — Google DeepMind, 2025. Ollama + MLX. **Recommended MLX.**
- 👁 🧠 Qwen3.5 4B — Alibaba, 2026. Ollama only (MLX requires torch). **Recommended Ollama.**
- Qwen3 4B — Alibaba, 2025. Text, Ollama + MLX.

### tier_16 (16 GB RAM)
- 👁 🧠 **Gemma 4 E4B** — Google, 2026. Ollama + MLX. **Recommended MLX.**
- Salamandra 7B — BSC/AINA, 2025. Ollama + llama.cpp (GGUF). Best for Catalan.
- 👁 🧠 Qwen3.5 9B — Alibaba, 2026. Ollama only (MLX requires torch). **Recommended Ollama.**
- 👁 🧠 Gemma 3 12B — Google DeepMind, 2025. Ollama + MLX.

### tier_24 (24 GB RAM)
- 👁 🧠 **Gemma 4 31B** — Google, 2026. Ollama + MLX. **Recommended.**
- 🧠 **Qwen3 14B** — Alibaba, 2025. Ollama + MLX. **Recommended.**
- 🧠 GPT-OSS 20B — OpenAI, 2025. Ollama + MLX. Apache 2.0.

### tier_32 (32 GB RAM)
- 👁 🧠 Qwen3.5 27B — Alibaba, 2026. Ollama only (MLX requires torch).
- 👁 🧠 Gemma 3 27B — Google DeepMind, 2025. MLX + llama.cpp (GGUF).
- 🧠 DeepSeek R1 Distill 32B — DeepSeek, 2025. Ollama + llama.cpp (MLX unsupported: qwen2 arch).
- 👁 🧠 **Gemma 4 31B** — Google, 2026. Ollama + MLX. **Recommended MLX.**
- 👁 🧠 Qwen3.5 35B-A3B (MoE) — Alibaba, 2026. Ollama only.
- **ALIA-40B Instruct** — BSC, 2026. Ollama + llama.cpp (GGUF). 9 Iberian languages. **Recommended Iberian.**

### Backend compatibility notes (verified 2026-04-16)

- **Qwen3.5 family on MLX**: requires PyTorch and torchvision for VideoProcessor. Works perfectly via Ollama with no extra dependencies. Optional: `pip install torch torchvision` in the venv to unlock MLX (~2 GB). Affects: Qwen3.5 2B/4B/9B/27B/35B-A3B/122B-A10B.
- **DeepSeek R1 Distill on MLX**: error "Unsupported model: qwen2". Use Ollama or GGUF via llama.cpp.
- **Gemma 4 E4B on MLX**: may be unstable (repetition loops) in small models. Works well for vision.
- **Gemma 4 31B on MLX**: requires complete 8-bit download (~33 GB, 7 shards). Verify integrity.
- **ALIA-40B**: 42 GB Q8_0. Verify integrity after download (truncated tensor case detected).

Custom models also supported via Ollama (name) or Hugging Face (GGUF repo).

## Installation methods

### 1. macOS DMG Installer (recommended)
SwiftUI native wizard with 6 screens: welcome, destination folder, model selection (hardware detection by RAM tier), confirmation, progress, completion. Bundles Python 3.12.

### 2. CLI headless
```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go
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
| Windows | Not yet supported |

## Current limitations

- Local models are less capable than GPT-4, Claude, etc. — the trade-off is privacy.
- RAG requires initial indexing time. Empty memory = no RAG context.
- No multi-device sync.
- No model fine-tuning.
- API is partially compatible with OpenAI (missing /v1/embeddings, /v1/models).
- Encryption at rest defaults to `auto` (activates if sqlcipher3 available) — new, not yet battle-tested.
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
