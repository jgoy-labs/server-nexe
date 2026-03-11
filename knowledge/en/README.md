# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "General overview of NEXE 0.8, a local AI server with persistent memory. Covers backends (MLX, llama.cpp, Ollama), features, architecture, available models, use cases and roadmap. Educational project by Jordi Goy."
tags: [overview, nexe, backends, rag, memory, arquitectura, roadmap, models, instal·lació]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# NEXE 0.8 - Local AI Server with Memory

**Version:** 0.8.0
**Default port:** 9119
**Author:** Jordi Goy
**Collaboration:** Developed with AI tools assistance
**License:** Apache 2.0

## What is NEXE?

NEXE is a **personal learning project** (learning by doing) that explores how to build an Artificial Intelligence server that runs entirely locally, with one key differentiating feature: **integrated persistent memory** via RAG (Retrieval-Augmented Generation).

**Important:** It is not a finished product and does not attempt to compete with mature tools like ChatGPT, Claude, Ollama or LM Studio. It is an experiment to learn about:
- RAG systems and vector memory
- Integration of different LLM backends
- Modular architecture with plugins
- REST APIs and servers with FastAPI
- Embeddings management and semantic search

## Why NEXE if Ollama/LM Studio already exist?

NEXE **does not replace** Ollama, LM Studio or similar tools. In fact, it can use Ollama as a backend!

**Available backends:**
1. **MLX** - Native for Apple Silicon (mlx-community)
2. **llama.cpp** - Universal, with Metal acceleration on Mac
3. **Ollama** - Bridge to Ollama if you already have it installed

**Future backends under consideration:**
- Other engines as needed

**What does NEXE bring?**
- An **experimental RAG layer** on top of these backends
- **Persistent memory** system between conversations
- Unified API to switch backends easily
- Learning by building a complete system
- [Future] Experimenting with AI coding tools + local RAG integration

## Project status

### ✅ What works (tested)

**Platform:**
- macOS (Apple Silicon and Intel) - Only tested platform

**LLM backends:**
- MLX backend for Apple Silicon
- llama.cpp with Metal
- Bridge to Ollama

**Features:**
- RAG system with Qdrant (3 specialized collections)
- REST API partially compatible with OpenAI (/v1/chat/completions)
- Interactive CLI (`./nexe`) with subcommands
- Basic experimental Web UI
- Security system (dual-key auth, rate limiting, sanitization)
- Document indexing (knowledge ingest)
- Persistent memory (768-dim embeddings)

### ⚠️ What is theoretical (code implemented but NOT tested)

- **Linux x86_64** - Should work with llama.cpp, NOT tested
- **Windows** - Theoretically possible with llama.cpp, NOT tested

### 🔨 What is in development or pending

- **Advanced Web UI** - The current UI is very basic
- **Advanced document management** - Better indexing, metadata, etc.

## Quick installation

**Minimum requirements:**
- macOS 12+ (recommended: macOS 14+ with Apple Silicon)
- Python 3.9+ (recommended: 3.11+)
- 8 GB RAM (recommended: 16+ GB)
- 10 GB free disk space

**Guided installation:**

```bash
cd server-nexe
./setup.sh
```

The interactive installer will guide you through:
1. Detecting your hardware (CPU, RAM, GPU)
2. Selecting the appropriate backend (MLX, llama.cpp or Ollama)
3. Choosing an LLM model based on your available RAM
4. Configuring the system
5. Starting the server automatically

## Quick start

### Start the server

```bash
./nexe go
```

The server will start on port 9119:
- API: `http://localhost:9119`
- Web UI: `http://localhost:9119/ui`
- Health check: `http://localhost:9119/health`
- API documentation: `http://localhost:9119/docs`

**Note:** The API requires authentication with the `X-API-Key` header (configured in `.env` as `NEXE_PRIMARY_API_KEY`).

### Interactive chat

```bash
# Simple chat
./nexe chat

# Chat with RAG memory enabled
./nexe chat --rag
```

### Memory management

```bash
# Save information to memory
./nexe memory store "La capital de Catalunya és Barcelona"

# Retrieve from memory
./nexe memory recall "capital Catalunya"

# System status
./nexe status

# Memory statistics
./nexe memory stats
```

## Basic architecture

```
server-nexe/
├── core/              # Servidor FastAPI + endpoints + CLI
│   ├── endpoints/     # API REST
│   ├── cli/           # Comandes CLI
│   ├── server/        # Factory, lifespan
│   └── loader/        # Càrrega de models
├── plugins/           # Sistema de plugins (backends modulars)
│   ├── mlx_module/
│   ├── llama_cpp_module/
│   ├── ollama_module/
│   ├── security/
│   └── web_ui_module/
├── memory/            # Sistema RAG (Qdrant + SQLite + embeddings)
├── knowledge/         # Documents auto-ingestats (aquesta carpeta!)
├── personality/       # Personalitat i comportament de l'IA
└── nexe               # Executable CLI principal
```

**Basic flow:**
```
User → CLI/API → Core → Plugin (MLX/llama.cpp/Ollama) → LLM Model
                   ↓
                 Memory (RAG) → Qdrant → Augmented context
```

## Available models

The installer offers several models depending on your available RAM:

### Small models (8GB RAM)
- **Phi-3.5 Mini** (2.4 GB) - Microsoft, fast, multilingual
- **Salamandra 2B** (1.5 GB) - BSC/AINA, optimized for Catalan and Iberian languages

### Medium models (12-16GB RAM)
- **Mistral 7B** (4.1 GB) - Mistral AI, good quality/speed balance
- **Salamandra 7B** (4.9 GB) - BSC/AINA, excellent for Catalan
- **Llama 3.1 8B** (4.7 GB) - Meta, very popular, high quality

### Large models (32GB+ RAM)
- **Mixtral 8x7B** (26 GB) - Mistral AI, MoE model (Mixture of Experts)
- **Llama 3.1 70B** (40 GB) - Meta, professional quality

**Note:** The Catalan models (Salamandra) are especially interesting for this project built in Catalonia.

## Technology stack

| Component | Technology | Version |
|-----------|------------|--------|
| Backend | FastAPI | 0.104+ |
| Python | CPython | 3.9+ |
| LLM Server | MLX / llama.cpp / Ollama | - |
| Vector database | Qdrant | Latest |
| Relational database | SQLite | 3 |
| Embeddings | Ollama (nomic-embed-text) + sentence-transformers | Latest |
| CLI | Click + Rich | - |
| API | Partially compatible OpenAI | v1 |
| Authentication | X-API-Key (dual-key rotation) | - |

## Experimental use cases

### 1. Personal assistant with memory
NEXE can remember information between sessions: projects, preferences, personal context.

### 2. Private knowledge base
Index local documents (MD, PDF, TXT) and query them in natural language without sending them to the cloud.

### 3. AI-assisted development
Use local models for coding and experimentation without depending on external services.

### 4. Experimentation with LLMs
Try different models and backends, compare results, learn how they work.

### 5. [Future experimental] AI Coding with RAG
Experimenting with AI coding tools using local memory.

## Project philosophy

NEXE **does not try to compete** with ChatGPT, Claude, or other professional assistants.

**The goal is to learn and demonstrate that:**

1. A useful AI with persistent memory is possible locally
2. Total privacy is achievable (zero data leaves your Mac)
3. Local models can cover many everyday use cases
4. Modular architecture allows experimenting with different backends
5. Open source code allows understanding how everything works

**It is an educational project** that can be useful for:
- Learning about RAG and AI systems
- Having a local assistant for basic tasks
- Experimenting with models without API costs
- Maintaining absolute privacy of conversations

## Current limitations

### Technical
- **Only tested on macOS** (despite having cross-platform code)
- **Local models are less capable** than GPT-4, Claude Opus, etc.
- **RAG requires time** for indexing large volumes of data
- **Variable quality** depending on the selected model
- **Significant RAM consumption** with large models

### Functional
- **Very basic Web UI** (not a priority right now)
- **No multi-device sync**
- **Simple document management** (no OCR, no advanced parsing)
- **No model fine-tuning**
- **API partially compatible with OpenAI** (missing /v1/embeddings, /v1/models)
- **Limited CLI** (basic commands: go, status, chat, memory, knowledge)

### Experience
- It is an **experimental and evolving** project
- It may have bugs and unexpected behavior
- No professional support or SLA
- Documentation is under construction

## Roadmap (flexible)

| Version | Goal | Status | Approx. date |
|--------|----------|-------|-------------|
| 0.8 | Base + RAG + 3 backends | ✅ | Completed |
| 0.9 | RAG improvements and stability | 🔨 | TBD |
| 1.0 | Public demo, complete docs | 📅 | TBD |

**Note:** Dates are approximate. This is a personal project done in free time.

## Resources and documentation

**In this folder (knowledge/):**
- **INSTALLATION.md** - Detailed installation guide
- **USAGE.md** - Usage examples and practical cases
- **ARCHITECTURE.md** - Detailed technical architecture
- **RAG.md** - How the memory system works
- **PLUGINS.md** - Plugin system and how to create them
- **API.md** - Complete REST API reference
- **SECURITY.md** - Security system and authentication
- **LIMITATIONS.md** - Technical limitations and unsupported cases

**Web:**
- **Author:** Jordi Goy - [jgoy.net](https://jgoy.net)

## Start exploring

After reading this README, the recommended flow is:

1. **INSTALLATION.md** - Install the system
2. **USAGE.md** - Try the basic features
3. **RAG.md** - Understand how the memory works
4. **ARCHITECTURE.md** - Dive deeper into the architecture
5. **SECURITY.md** - Understand the security and authentication system
6. **API.md** - If you want to integrate it with other tools
7. **LIMITATIONS.md** - To know what it CANNOT do

---

**Important note:** This documentation is auto-ingested into the NEXE RAG system during installation. If you ask NEXE about itself, its capabilities or limitations, it will use this information to respond honestly.

**Learning by doing** - This project is a continuous learning experiment. Bugs, improvements and evolution are part of the process.
