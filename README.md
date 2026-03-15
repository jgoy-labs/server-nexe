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
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
</p>

<p align="center">
  <a href="https://qdrant.tech"><img src="https://img.shields.io/badge/Qdrant-vector--db-dc244c?logo=qdrant&logoColor=white" alt="Qdrant"></a>
  <a href="https://github.com/ml-explore/mlx"><img src="https://img.shields.io/badge/MLX-Apple%20Silicon-000000?logo=apple&logoColor=white" alt="MLX"></a>
  <a href="https://ollama.com"><img src="https://img.shields.io/badge/Ollama-compatible-black?logo=ollama&logoColor=white" alt="Ollama"></a>
  <a href="https://github.com/ggerganov/llama.cpp"><img src="https://img.shields.io/badge/llama.cpp-GGUF-8B5CF6" alt="llama.cpp"></a>
  <a href="https://github.com/jgoy-labs/server-nexe"><img src="https://img.shields.io/badge/RAG-local%20%7C%20private-22c55e" alt="RAG"></a>
</p>

<p align="center">
  <a href="https://server-nexe.org"><strong>📖 Documentation</strong></a> ·
  <a href="https://server-nexe.org/install"><strong>⬇️ Install</strong></a> ·
  <a href="https://server-nexe.org/api"><strong>🔌 API Reference</strong></a>
</p>

---

## ✨ Why Server Nexe?

Server Nexe is a local AI server that keeps **everything on your machine** — conversations, documents, embeddings, and model weights. It combines LLM inference with a **persistent RAG memory system**, so your AI remembers context across sessions without ever sending data to the cloud.

> **Note:** This is a personal learning project exploring local AI infrastructure. It does not aim to replace mature tools like ChatGPT, Claude, or LM Studio — but it can use [Ollama](https://ollama.com) as one of its backends.

## 🔑 Key Features

<table>
<tr>
<td width="50%">

### 🔒 Local & Private
Every conversation, document, and embedding stays on your device. No telemetry, no external calls, no data leaves your machine.

</td>
<td width="50%">

### 🧠 Persistent RAG Memory
Remembers context across sessions using Qdrant vector search with 768-dimensional embeddings across 3 specialized collections.

</td>
</tr>
<tr>
<td width="50%">

### ⚡ Multi-Backend Inference
Switch between MLX (Apple Silicon native), llama.cpp (GGUF, universal), or Ollama — one config change, same API.

</td>
<td width="50%">

### 🧩 Modular Plugin System
Auto-discovered plugins with independent manifests. Add RAG, security, web UI, or custom capabilities without touching the core.

</td>
</tr>
</table>

## 🚀 Quick Start

```bash
git clone https://github.com/jgoy-labs/server-nexe.git
cd server-nexe
./setup.sh                # guided installation (detects hardware, picks backend & model)
./nexe go                 # start server on port 9119
```

The interactive installer will detect your hardware, select the appropriate backend, and choose an LLM model based on your available RAM.

Once the server is running:

```bash
./nexe chat               # interactive chat
./nexe chat --rag         # chat with RAG memory
./nexe memory store "Barcelona is the capital of Catalonia"
./nexe memory recall "capital Catalonia"
./nexe status             # system status
```

**Endpoints available at `http://localhost:9119`:**

| Endpoint | Description |
|----------|-------------|
| `/v1/chat/completions` | OpenAI-compatible chat API |
| `/ui` | Web UI |
| `/health` | Health check |
| `/docs` | Interactive API documentation |

> Authentication required via `X-API-Key` header (configured in `.env`).

## 🔧 Backends

| Backend | Platform | Best for |
|---------|----------|----------|
| **MLX** | macOS (Apple Silicon) | ⭐ Recommended for Mac — native GPU acceleration via Metal |
| **llama.cpp** | macOS / Linux | Universal — GGUF format, Metal acceleration on Mac |
| **Ollama** | macOS / Linux | Bridge to existing Ollama installations |

Configure your backend in `personality/server.toml` or during `./setup.sh`.

## 🏗️ Architecture

```
server-nexe/
├── core/                 # FastAPI server, endpoints, CLI, config, metrics
│   ├── endpoints/        # REST API (v1, chat, health, status)
│   └── cli/              # CLI commands & i18n (ca/es/en)
├── personality/          # Personality system, module manager, server.toml
├── memory/               # Embeddings, RAG engine, vector memory
├── plugins/              # Auto-discovered plugin modules
│   ├── mlx_module/       # MLX backend (Apple Silicon)
│   ├── llama_cpp_module/ # llama.cpp backend (GGUF)
│   ├── ollama_module/    # Ollama bridge
│   ├── security/         # Auth, rate limiting, CSRF
│   └── web_ui_module/    # Browser-based chat UI
└── knowledge/            # Indexed documentation for RAG (ca/es/en)
```

## 📋 Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| **OS** | macOS 12+ | macOS 14+ (Apple Silicon) |
| **Python** | 3.11+ | 3.11+ |
| **RAM** | 8 GB | 16 GB+ |
| **Disk** | 10 GB free | 20 GB+ free |

Linux x86_64 should work with llama.cpp but is not actively tested.

## 🧪 Testing

CI runs on Ubuntu with the full unit suite and coverage reporting.

```bash
pytest core memory personality plugins -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --cov-report=xml:coverage.xml --tb=short -q
```

Integration tests require local services:

```bash
NEXE_AUTOSTART_OLLAMA=true pytest -m "integration" -q
```

Run the same suite on Linux via Docker:

```bash
./dev-tools/run_linux_ci.sh
```

## 📖 Documentation

Full documentation is available in three languages:

| | Link |
|---|------|
| 🇬🇧 English | [knowledge/en/README.md](knowledge/en/README.md) |
| 🏴 Català | [knowledge/ca/README.md](knowledge/ca/README.md) |
| 🇪🇸 Español | [knowledge/es/README.md](knowledge/es/README.md) |
| 🌐 Web | [server-nexe.org](https://server-nexe.org) |

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## 🔐 Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## ⚠️ Disclaimer

This software is provided **"as is"**, without warranty of any kind. Use it at your own risk. The author is not responsible for any damage, data loss, security incidents, or misuse arising from the use of this software. By using Server Nexe, you accept full responsibility for how you deploy and operate it.

See [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Version 0.8</strong> · Apache 2.0 · Made by <a href="https://www.jgoy.net">Jordi Goy</a>
</p>
