# Nexe Server

Local, sovereign AI server. Runs fully on your machine with modular engines, memory (RAG), and a web UI.

**Local AI Philosophy**
- Offline by default, no cloud dependency.
- Your data stays on your machine.
- Open and inspectable components (core, plugins, memory).

**Quick Start**
1. Run the installer: `./setup.sh`
2. Start the server: `./nexe go`
3. Open the UI: `http://localhost:9119/ui/`

**Docker (Optional)**
1. `docker compose up --build`
2. Open the UI: `http://localhost:9119/ui/`

**Features**
- Multi-engine: Ollama, MLX, llama.cpp.
- Memory + RAG ingestion from local files.
- Modular plugin system with manifests.
- Web UI with sessions and document upload.
- Security plugins (rate limiting, sanitization, auditing).

**Architecture Overview**
- `core/` runtime, API, middleware, and server lifecycle.
- `personality/` configuration, module manager, models, i18n.
- `plugins/` engines, UI, security, and extension modules.
- `memory/` vector storage, ingestion, and retrieval.

**Privacy**
- Qdrant is started with `--disable-telemetry` by default.
- No external API calls unless you explicitly configure them.

**Docs**
- `knowledge/INSTALLATION.md`
- `README_PLUGINS.md`
- `HOWTO_CREATE_PLUGIN.md`

**License**
MIT. See `LICENSE`.
