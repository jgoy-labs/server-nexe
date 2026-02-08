# Nexe Server

Local, sovereign AI server. Runs fully on your machine with modular engines, memory (RAG), and a web UI.

![Nexe Banner](https://img.shields.io/badge/Nexe-0.8-blue?style=for-the-badge) ![Python](https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge) [![CI](https://github.com/jgoy-labs/nexe-server/actions/workflows/ci.yml/badge.svg)](https://github.com/jgoy-labs/nexe-server/actions/workflows/ci.yml) ![Coverage](https://img.shields.io/badge/Coverage%20Gate-90%25-brightgreen?style=for-the-badge)

**Local AI Philosophy**
-   **Offline by default**: No cloud dependency.
-   **Data Sovereignty**: Your data stays on your machine.
-   **Transparent**: Open and inspectable components (core, plugins, memory).

---

## 🚀 Quick Start

### 1️⃣ Install
Run the interactive installer. It handles dependencies, model download (Ollama/MLX), and environment setup.

```bash
./setup.sh
```

### 2️⃣ Start the Server
Launch the server in the background:

```bash
./nexe go
```

### 3️⃣ Use It
-   **Web UI**: Open [http://localhost:9119/ui/](http://localhost:9119/ui/)
-   **CLI Chat**: `./nexe chat`
-   **API**: [http://localhost:9119/docs](http://localhost:9119/docs)

---

## 🐋 Docker (Optional)

You can run Nexe using Docker.

-   **Telemetry**: The provided `docker-compose.yml` disables Qdrant telemetry by default (`QDRANT__SERVICE__DISABLE_TELEMETRY=1`). If you want telemetry, remove that environment variable.
-   **Apple Silicon / Metal**: For best performance with MLX/Metal on macOS, use the native install via `./setup.sh` instead of Docker.

1.  **Build and Run**:
    ```bash
    docker compose up --build
    ```
2.  **Access**:
    -   Web UI: `http://localhost:9119/ui/`

---

## ✨ Features

-   **Multi-Engine Support**:
    -   **Ollama**: Universal compatibility.
    -   **MLX**: Optimized for Apple Silicon (Metal).
    -   **llama.cpp**: Efficient CPU/GPU inference.
-   **RAG (Retrieval-Augmented Generation)**:
    -   Ingest local documents (`.txt`, `.md`, `.pdf`) from `knowledge/`.
    -   Semantic search powered by Qdrant.
-   **Modular Plugin System**:
    -   Features are isolated plugins (`plugins/`).
    -   Enable/disable modules via manifest.
-   **Web UI**:
    -   Clean, responsive interface.
    -   Chat history and sessions.
    -   File uploads with **security sanitization**.
-   **Security**:
    -   Internal Sanitizer to block prompt injections.
    -   Rate limiting and audit logging.

---

## 🏗️ Architecture

-   **`core/`**: Runtime, API, middleware, and server lifecycle.
-   **`personality/`**: Configuration, module manager, models, i18n.
-   **`plugins/`**: Engines, UI, security, and extension modules.
-   **`memory/`**: Vector storage (Qdrant), ingestion, and retrieval logic.
-   **`storage/`**: Local data (vectors, models, logs, cache).

---

## 🔒 Privacy & Security

-   **Qdrant**: Started with `--disable-telemetry` by default.
-   **No Telemetry**: Nexe does not phone home.
-   **Sanitization**: Uploaded files are scanned for potential jailbreaks before processing.

---

## ✅ Testing & Coverage

CI enforces **90% coverage** on unit-tested modules:
- `core/contracts`
- `memory/embeddings`
- `plugins/security/sanitizer`
- `plugins/security_logger`
- `personality/metrics`
Coverage omits CLI entrypoints and workflow-node stubs (see `.coveragerc`).

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -m "not integration and not e2e and not slow" \
  --cov=core/contracts \
  --cov=memory/embeddings \
  --cov=plugins/security/sanitizer \
  --cov=plugins/security_logger \
  --cov=personality/metrics \
  --cov-report=term-missing \
  --cov-config=.coveragerc \
  --cov-fail-under=90
```

---

## 🔋 Resource & Power Notes

Local inference is compute-heavy and can drain battery:
- **Laptops**: plug in for long sessions.
- **Thermals**: expect heat under sustained load.
- **Lower power**: choose smaller models, reduce concurrency, and prefer quantized models.

---

## 📚 Documentation

-   [Installation Guide](knowledge/INSTALLATION.md)
-   [Plugin Development](HOWTO_CREATE_PLUGIN.md)
-   [Contributing](CONTRIBUTING.md)

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

**Created by [Jordi Goy](https://www.jgoy.net)**
