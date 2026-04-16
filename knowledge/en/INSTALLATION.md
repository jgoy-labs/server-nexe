# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "How to install server-nexe: 2 methods. (1) macOS DMG with SwiftUI wizard, bundled Python 3.12, models by RAM tier. (2) CLI: git clone + ./setup.sh (macOS/Linux). Requirements: macOS 13+ or Linux, 8GB RAM minimum. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Default port: 9119."
tags: [installation, setup, dmg, swiftui, wizard, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy"
expires: null
---

# Installation — server-nexe 0.9.7

Two installation methods available. Choose based on your platform and preferences.

## System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | macOS 12+ / Linux x86_64 | macOS 14+ (Apple Silicon) |
| RAM | 8 GB | 16+ GB |
| Disk | 10 GB free | 20+ GB (for larger models) |
| Python | 3.11+ (CLI method) | Bundled 3.12 (DMG method) |

## Method 1: macOS DMG Installer (Recommended)

Native SwiftUI wizard with 6 screens. Bundles Python 3.12 — no system Python dependency.

### ⚡ 100% offline install (since 2026-04-16)

Starting with this version, the DMG bundles **everything** the installer needs:

- Python 3.12 runtime (~45 MB)
- **All Python wheels** pre-compiled for arm64 macOS 13+ (~220 MB): fastapi, pydantic, mlx-lm, mlx-vlm, llama-cpp-python (with Metal), fastembed, onnxruntime, sqlcipher3, cryptography, and the rest of the stack.
- **Multilingual embedding model** pre-downloaded (~470 MB): `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` in ONNX format.

What this changes:

- DMG size: **~700 MB** (previously ~20 MB).
- Once the DMG is downloaded, installation **requires no network** and does not need Xcode Command Line Tools.
- **No macOS prompt asking for "developer tools"** during install.
- RAG works on first boot: the embedding model is already present.
- The only thing that still requires network after installation is downloading your chosen LLM model (Qwen, Gemma, DeepSeek, etc.), unless you use a model already present in a local Ollama.

Requirement: **Apple Silicon (M1+) with macOS 13 Ventura or later**. Intel Macs are no longer a supported target.

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
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detects your platform:
- **macOS:** Checks Homebrew, Python 3.11+, creates venv, installs requirements.txt + requirements-macos.txt (rumps for tray)
- **Linux:** Suggests apt/dnf packages, creates venv, installs requirements.txt only

After setup:
```bash
./nexe go    # Start server → http://127.0.0.1:9119
```

## Model Catalog

### tier_8 (8 GB RAM)
| Model | Engine | Year |
|-------|--------|------|
| Qwen3.5 9B | All | 2025 |
| Gemma 4 E4B | All | 2025 |
| Salamandra 2B | All | 2024 |

### tier_16 (16 GB RAM)
| Model | Engine | Year |
|-------|--------|------|
| Llama 4 Scout (109B/17B active MoE) | All | 2025 |
| Salamandra 7B | All | 2024 |

### tier_24 (24 GB RAM)
| Model | Engine | Year |
|-------|--------|------|
| Qwen3.5 27B | All | 2025 |
| Gemma 4 31B | All | 2025 |

### tier_32 (32 GB RAM)
| Model | Engine | Year |
|-------|--------|------|
| Qwen3.5 35B-A3B (MoE) | All | 2025 |
| DeepSeek R1 Distill 32B | All | 2025 |
| ALIA-40B Instruct | All | 2025 |

### tier_48 (48 GB RAM)
| Model | Engine | Year |
|-------|--------|------|
| Qwen3.5 122B-A10B (MoE) | All | 2025 |
| Llama 4 Maverick (400B/17B active MoE) | All | 2025 |

### tier_64 (64 GB RAM)
| Model | Engine | Year |
|-------|--------|------|
| Qwen3.5 122B-A10B | All | 2025 |
| GPT-OSS 120B | All | 2025 |

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

## Tray App (macOS)

System tray app with: server start/stop, status indicator (pulsing during startup), dark/light mode (auto by time + manual toggle), quick links to Web UI, uninstaller access, multilingual menu (ca/es/en), Ollama opens in background.

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
