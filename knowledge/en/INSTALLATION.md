# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Installation guide for server-nexe 0.8.5 pre-release. Three methods: macOS DMG with SwiftUI wizard (6 screens, hardware detection, 17 models, bundled Python 3.12), CLI headless (setup.sh with Linux support), and Docker (docker-compose with Ollama). Covers system requirements, backend selection, model catalog by RAM tier, post-install verification, tray app, uninstaller, encryption opt-in, and troubleshooting."
tags: [installation, setup, dmg, swiftui, wizard, docker, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Installation — server-nexe 0.8.5 pre-release

Three installation methods available. Choose based on your platform and preferences.

## System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | macOS 12+ / Linux x86_64 | macOS 14+ (Apple Silicon) |
| RAM | 8 GB | 16+ GB |
| Disk | 10 GB free | 20+ GB (for larger models) |
| Python | 3.11+ (CLI method) | Bundled 3.12 (DMG method) |

## Method 1: macOS DMG Installer (Recommended)

Native SwiftUI wizard with 6 screens. Bundles Python 3.12 — no system Python dependency.

### What the wizard does

1. **Welcome:** Language selector (ca/es/en), logo, version info
2. **Destination:** Folder picker with free space validation
3. **Model Selection:** 4 tabs (small/medium/large/custom) with hardware detection. Shows 17 models with RAM requirements, engine compatibility, and year. Recommends models based on detected RAM/GPU.
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

## Method 3: Docker

For Linux servers or containerized deployments.

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
docker-compose up
```

- **Dockerfile:** Python 3.12-slim, embedded Qdrant binary (auto-detects linux-amd64/arm64), non-root user (`nexe`), EXPOSE 9119 6333
- **docker-compose.yml:** Two services — Nexe + Ollama
- **docker-entrypoint.sh:** Sequential start (Qdrant → wait for health → Nexe), 15s timeout with warning

Mount `storage/` for persistent data (models, Qdrant vectors, logs).

## Model Catalog (17 models)

### Small (8 GB RAM)
| Model | Size | Engine | Year |
|-------|------|--------|------|
| Qwen3 1.7B | 1.1 GB | All | 2025 |
| Qwen3.5 2B | 1.5 GB | Ollama only | 2025 |
| Phi-3.5 Mini | 2.4 GB | All | 2024 |
| Salamandra 2B | 1.5 GB | All | 2024 |
| Qwen3 4B | 2.5 GB | All | 2025 |

### Medium (12-16 GB RAM)
| Model | Size | Engine | Year |
|-------|------|--------|------|
| Mistral 7B | 4.1 GB | All | 2023 |
| Salamandra 7B | 4.9 GB | All | 2024 |
| Llama 3.1 8B | 4.7 GB | All | 2024 |
| Qwen3 8B | 5.0 GB | All | 2025 |
| Gemma 3 12B | 7.6 GB | All | 2025 |

### Large (32+ GB RAM)
| Model | Size | Engine | Year |
|-------|------|--------|------|
| Qwen3.5 27B | 17 GB | Ollama only | 2025 |
| Qwen3 32B | 20 GB | All | 2025 |
| Gemma 3 27B | 17 GB | All | 2025 |
| DeepSeek R1 32B | 20 GB | All | 2025 |
| Llama 3.1 70B | 40 GB | All | 2024 |

Custom models: Ollama (by name) or Hugging Face (GGUF repo URL).

## Post-Install Verification

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # List loaded modules
./nexe chat                           # Test chat
open http://127.0.0.1:9119/ui        # Web UI
```

## Encryption at Rest (opt-in)

After installation, you can enable encryption at rest:

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
| Qdrant won't start | Check port 6333, check binary permissions |
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
| NEXE_ENCRYPTION_ENABLED | Enable encryption at rest | false |
