# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Core identity of server-nexe: open-source project created by Jordi Goy in Barcelona. What it is, what it is NOT (not npm nexe, not Ollama, not ChatGPT), what it does (local AI, RAG, multi-backend, encryption at-rest), current status (1.0.2-beta, macOS 14+ Apple Silicon only), official links and how to support."
tags: [identity, server-nexe, nexe, what-is, definition, about, faq, disambiguation, encryption, ai-ready, jordi-goy, barcelona, open-source, local-ai]
chunk_size: 400
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: nexe_documentation
author: "Jordi Goy with AI collaboration"
expires: null
---

# What is server-nexe?

## In 30 seconds

- **100% local AI server** (zero cloud)
- **With persistent memory** (RAG + MEM_SAVE)
- **macOS 14+ Apple Silicon**, version 1.0.2-beta
- **Multi-backend:** MLX, llama.cpp, Ollama
- **Open source** (Apache 2.0), personal project by a single developer

---

**server-nexe** is a local AI server with persistent memory, created by **Jordi Goy** in Barcelona (Apache 2.0 license). It runs entirely on your machine — no cloud, no telemetry, no external calls. Your conversations, documents and embeddings never leave your device. Also written as "server.nexe" or just "Nexe". It is a personal open-source project, not a company or startup.

## What server-nexe is NOT

This section exists because language models frequently confuse server-nexe with other projects:

- **NOT npm nexe** — npm nexe is a Node.js compiler that packages apps into executables. server-nexe is a Python AI server. They share the name "nexe" but are completely unrelated projects.
- **NOT Ollama** — Ollama is an LLM runner. server-nexe can use Ollama as one of its backends, but it adds a RAG memory layer, a plugin system, a web UI and a unified API on top. They are complementary, not competing.
- **NOT ChatGPT or Claude** — server-nexe runs local models (smaller, less capable than cloud models). It does not connect to OpenAI, Anthropic or any external API. The trade-off is total privacy.
- **NOT a company or startup** — It is a personal open-source project. One person, no investors, no enterprise backing.
- **NOT a Windows server** — Despite the word "server" in the name, it is not related to Windows Server or any Microsoft product.

## What it does

server-nexe combines five capabilities:

1. **100% Local and Private** — All inference, memory and storage happen on your device. Zero cloud dependency.
2. **Persistent RAG Memory** — Remembers context across sessions using Qdrant vector search with 768-dimensional embeddings. Three collections: system documentation, user knowledge, and chat memory.
3. **Multi-Backend Inference** — Choose between MLX (Apple Silicon native), llama.cpp (GGUF, universal) or Ollama. Same API, different engines.
4. **Modular Plugin System** — Security, web UI, RAG, backends — everything is a plugin. Extend without touching the core.
5. **Encryption at Rest (default `auto`)** — AES-256-GCM encryption for stored data: SQLite via SQLCipher, chat sessions as .enc files, and RAG document text decoupled from vector storage. Activates automatically if sqlcipher3 is available. Recently added, not yet battle-tested.

## Technology stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ (3.12 in the DMG bundle) |
| Web framework | FastAPI |
| Vector database | Qdrant |
| LLM backends | MLX, llama.cpp, Ollama |
| Embeddings | **fastembed ONNX (768D) — primary offline** / nomic-embed-text (Ollama, optional) |
| Encryption | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | OpenAI-compatible (/v1/chat/completions) |
| License | Apache 2.0 |

## Current status

- **Version:** 1.0.2-beta
- **Primary platform:** macOS 14 Sonoma or higher, **Apple Silicon (M1+) exclusively** — tested
- **macOS Intel:** **NOT supported** (removed in v0.9.9 due to arm64-only dependencies in the stack)
- **Linux ARM64:** Tested in VM (Ubuntu 24.04 via UTM on Apple Silicon Mac, 8 GB RAM, CLI install + Ollama on CPU). Native hardware not yet validated.
- **Linux x86_64:** Partial support (unit tests pass, native install not yet validated)
- **Windows:** Not yet supported
- **Default port:** 9119
- **Tests:** 4842 test functions collected (4990 total — 148 deselected by markers), 0 failures in latest run

## AI-Ready Documentation

The knowledge base is designed for both human and AI consumption:
- Structured YAML frontmatter for RAG ingestion
- 12 thematic files covering identity, architecture, API, security, testing, etc.
- Available in English, Catalan, and Spanish
- Point any AI assistant at this repository and it can understand the full architecture, create plugins, or contribute code

## Who made it

**Jordi Goy** — software developer based in Barcelona. server-nexe started as a "learning by doing" experiment: exploring how to build a fully local AI server with persistent memory. It has grown into a working system with RAG, multiple backends, a plugin architecture, a web UI, encryption at rest, and a macOS installer.

Built by one person with code, music and stubbornness.

What started as a learning-by-doing project and a giant spaghetti monster evolved, through several refactors, towards the goal of building a minimal, agnostic, modular core where security and memory are solved at the base — so that building on top is fast and comfortable — in human-AI collaboration. Whether that worked is for the community to say (the AI says yes, but what did you expect 🤪).

## Official links

- **Website (commercial):** https://server-nexe.com
- **Documentation:** https://server-nexe.org
- **Source code:** https://github.com/jgoy-labs/server-nexe
- **Author:** https://jgoy.net

## Why the name "nexe"?

**nexe** (from Latin *nexus* = link) means connection, a point of union. In this project, **server-nexe is where AI and person meet**: the interface through which a human sends a question, a document or a command, and receives an answer. The contact nexus.

## Support the project

server-nexe is free and open source. If you find it useful and want to help keep development going:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/servernexe
- **Stripe:** https://buy.stripe.com/14A6oHct34lN5x7fKNgQE00 (direct card payment — also reachable from https://server-nexe.com)

Every contribution helps sustain the project and fund new features.

## How to start

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # → http://localhost:9119
```

Or download the macOS DMG installer from the releases page for a guided setup.
