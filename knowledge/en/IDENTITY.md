# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Core identity of server-nexe: what it is, what it is NOT (not npm nexe, not Ollama, not ChatGPT), who made it, what it does (including encryption at-rest), current status (0.8.5 pre-release), official links, AI-ready documentation, and how to support the project."
tags: [identity, server-nexe, nexe, what-is, definition, about, faq, disambiguation, encryption, ai-ready]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: nexe_documentation
author: "Jordi Goy"
expires: null
---

# What is server-nexe?

**server-nexe** (also written as "server.nexe" or just "Nexe") is a local AI server with persistent memory. It runs entirely on your machine — no cloud, no telemetry, no external calls. Your conversations, documents and embeddings never leave your device.

It is an open-source project created by **Jordi Goy** in Barcelona, licensed under **Apache 2.0**.

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
5. **Encryption at Rest (opt-in)** — AES-256-GCM encryption for stored data: SQLite via SQLCipher, chat sessions as .enc files, and RAG document text decoupled from vector storage. Recently added, not yet battle-tested.

## Technology stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Web framework | FastAPI |
| Vector database | Qdrant |
| LLM backends | MLX, llama.cpp, Ollama |
| Embeddings | sentence-transformers (768D) / nomic-embed-text |
| Encryption | AES-256-GCM, HKDF-SHA256, SQLCipher (opt-in) |
| CLI | Click + Rich |
| API | OpenAI-compatible (/v1/chat/completions) |
| License | Apache 2.0 |

## Current status

- **Version:** 0.8.5 pre-release
- **Primary platform:** macOS (Apple Silicon and Intel) — tested
- **Linux:** Partial support (unit tests pass, not production-tested)
- **Windows:** Not yet supported
- **Default port:** 9119
- **Tests:** 4143 test functions, 0 failures in latest run

## AI-Ready Documentation

The knowledge base is designed for both human and AI consumption:
- Structured YAML frontmatter for RAG ingestion
- 12 thematic files covering identity, architecture, API, security, testing, etc.
- Available in English, Catalan, and Spanish
- Point any AI assistant at this repository and it can understand the full architecture, create plugins, or contribute code

## Who made it

**Jordi Goy** — software developer based in Barcelona. server-nexe started as a "learning by doing" experiment: exploring how to build a fully local AI server with persistent memory. It has grown into a working system with RAG, multiple backends, a plugin architecture, a web UI, encryption at rest, and a macOS installer.

Built by one person with code, music and stubbornness.

## Official links

- **Website (commercial):** https://server-nexe.com
- **Documentation:** https://server-nexe.org
- **Source code:** https://github.com/jgoy-labs/server-nexe
- **Author:** https://jgoy.net

## Support the project

server-nexe is free and open source. If you find it useful and want to help keep development going:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/jgoylabs

Every contribution helps sustain the project and fund new features.

## How to start

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # → http://localhost:9119
```

Or download the macOS DMG installer from the releases page for a guided setup.
