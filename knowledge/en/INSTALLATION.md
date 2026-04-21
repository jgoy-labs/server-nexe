# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "How to install server-nexe: 2 methods. (1) macOS DMG with SwiftUI wizard, bundled Python 3.12, models by RAM tier. (2) CLI: git clone + ./setup.sh (macOS/Linux). Requirements: macOS 14 Sonoma+ Apple Silicon (M1+), 8GB RAM minimum. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Default port: 9119."
tags: [installation, setup, dmg, swiftui, wizard, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Installation — server-nexe 1.0.2-beta

## In 30 seconds

- **2 methods:** DMG (macOS, SwiftUI wizard) or CLI (`./setup.sh`)
- **DMG ~1.2 GB offline** (wheels + embedding model bundled)
- **Requires macOS 14 Sonoma + Apple Silicon** (M1+)
- **Pick a model by RAM** (catalog of 16 models, 4 tiers 8/16/24/32 GB)
- **Default port:** 9119

---

Two installation methods available. Choose based on your platform and preferences.

## System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | **macOS 14 Sonoma** (Apple Silicon) / Linux ARM64 Ubuntu 24.04 (tested in VM) / Linux x86_64 (partial) | macOS 14+ (Apple Silicon M1+) |
| CPU | **Apple Silicon (M1+) required** — Intel NOT supported | M2 Pro / M3 Pro / M4 |
| RAM | 8 GB | 16+ GB |
| Disk | 10 GB free | 20+ GB (for larger models) |
| Python | 3.11+ (CLI method) | Bundled 3.12 (DMG method) |

> **Breaking in v0.9.9:** macOS 13 Ventura and Intel Macs are out of the supported target. The stack (mlx, mlx-vlm, fastembed ONNX, llama-cpp-python with Metal, arm64 wheels) requires macOS 14 Sonoma and Apple Silicon.

## Method 1: macOS DMG Installer (Recommended)

Native SwiftUI wizard with 6 screens. Bundles Python 3.12 — no system Python dependency.

### ⚡ 100% offline install (since v0.9.9)

Starting with this version, the DMG bundles **everything** the installer needs:

- Python 3.12 runtime (~45 MB)
- **All Python wheels** pre-compiled for arm64 macOS 14+ (~220 MB): fastapi, pydantic, mlx-lm, mlx-vlm, **llama-cpp-python pinned to 0.3.19** (with Metal; 0.3.20 has corrupt wheels Bad CRC-32 on the package server and has been explicitly avoided), fastembed, onnxruntime, sqlcipher3, cryptography, and the rest of the stack.
- **Multilingual embedding model** pre-downloaded (~470 MB): `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` in ONNX format (loaded via fastembed).
- **Precomputed KB embeddings** in `knowledge/.embeddings/` for ca/es/en (10.7× first-boot speedup).

Practical effects:

- DMG size: **~1.2 GB** (grows from wheels + embedding model bundled to make offline install on other machines easier).
- Once the DMG is downloaded, installation **requires no network** and does not need Xcode Command Line Tools (no `CMAKE_ARGS` prompt).
- **No macOS prompt asking for "developer tools"** during install.
- RAG works on first boot: the embedding model is already present.
- The only thing that still requires network after installation is downloading your chosen LLM model (Qwen, Gemma, DeepSeek, etc.), unless you use a model already present in a local Ollama.
- Fallback to PyPI if any bundled wheel is missing (robustness).

Requirement: **Apple Silicon (M1+) with macOS 14 Sonoma or later**. Intel Macs and macOS 13 Ventura are no longer a supported target.

### What the wizard does

1. **Welcome:** Language selector (ca/es/en), logo, version info
2. **Destination:** Folder picker with free space validation
3. **Model Selection:** 4 tabs (small/medium/large/custom) with hardware detection. Shows 15 models with RAM requirements, engine compatibility, and year. Recommends models based on detected RAM/GPU.
4. **Confirmation:** Summary of choices before install
5. **Progress:** 7-step progress bar with real-time log. Python protocol parser ([PROGRESS], [LOG], [DONE], [ERROR] markers). 8-30 minutes depending on model download.
6. **Completion:** API key display, options to add to Dock and Login Items, countdown to launch

### Hardware detection

The wizard uses native `sysctl` calls to detect:
- CPU chip (M1/M2/M3/M4, Intel)
- Total RAM
- Metal GPU support
- Free disk space

Based on detection, recommends appropriate backend and models.

### Backend selection

| Backend | Platform | Best for |
|---------|----------|----------|
| MLX | Apple Silicon only | Fastest on M-series, Metal GPU + Neural Engine |
| llama.cpp | macOS + Linux | Universal GGUF format, Metal acceleration on Mac |
| Ollama | macOS + Linux | If you already have Ollama installed, easiest setup |

### Download

Download the DMG from the GitHub releases page: https://github.com/jgoy-labs/server-nexe/releases

## Method 2: CLI Headless

For users who prefer terminal installation or are on Linux.

```bash
# Linux (Debian/Ubuntu) — one-time prerequisites:
# sudo apt-get install -y python3-venv python3-dev build-essential

git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detects your platform:
- **macOS:** Checks Homebrew, Python 3.11+, creates venv, installs requirements.txt + requirements-macos.txt (rumps for tray)
- **Linux:** Suggests apt/dnf packages, creates venv, installs requirements.txt only

### Linux install — tested environment

Tested end-to-end on Ubuntu 24.04.4 LTS Desktop ARM64 inside a UTM virtual machine on an Apple Silicon Mac (8 GB RAM assigned, Ollama backend on CPU). The installer auto-detects download/temp directories and relocates the install to `~/.local/share/nexe/` (XDG-compliant). Native Linux ARM64/x86_64 hardware is not yet validated.

After setup:
```bash
./nexe go    # Start server → http://127.0.0.1:9119
```

## Model Catalog (16 models, 4 tiers — verified 2026-04-16)

### tier_8 (8 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Gemma 3 4B | Ollama, MLX | 👁 | 🧠 | MLX |
| Qwen3.5 4B | Ollama | 👁 | 🧠 | Ollama |
| Qwen3 4B | Ollama, MLX | | | |

### tier_16 (16 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Gemma 4 E4B | Ollama, MLX | 👁 | 🧠 | MLX |
| Salamandra 7B | Ollama, llama.cpp | | | iberic |
| Qwen3.5 9B | Ollama | 👁 | 🧠 | Ollama |
| Gemma 3 12B | Ollama, MLX | 👁 | 🧠 | |

### tier_24 (24 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Gemma 4 31B | Ollama, MLX | 👁 | 🧠 | ✓ |
| Qwen3 14B | Ollama, MLX | | 🧠 | ✓ |
| GPT-OSS 20B | Ollama, MLX | | 🧠 | |

### tier_32 (32 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 27B | Ollama | 👁 | 🧠 | |
| Gemma 3 27B | MLX, llama.cpp | 👁 | 🧠 | |
| DeepSeek R1 32B | Ollama, llama.cpp | | 🧠 | |
| Gemma 4 31B | Ollama, MLX | 👁 | 🧠 | MLX |
| Qwen3.5 35B-A3B | Ollama | 👁 | 🧠 | |
| ALIA-40B | Ollama, llama.cpp | | | iberic |

Qwen3.5 family only works via Ollama (MLX requires torch). DeepSeek R1 only Ollama/GGUF (MLX does not support qwen2 arch).

### How to install these models

Both Qwen3.5 family and DeepSeek R1 are installed via **Ollama**. First make sure Ollama is running (bundled with the DMG or install from [ollama.com](https://ollama.com)), then:

```bash
# Qwen3.5 family (multimodal + thinking)
ollama pull qwen3.5:4b          # tier_8, ~3.4 GB
ollama pull qwen3.5:9b          # tier_16, ~6 GB
ollama pull qwen3.5:27b         # tier_32, ~17 GB
ollama pull qwen3.5:35b-a3b     # tier_32 MoE, ~21 GB

# DeepSeek R1 (reasoning)
ollama pull deepseek-r1:32b     # tier_32, ~19 GB
```

Once downloaded, configure it in `storage/config/server.toml`:

```toml
[plugins.models]
primary = "qwen3.5:9b"          # or whichever you picked
preferred_engine = "ollama"     # required for these models
```

Restart the server (`./nexe restart` or via the tray) to pick up the change.

### GGUF alternative for DeepSeek R1

If you want to use DeepSeek R1 without Ollama, download a GGUF file from a compatible Hugging Face repo (e.g. `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF`) and place it in `storage/models/`. Then set `preferred_engine = "llama_cpp"`.

Custom models: Ollama (by name) or Hugging Face (GGUF repo URL).

### Loading a custom model

**Ollama** — any model from the public or private registry:
```bash
# 1. Download the model with Ollama
ollama pull model-name:tag

# 2. Configure server-nexe to use it
# Edit storage/config/server.toml:
# [plugins.models]
# primary = "model-name:tag"
```

**MLX (Hugging Face)** — any compatible MLX repository:
```bash
# Download model to storage/models/
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('org/model-name-mlx', local_dir='storage/models/model-name-mlx')
"

# Configure server.toml:
# [plugins.models]
# primary = "storage/models/model-name-mlx"
# preferred_engine = "mlx"
```

**llama.cpp (GGUF)** — any `.gguf` file:
```bash
# Place the file in storage/models/
cp /path/to/model.gguf storage/models/

# Configure server.toml:
# [plugins.models]
# primary = "storage/models/model.gguf"
# preferred_engine = "llama_cpp"
```

Restart the server to apply changes: `./nexe restart`

## Post-Install Verification

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # List loaded modules
./nexe chat                           # Test chat
open http://127.0.0.1:9119/ui        # Web UI
```

## Encryption at Rest (default `auto`)

After installation, encryption activates automatically if sqlcipher3 is available. To manage it manually:

```bash
# Enable encryption
export NEXE_ENCRYPTION_ENABLED=true

# Check current status
./nexe encryption status

# Migrate existing data to encrypted format
./nexe encryption encrypt-all
```

This encrypts SQLite databases (via SQLCipher), chat sessions (.json → .enc), and RAG document text. See SECURITY.md for full details.

## Tray App (NexeTray, macOS)

Menu bar app for controlling the server without a terminal. Built on the `rumps` framework as the `NexeTray` class (`installer/tray.py`, 655 lines). Launched automatically in `--attach` mode once the server is running (via `core/server/runner.py`). The `installer/NexeTray.app` bundle (bash wrapper, `LSUIElement=true`, `CFBundleIdentifier=net.servernexe.tray`) avoids macOS Sequoia provenance restrictions.

### Menu items (top to bottom)

| Item | What it does | Code |
|------|--------------|------|
| **server.nexe v1.0.2-beta** | Non-clickable header. Version read dynamically from `pyproject.toml` via `tomllib` (SSOT). | `tray.py:170-180, 246` |
| **Server running / stopped** | Non-clickable status indicator. Menu bar icon changes: `ICON_RUNNING` (green) when alive, `ICON_STOPPED` (grey) when not. | `tray.py:197` |
| **Start / Stop server** | Spawns or stops the `core.app` process (uvicorn + FastAPI + Qdrant). SIGTERM then SIGKILL if needed. PID stored in `storage/run/server.pid`. | `_toggle_server` → `tray.py:296` |
| **Open Web UI** | Opens `http://127.0.0.1:9119/ui` in the default browser. | `_open_web_ui` → `tray.py:509` |
| **Open logs** | Opens `storage/logs/server.log` in the `.log`-associated editor. | `_open_logs` → `tray.py:512` |
| **Server RAM** | RAM consumed by the server process + loaded model. `psutil` polling runs in a daemon thread (`_RamMonitor`, `installer/tray_monitor.py`, 141 lines) to avoid blocking the menu (post-v0.9.0 fix — previously froze the keyboard). | `tray_monitor.py`; `tray.py:205` |
| **Uptime** | Server uptime calculated from `server_start_time`. | `tray.py:208` |
| **Documentation** | Opens the official documentation. Item added to the main menu (Bug #9) to replace a duplicate link. | `_open_docs` → `tray.py:523` |
| **Settings** | Submenu with 3 options: | `tray.py:227-243` |
| ↳ server-nexe.com | Opens the official website in the browser. | `_open_website` → `tray.py:520` |
| ↳ Support the project | Opens GitHub Sponsors. | `_open_donate` → `tray.py:528` |
| ↳ Uninstall Nexe | Launches the uninstaller with double confirmation, calculates space, removes Dock/Login Items, backs up `storage/` with a timestamp. **Does NOT delete the project folder** (safety option). | `_uninstall` → `tray.py:531` + `installer/tray_uninstaller.py` (284 lines) |
| **Quit** | Stops the server (if running) and closes the tray app. | `_quit` → `tray.py:581` |

### Auto-refresh

A `rumps.Timer(self._update_stats, 5)` runs the `_update_stats` callback (`tray.py:458`) every 5 seconds: refreshes RAM, uptime, and verifies server state (if the process died unexpectedly → icon and status change).

### Translations

Language is detected from `$LANG` / system locale in `_detect_lang`. All strings live in the `T` dictionary in `installer/tray_translations.py` (135 lines) with 3 variants: `ca` (canonical), `es`, `en`.

## Uninstaller

Accessible from tray menu. Double confirmation, calculates space, removes Dock/Login Items, backup storage/ with timestamp, does NOT delete the folder.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Port 9119 in use | `lsof -i :9119` then kill, or change in server.toml |
| Qdrant won't start | Verify that `storage/vectors/` is writable and has no lock files (`*.lock`). Restart the server. |
| Ollama not found | Install from ollama.com, or use MLX/llama.cpp |
| Python version error | Requires 3.11+. DMG bundles 3.12. |
| MLX not available | Apple Silicon only. Use llama.cpp or Ollama. |
| Model download slow | Large models take 30+ min. Timeout 600s. |
| OOM killed | Choose smaller model. 8GB → 2B models. |

## Key Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| NEXE_PRIMARY_API_KEY | Main API key | (generated) |
| NEXE_MODEL_ENGINE | Default backend | auto |
| NEXE_OLLAMA_MODEL | Ollama model | (selected during install) |
| NEXE_LLAMA_CPP_MODEL | GGUF model path | storage/models/*.gguf |
| NEXE_DEFAULT_MAX_TOKENS | Max response tokens | 4096 |
| NEXE_LANG | Server language | ca |
| NEXE_ENV | Environment | production |
| NEXE_ENCRYPTION_ENABLED | Enable encryption at rest | auto (activates if sqlcipher3 available) |
| NEXE_OLLAMA_THINK | Global default for thinking tokens on Ollama models | false |
| NEXE_OLLAMA_EMBED_MODEL | Ollama embedding model (optional, fallback) | nomic-embed-text |
