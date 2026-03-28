<p align="center">
  <img src=".github/logo.svg" alt="server.nexe" width="400">
</p>

<p align="center">
  <strong>Local AI server with persistent memory. Zero cloud. Full control.</strong>
</p>

<p align="center">
  <a href="https://github.com/jgoy-labs/server-nexe/actions/workflows/ci.yml"><img src="https://github.com/jgoy-labs/server-nexe/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src=".github/badges/coverage.svg" alt="Coverage">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
</p>

<p align="center">
  <a href="https://qdrant.tech"><img src="https://img.shields.io/badge/Qdrant-vector--db-dc244c?logo=qdrant&logoColor=white" alt="Qdrant"></a>
  <a href="https://github.com/ml-explore/mlx"><img src="https://img.shields.io/badge/MLX-Apple%20Silicon-000000?logo=apple&logoColor=white" alt="MLX"></a>
  <a href="https://ollama.com"><img src="https://img.shields.io/badge/Ollama-compatible-black?logo=ollama&logoColor=white" alt="Ollama"></a>
  <a href="https://github.com/ggerganov/llama.cpp"><img src="https://img.shields.io/badge/llama.cpp-GGUF-8B5CF6" alt="llama.cpp"></a>
  <a href="https://github.com/jgoy-labs/server-nexe"><img src="https://img.shields.io/badge/RAG-local%20%7C%20private-22c55e" alt="RAG"></a>
  <a href="https://github.com/sponsors/jgoy-labs"><img src="https://img.shields.io/badge/sponsor-♥-ea4aaa?logo=github-sponsors&logoColor=white" alt="Sponsor"></a>
</p>

<p align="center">
  <a href="https://server-nexe.org"><strong>Documentation</strong></a> ·
  <a href="#-quick-start"><strong>Install</strong></a> ·
  <a href="#-architecture"><strong>Architecture</strong></a> ·
  <a href="https://github.com/jgoy-labs/server-nexe/releases"><strong>Releases</strong></a>
</p>

---

## The Story

Server Nexe started as a learning-by-doing experiment: *"What would it take to run a fully local AI server with persistent memory?"* One question led to another — inference backends, RAG pipelines, vector search, plugin systems, security layers, a web UI, an installer with hardware detection.

What began as a weekend prototype has grown into a real, working system. It's not done — there's a roadmap full of ideas — but it already does what it set out to do: **run an AI server on your machine, with memory that persists, and zero data leaving your device.**

This is not trying to compete with ChatGPT or Claude. It's an open-source tool for people who want to own their AI infrastructure. Built by one person in Barcelona, with code, music, and stubbornness.

## Why Server Nexe?

Your conversations, documents, embeddings, and model weights stay on your machine. Always. Server Nexe combines LLM inference with a **persistent RAG memory system** — your AI remembers context across sessions, indexes your documents, and never phones home.

<table>
<tr>
<td width="50%">

### Local & Private
Every conversation, document, and embedding stays on your device. No telemetry, no external calls, no cloud dependency. Not even a server to spy on you.

</td>
<td width="50%">

### Persistent RAG Memory
Remembers context across sessions using Qdrant vector search with 768-dimensional embeddings across 3 specialized collections. Ingest documents, recall knowledge.

</td>
</tr>
<tr>
<td width="50%">

### Multi-Backend Inference
Switch between MLX (Apple Silicon native), llama.cpp (GGUF, universal), or Ollama — one config change, same OpenAI-compatible API.

</td>
<td width="50%">

### Modular Plugin System
Auto-discovered plugins with independent manifests. Security, web UI, RAG, backends — everything is a plugin. Add capabilities without touching the core.

</td>
</tr>
<tr>
<td width="50%">

### macOS Installer
DMG with guided wizard that detects your hardware, picks the right backend, recommends models for your RAM, and gets you running in minutes.

</td>
<td width="50%">

### Built to Grow
245 tests, security audit, i18n in 3 languages, comprehensive API. What started as an experiment is being built with production practices.

</td>
</tr>
</table>

## Quick Start

### Option A: DMG Installer (macOS)

Download the latest **[Install Nexe.dmg](https://github.com/jgoy-labs/server-nexe/releases/latest)** from Releases. The wizard handles everything: hardware detection, backend selection, model download, and configuration.

### Option B: Command Line

```bash
git clone https://github.com/jgoy-labs/server-nexe.git
cd server-nexe
./setup.sh                # guided installation (detects hardware, picks backend & model)
python -m core.cli go     # start server on port 9119
```

Once running:

```bash
python -m core.cli chat               # interactive chat
python -m core.cli chat --rag         # chat with RAG memory
python -m core.cli memory store "Barcelona is the capital of Catalonia"
python -m core.cli memory recall "capital Catalonia"
python -m core.cli status             # system status
```

### Option C: Headless (servers, scripts, CI)

```bash
python -m installer.install_headless --backend ollama --model qwen3.5:latest
python -m core.cli go
```

**Endpoints at `http://localhost:9119`:**

| Endpoint | Description |
|----------|-------------|
| `/v1/chat/completions` | OpenAI-compatible chat API |
| `/ui` | Web UI (chat, file upload, sessions) |
| `/health` | Health check |
| `/docs` | Interactive API documentation (Swagger) |

> Authentication via `X-API-Key` header. Key is generated during installation and stored in `.env`.

## Backends

| Backend | Platform | Best for |
|---------|----------|----------|
| **MLX** | macOS (Apple Silicon) | Recommended for Mac — native Metal GPU acceleration, fastest on M-series |
| **llama.cpp** | macOS / Linux | Universal — GGUF format, Metal on Mac, CPU/CUDA on Linux |
| **Ollama** | macOS / Linux | Bridge to existing Ollama installations, easiest model management |

The installer auto-detects your hardware and recommends the best backend. You can switch anytime in `personality/server.toml`.

## Architecture

```
server-nexe/
├── core/                 # FastAPI server, endpoints, CLI, config, metrics, resilience
│   ├── endpoints/        # REST API (v1 chat, health, status, system)
│   ├── cli/              # CLI commands & i18n (ca/es/en)
│   └── resilience/       # Circuit breaker, rate limiting
├── personality/          # Module manager, plugin discovery, server.toml
│   ├── loading/          # Plugin loading pipeline (find, validate, import, lifecycle)
│   └── module_manager/   # Discovery, registry, config, sync
├── memory/               # Embeddings, RAG engine, vector memory, document ingestion
│   ├── embeddings/       # Chunking, embedding generation
│   ├── rag/              # Retrieval-augmented generation pipeline
│   └── memory/           # Persistent vector store (Qdrant)
├── plugins/              # Auto-discovered plugin modules
│   ├── mlx_module/       # MLX backend (Apple Silicon)
│   ├── llama_cpp_module/ # llama.cpp backend (GGUF)
│   ├── ollama_module/    # Ollama bridge
│   ├── security/         # Auth, injection detection, CSRF, rate limiting, input sanitization
│   └── web_ui_module/    # Browser-based chat UI with file upload
├── installer/            # Guided installer, headless mode, hardware detection, model catalog
├── knowledge/            # Indexed documentation for RAG (ca/es/en)
└── tests/                # Integration & e2e test suites
```

## Security

Server Nexe includes a security module enabled by default:

- **API key authentication** on all endpoints
- **CSP headers** (script-src 'self', no unsafe-inline)
- **CSRF protection** with token validation
- **Rate limiting** per IP
- **Input sanitization** — jailbreak and injection detection
- **Trusted host middleware**

The project has passed a full technical audit (73 findings reviewed, 40 fixes implemented). See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| **OS** | macOS 13+ | macOS 14+ (Apple Silicon) |
| **Python** | 3.11+ | 3.12+ |
| **RAM** | 8 GB | 16 GB+ (for larger models) |
| **Disk** | 10 GB free | 20 GB+ free |

> **Linux**: Works with llama.cpp and Ollama backends. Docker support and full Linux compatibility are on the roadmap.

## Testing

245 tests with coverage reporting. CI runs the full suite on every push.

```bash
# Unit tests
pytest core memory personality plugins -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --tb=short -q

# Integration tests (requires Ollama running)
NEXE_AUTOSTART_OLLAMA=true pytest -m "integration" -q
```

## Documentation

| Language | Link |
|----------|------|
| English | [knowledge/en/README.md](knowledge/en/README.md) |
| Catalan | [knowledge/ca/README.md](knowledge/ca/README.md) |
| Spanish | [knowledge/es/README.md](knowledge/es/README.md) |

## Roadmap

Server Nexe is actively developed. Here's what's coming:

- [ ] Docker container for Linux deployment
- [ ] Full Linux compatibility audit
- [x] Updated knowledge base for v0.8.5
- [ ] Website updates (server-nexe.org / server-nexe.com)
- [ ] macOS code signing & notarization
- [ ] Configurable inference parameters via UI
- [ ] Community forum

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## Acknowledgments

server-nexe is built on the shoulders of these amazing open-source projects:

**AI & Inference**
- [MLX](https://github.com/ml-explore/mlx) — Apple Silicon native ML framework
- [llama.cpp](https://github.com/ggerganov/llama.cpp) — Efficient GGUF model inference
- [Ollama](https://ollama.ai) — Local model management and serving
- [sentence-transformers](https://www.sbert.net) — Text embedding models
- [Hugging Face](https://huggingface.co) — Model hub and transformers library

**Infrastructure**
- [Qdrant](https://qdrant.tech) — Vector search engine powering RAG memory
- [FastAPI](https://fastapi.tiangolo.com) — High-performance async web framework
- [Uvicorn](https://www.uvicorn.org) — Lightning-fast ASGI server
- [Pydantic](https://docs.pydantic.dev) — Data validation

**Tools & Libraries**
- [Rich](https://github.com/Textualize/rich) — Beautiful terminal formatting
- [marked.js](https://marked.js.org) — Markdown rendering in web UI
- [PyPDF](https://github.com/py-pdf/pypdf) — PDF text extraction for RAG
- [rumps](https://github.com/jaredks/rumps) — macOS menu bar integration

**Security & Monitoring**
- [Prometheus](https://prometheus.io) — Metrics and monitoring
- [SlowAPI](https://github.com/laurentS/slowapi) — Rate limiting

Also built with: Python, NumPy, httpx, tenacity, Click, Typer, Colorama, python-dotenv, PyYAML, toml, structlog, starlette-csrf, python-multipart, psutil, PyObjC, and Linux.

20% of Enterprise sponsorships go directly to supporting these projects.

Built with AI collaboration · Barcelona

## Disclaimer

This software is provided **"as is"**, without warranty of any kind. Use it at your own risk. The author is not responsible for any damage, data loss, security incidents, or misuse arising from the use of this software.

See [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Version 0.8.5</strong> · Apache 2.0 · Made by <a href="https://www.jgoy.net">Jordi Goy</a> in Barcelona
</p>
