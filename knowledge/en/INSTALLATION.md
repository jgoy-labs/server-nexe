# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete installation guide for NEXE 0.8. macOS (tested), Linux and Windows (theoretical). Requirements, guided installation with setup.sh, .env configuration, MLX/llama.cpp/Ollama backends and troubleshooting."
tags: [installation, setup, macos, configuration, homebrew, python, venv]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: en
type: tutorial
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Installation Guide - NEXE 0.8

> **📝 Document updated:** 2026-02-04
> **⚠️ IMPORTANT:** This document has been reviewed to reflect the **actual code** of Nexe 0.8 (setup.sh, install_nexe.py, environment variables, etc.).

This guide explains step by step how to install NEXE on your system.

## ⚠️ Supported platforms

**Tested and working:**
- ✅ macOS 12+ (Monterey or later)
  - Apple Silicon (M1, M2, M3, M4)
  - Intel x86_64

**Theoretical (code implemented but NOT tested):**
- ⚠️ Raspberry Pi 4/5 with Raspberry Pi OS
- ⚠️ Linux x86_64 (Ubuntu 20.04+, Debian, etc.)
- ⚠️ Windows 10/11 (with WSL2 recommended)

**If you test NEXE on RPi, Linux or Windows**, please report your experience! It is untested code but should work.

## System requirements

### Minimum (small models)
- **CPU:** Any modern CPU (2+ cores)
- **RAM:** 8 GB
- **Disk:** 10 GB free
- **Python:** 3.9+
- **Internet:** To download models and dependencies

### Recommended (medium models)
- **CPU:** Apple Silicon (M1+) or CPU with AVX2
- **RAM:** 16 GB
- **Disk:** 20 GB free
- **Python:** 3.11+
- **GPU:** Metal (Mac) or CUDA (Linux/Win) for acceleration

### Optimal (large models)
- **CPU:** Apple Silicon M2+ or modern multicore CPU
- **RAM:** 32+ GB
- **Disk:** 50+ GB free
- **GPU:** Required for 70B models

## Prerequisites

### macOS

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.11 (recommended)
brew install python@3.11

# Verify installation
python3 --version
```

### Linux (Ubuntu/Debian)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install python3.11 python3.11-venv python3-pip git curl -y

# Verify installation
python3.11 --version
```

### Raspberry Pi

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install python3-pip python3-venv git curl -y

# Note: Large models will NOT work on RPi due to RAM limitations
```

## Download NEXE

**Option 1: Clone repository (recommended)**

```bash
# Clone the repository
git clone https://github.com/jgoy/nexe.git
cd nexe/server-nexe

# Or if it's in a local path
cd /path/to/server-nexe
```

**Option 2: Download ZIP**

If you have NEXE as a ZIP:
```bash
unzip server-nexe.zip
cd server-nexe
```

## Guided installation (recommended)

NEXE includes an interactive installer that detects your hardware and guides you through the process.

### Run the installer

**Option 1: Via setup.sh (RECOMMENDED)**

```bash
cd server-nexe
chmod +x setup.sh   # only needed the first time (GitHub ZIP does not preserve permissions)
./setup.sh
```

This script:
- Clears Python cache automatically
- Stops previous processes (Qdrant, Ollama, server)
- Offers a complete cleanup option (venv, .env, storage)
- Calls `install_nexe.py` with a clean environment

**Option 2: Directly (less robust)**

```bash
cd server-nexe
./setup.sh
```

⚠️ **Note:** If you have a previous installation, use `./setup.sh` to ensure proper cleanup.

### What does the installer do?

The installer will guide you through these stages:

#### 1. Language selection
- Català (CA)
- Castellà (ES)
- English (EN)

#### 2. Hardware detection

The installer analyzes:
- **Platform:** macOS, Linux, Raspberry Pi, Windows
- **CPU:** Architecture (ARM64, x86_64, armv7l)
- **Available RAM:** To recommend suitable models
- **Disk space:** To verify there is enough space
- **GPU/Metal:** To decide which backend to use

**Example output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Analyzing your hardware...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Plataforma: macOS (Darwin)
Arquitectura: arm64 (Apple Silicon)
RAM Disponible: 16 GB
Disc Disponible: 256 GB lliures
Suport Metal (GPU): Sí ✓

Recomanació: Backend MLX (optimitzat per Apple Silicon)
```

#### 3. Backend selection

Depending on your hardware, backends will be proposed:

**For Apple Silicon:**
- **MLX** (recommended) - Native, optimized, fast
- llama.cpp - Universal, compatible
- Ollama - If you already have it installed

**For Intel Mac:**
- **llama.cpp** (recommended) - Universal with Metal
- Ollama - If you already have it installed

**For Linux/RPi:**
- **llama.cpp** (only theoretically tested option)
- Ollama - If you already have it installed

**For Raspberry Pi:**
- **llama.cpp** (only viable option)
- ⚠️ Small models only (Phi-3.5, Salamandra 2B)

#### 4. Model selection

The installer will show you models compatible with your RAM:

**If you have 8 GB RAM:**
```
Models disponibles:

[1] Phi-3.5 Mini (2.4 GB)
    Origin: Microsoft
    Idioma: Multilingüe
    Característiques: Molt ràpid, bo per tasques generals

[2] Salamandra 2B (1.5 GB) ⭐ RECOMANAT PER CATALÀ
    Origin: BSC/AINA (Catalunya)
    Idioma: Català, Castellà, Euskera, Gallec
    Característiques: Optimitzat per llengües ibèriques
```

**If you have 16+ GB RAM:**
```
Models disponibles:

[1] Mistral 7B (4.1 GB)
    Origin: Mistral AI
    Idioma: Multilingüe
    Característiques: Excel·lent equilibri qualitat/velocitat

[2] Salamandra 7B (4.9 GB) ⭐ RECOMANAT PER CATALÀ
    Origin: BSC/AINA (Catalunya)
    Idioma: Català, Castellà, Euskera, Gallec
    Característiques: El millor per català

[3] Llama 3.1 8B (4.7 GB)
    Origin: Meta
    Idioma: Multilingüe
    Característiques: Molt popular, excel·lent qualitat
```

**If you have 32+ GB RAM:**
Mixtral 8x7B and Llama 3.1 70B will also be available.

#### 5. Download and installation

The installer:
1. Creates a Python virtual environment
2. Installs the necessary dependencies
3. Downloads the Qdrant binary (handles macOS quarantine)
4. Downloads the selected model (may take time depending on size)
5. Configures the `.env` file with the necessary variables
6. Creates `storage/` directories (qdrant, vectors, logs, models)
7. Marks auto-ingestion for the first run (does not perform it now)
8. Shows final instructions

**Note:** Model download may take between 5-30 minutes depending on your connection and the model size.

#### 6. First run

After installation:

```bash
./nexe go
```

On first startup:
- ✅ Qdrant auto-starts (subprocess managed by lifespan.py)
- ✅ Ollama auto-starts if installed
- ✅ Memory modules load (Memory, RAG, Embeddings)
- ✅ Plugin modules initialize (MLX/LlamaCpp/Ollama, Security, WebUI)
- ✅ Auto-ingestion of `knowledge/` (first time only, creates marker `.knowledge_ingested`)
- ✅ Bootstrap token is generated (if NEXE_ENV=development)

**There are no automatic tests** - verification is done manually (see "Post-installation verification" section).

## Manual installation (advanced)

If you prefer to install manually or the automatic installer fails:

### 1. Create virtual environment

```bash
cd server-nexe
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows
```

### 2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure `.env`

Create a `.env` file at the root of `server-nexe/`:

```bash
# ═══════════════════════════════════════════════════════════
# NEXE 0.8 - Variables d'Entorn (Configuration)
# ═══════════════════════════════════════════════════════════

# ─── MODEL ENGINE ───
# Opcions: mlx (Apple Silicon), llama_cpp (universal), ollama (bridge)
NEXE_MODEL_ENGINE=mlx

# ─── MODELS ───
# Path o ID del model per cada backend
NEXE_DEFAULT_MODEL=mlx-community/Phi-3.5-mini-instruct-4bit  # Model actiu
NEXE_MLX_MODEL=mlx-community/Phi-3.5-mini-instruct-4bit      # Específic MLX
NEXE_LLAMA_CPP_MODEL=storage/models/phi-3.5-mini.gguf        # Específic llama.cpp
NEXE_OLLAMA_MODEL=phi3:mini                                   # Específic Ollama

# ─── ENVIRONMENT ───
NEXE_ENV=development  # "production" o "development"

# ─── SECURITY (CRÍTIC EN PRODUCCIÓ) ───
# Dual-key support (key rotation)
NEXE_PRIMARY_API_KEY=your-primary-key-here
NEXE_PRIMARY_KEY_EXPIRES=2026-06-30T00:00:00Z  # ISO 8601 format
NEXE_SECONDARY_API_KEY=your-secondary-key-here  # Grace period rotation
NEXE_SECONDARY_KEY_EXPIRES=2026-01-31T00:00:00Z

# Backward compatibility (single key)
# NEXE_ADMIN_API_KEY=single-key-here

# CSRF Protection
NEXE_CSRF_SECRET=auto-generated-secret-32-chars

# ─── BOOTSTRAP (DEV MODE) ───
BOOTSTRAP_TTL=30  # Minutes
NEXE_BOOTSTRAP_DISPLAY=true  # Show token on startup

# ─── AUTOSTART SERVICES ───
NEXE_AUTOSTART_QDRANT=true   # Auto-start Qdrant local binary
NEXE_AUTOSTART_OLLAMA=true   # Auto-start Ollama if installed

# ─── QDRANT (AUTO-MANAGED) ───
# NO usar QDRANT_PATH (obsolet!)
# Paths auto-gestionats per lifespan.py:
#   - storage/qdrant/           → Qdrant data
#   - storage/vectors/          → Vector DBs (metadata_memory.db, qdrant_local/)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Variables internes Qdrant (auto-injectades per lifespan.py):
# QDRANT__STORAGE__STORAGE_PATH=storage/qdrant
# QDRANT__SERVICE__HTTP_PORT=6333
# QDRANT__SERVICE__DISABLE_TELEMETRY=true

# ─── TIMEOUTS (OPCIONAL) ───
NEXE_OLLAMA_HEALTH_TIMEOUT=5.0
NEXE_OLLAMA_UNLOAD_TIMEOUT=10.0
NEXE_QDRANT_HEALTH_TIMEOUT=2.0

# ─── PRODUCTION SECURITY (OPCIONAL) ───
# Module allowlist (només en production mode)
# NEXE_APPROVED_MODULES=security,mlx_module,memory,rag,embeddings

# ─── ADVANCED (NO TOCAR) ───
NEXE_FORCE_RELOAD=false  # Force rebuild app (testing only)
AUTO_CLEAN_ENABLED=false  # Auto-clean temp files
AUTO_CLEAN_DRY_RUN=true

# ─── LOGGING ───
# Configurat a personality/server.toml
# Logs a: storage/logs/
```

**Important note:**
- The server/port is configured in `personality/server.toml` (NOT .env)
- The `storage/*` paths are created automatically
- In DEV mode, API keys are optional (fail-open)
- In PRODUCTION mode, API keys are mandatory (fail-closed)

### 4. Initialize Qdrant

**Qdrant starts automatically** when you run `./nexe go` (managed by `core/lifespan.py`).

**If you want to start Qdrant manually:**

```bash
# Required environment variables
export QDRANT__STORAGE__STORAGE_PATH="storage/qdrant"
export QDRANT__SERVICE__HTTP_PORT="6333"
export QDRANT__SERVICE__DISABLE_TELEMETRY="true"

# Run binary
./qdrant --disable-telemetry &

# Verify it is running
curl http://localhost:6333/health
```

**If you don't have the binary:**
```bash
# The installer downloads it automatically
# Or download manually:
# Mac (arm64): https://github.com/qdrant/qdrant/releases
# Linux (x86_64): https://github.com/qdrant/qdrant/releases
```

⚠️ **Recommendation:** Let `./nexe go` manage Qdrant automatically.

### 5. Start the server

```bash
./nexe go

# Or manually:
python3 -m uvicorn core.app:app --host 0.0.0.0 --port 9119
```

### 6. Verify operation

```bash
# Health test
curl http://localhost:9119/health

# You should see:
# {"status": "ok", "version": "0.8.0"}
```

## Backends: Specific installation

### Backend MLX (Apple Silicon)

```bash
pip install mlx mlx-lm
```

**MLX models:**
- Downloaded automatically from HuggingFace
- Stored in `storage/models/` (NOT `~/.cache/huggingface/`)
- Format: Native MLX checkpoint (not GGUF)
- The installer uses `snapshot_download(local_dir=storage/models/...)`

### Backend llama.cpp

```bash
pip install llama-cpp-python

# For Metal (Mac):
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

# For CUDA (Linux with NVIDIA GPU):
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
```

**llama.cpp models:**
- GGUF format
- Downloaded from HuggingFace
- Stored in `storage/models/` (NOT `./models/`)
- `.env` variable: `NEXE_LLAMA_CPP_MODEL=storage/models/model.gguf`

### Backend Ollama

```bash
# 1. Install Ollama

# Mac: Download .pkg installer
# https://ollama.com/download
# (NOT available via Homebrew)

# Linux:
curl -fsSL https://ollama.com/install.sh | sh

# 2. Start Ollama
ollama serve &

# 3. Download a model
ollama pull phi3:mini
# or
ollama pull mistral:7b

# 4. Configure NEXE to use Ollama
# In .env:
NEXE_MODEL_ENGINE=ollama
NEXE_OLLAMA_MODEL=phi3:mini
```

## Post-installation verification

### 1. Check server

```bash
# Health check
curl http://localhost:9119/health

# Expected response:
# {
#   "status": "healthy",
#   "message": "Nexe 0.8 - All systems operational",
#   "version": "0.8.0",
#   "uptime": 123.45
# }

# System info (available API endpoints)
curl http://localhost:9119/api/info

# Expected response:
# {
#   "version": "0.8.0",
#   "endpoints": [...],
#   "modules": [...]
# }
```

### 2. Chat test

```bash
./nexe chat

# Try a question:
# > Hello, who are you?
```

### 3. RAG memory test

```bash
# Store information
./nexe memory store "My favorite project is NEXE"

# Retrieve (NOT "search", but "recall")
./nexe memory recall "favorite project"

# Other memory commands:
./nexe memory stats     # Statistics
./nexe memory cleanup   # Clean expired entries

# RAG search (different from memory):
./nexe rag search "favorite project"
```

**Note:**
- `memory` → Flat memory (store/recall/stats/cleanup)
- `rag` → RAG search (semantic search with vectors)

### 4. Access Web UI

Open your browser at: `http://localhost:9119/ui`

### 5. Review logs

```bash
# Logs in real time (correct path)
tail -f storage/logs/nexe.log

# Or via CLI (automatic, finds logs in storage/logs/)
./nexe logs

# View module-specific logs
./nexe logs --module mlx_module
./nexe logs --module security

# Last 100 lines
./nexe logs --last 100
```

## Common troubleshooting

### Error: "Python version not supported"

```bash
# Check the version
python3 --version

# Must be 3.9+, recommended 3.11+
# If it is older, install a newer Python version
```

### Error: "No module named 'mlx'"

```bash
# Reactivate the virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Error: "Qdrant connection refused"

```bash
# Check that Qdrant is running
ps aux | grep qdrant

# If it is not, start it:
./qdrant &

# Wait a few seconds and try again
```

### Error: "Out of memory" during inference

**Solution:**
- Choose a smaller model
- Close other applications
- On Mac, check Activity Monitor
- On RPi, use only 2B models

### Error: "Model download failed"

**Solution:**
- Check your internet connection
- HuggingFace may be temporarily unavailable
- Try manually: visit the model link in the browser
- Choose an alternative model

### Server starts but does not respond

```bash
# Check that the port is not in use
lsof -i :9119

# If there is another process:
kill -9 <PID>

# Or stop Nexe processes:
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"
pkill -f "ollama serve"

# Start again
./nexe go
```

**Note:** The commands `./nexe stop` and `./nexe restart` do not exist. Use:
- **Stop:** Ctrl+C or `pkill`
- **Restart:** API endpoint `/admin/system/restart` (requires API key)

### Very slow performance

**Possible causes:**
- Model too large for your RAM
- Backend not optimized (try MLX if you have Apple Silicon)
- Overloaded CPU
- Full disk (swap is slow)

**Solutions:**
- Choose a smaller model
- Close other applications
- Verify that Metal/GPU is active
- Free up disk space

## Uninstallation

If you want to uninstall NEXE:

```bash
# 1. Stop the server (Ctrl+C or pkill)
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"
pkill -f "ollama serve"

# 2. Remove the virtual environment
rm -rf venv/

# 3. Remove storage (data, logs, vectors, models)
rm -rf storage/

# 4. Remove configuration files
rm -f .env
rm -f .qdrant-initialized

# 5. Remove legacy snapshots (if they exist)
rm -rf snapshots/

# 6. (Optional) Remove the project folder
cd ..
rm -rf server-nexe/
```

**Note:**
- MLX models are in `storage/models/`, NOT in `~/.cache/huggingface/`
- Removing `storage/` removes ALL data (vectors, logs, models)

## Updates

To update NEXE to a new version:

```bash
# 1. Back up your configuration
cp .env .env.backup
cp -r storage/ storage.backup/

# 2. Stop the server
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"

# 3. Download the new version
git pull origin main

# 4. Update dependencies
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 5. Restart the server
./nexe go

# Or via API (if server is running):
curl -X POST http://localhost:9119/admin/system/restart \
  -H "X-API-Key: your-api-key-here"
```

**Note:** `./nexe restart` does NOT exist. Use `./nexe go` or the API endpoint `/admin/system/restart`.

## Next steps

Now that you have NEXE installed:

1. **USAGE.md** - Learn how to use the features
2. **RAG.md** - Understand how memory works
3. **API.md** - Integrate NEXE with other tools
4. **ARCHITECTURE.md** - Dive deeper into the architecture

---

## Quick reference: Environment variables

| Variable | Default value | Description |
|----------|---------------|-------------|
| **Model Engine** |||
| `NEXE_MODEL_ENGINE` | `mlx` | LLM backend: mlx, llama_cpp, ollama |
| `NEXE_DEFAULT_MODEL` | - | Active model (path or ID) |
| `NEXE_MLX_MODEL` | - | Specific MLX model |
| `NEXE_LLAMA_CPP_MODEL` | - | Specific llama.cpp model (GGUF) |
| `NEXE_OLLAMA_MODEL` | - | Specific Ollama model |
| **Security** |||
| `NEXE_PRIMARY_API_KEY` | - | Primary API key (production) |
| `NEXE_PRIMARY_KEY_EXPIRES` | - | Expiry date ISO 8601 |
| `NEXE_SECONDARY_API_KEY` | - | Secondary API key (rotation) |
| `NEXE_SECONDARY_KEY_EXPIRES` | - | Expiry date ISO 8601 |
| `NEXE_ADMIN_API_KEY` | - | Single API key (legacy) |
| `NEXE_CSRF_SECRET` | auto | CSRF tokens secret |
| **Environment** |||
| `NEXE_ENV` | `development` | production or development |
| **Autostart** |||
| `NEXE_AUTOSTART_QDRANT` | `true` | Auto-start Qdrant binary |
| `NEXE_AUTOSTART_OLLAMA` | `true` | Auto-start Ollama if installed |
| **Qdrant** |||
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| **Bootstrap** |||
| `BOOTSTRAP_TTL` | `30` | Token TTL (minutes) |
| `NEXE_BOOTSTRAP_DISPLAY` | `true` | Show token on startup |
| **Production** |||
| `NEXE_APPROVED_MODULES` | - | Module allowlist (comma-separated) |

**Server configuration (personality/server.toml):**
- `core.server.host` → `127.0.0.1`
- `core.server.port` → `9119`
- `core.server.cors_origins` → `["http://localhost:3000"]`

---

## Update changelog (2026-02-04)

### Main changes vs previous version:

1. **✅ Updated .env variables**
   - `NEXE_BACKEND` → `NEXE_MODEL_ENGINE`
   - `MODEL_ID` → `NEXE_DEFAULT_MODEL`
   - `API_KEY` → `NEXE_PRIMARY_API_KEY` + `NEXE_SECONDARY_API_KEY`
   - Added: `NEXE_ENV`, `NEXE_CSRF_SECRET`, `BOOTSTRAP_TTL`, etc.

2. **✅ Corrected paths**
   - `snapshots/qdrant_storage/` → `storage/qdrant/`
   - `./models/` → `storage/models/`
   - `logs/nexe.log` → `storage/logs/*.log`
   - `~/.cache/huggingface/` → `storage/models/` (MLX)

3. **✅ Updated endpoints**
   - `/info` → `/api/info`
   - `/health` response corrected (added uptime, message)
   - `/metrics` → Prometheus text (JSON at `/metrics/json`)

4. **✅ Updated CLI**
   - Recommend `./setup.sh` (not `./setup.sh`)
   - `./nexe memory search` → `./nexe memory recall`
   - REMOVED: `./nexe stop`, `./nexe restart` (do not exist)

5. **✅ Qdrant auto-start**
   - No need to run `./qdrant &` manually
   - Lifespan.py manages auto-start with env vars

6. **✅ Ollama backend**
   - NOT `brew install ollama` (not available)
   - Download .pkg installer or script

7. **✅ Installer**
   - Does NOT run automatic tests
   - Auto-ingestion only on first run (marker file)
   - Creates `storage/` (not `snapshots/`)

8. **✅ Auth headers**
   - `X-API-Key` header (NOT `Authorization: Bearer`)
   - Dual-key support documented

---

**Note:** If you have unresolved issues, check the logs (`./nexe logs`) or review **LIMITATIONS.md** to see if it is a known limitation.

**Contributions:** If you test NEXE on Linux, Windows or RPi, please share your experience to help improve this guide!
