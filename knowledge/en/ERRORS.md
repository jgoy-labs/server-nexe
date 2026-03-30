# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-errors-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Common errors and solutions for server-nexe 0.9.0 pre-release. Covers installation errors, server startup, Web UI, API authentication, model loading, memory/RAG, Docker, streaming, and encryption errors."
tags: [errors, troubleshooting, debugging, installation, startup, web-ui, api, models, memory, docker, streaming, encryption]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Common Errors — server-nexe 0.9.0 pre-release

## Installation Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Python 3.11+ not found | System Python too old | Install Python 3.11+ via Homebrew, or use DMG installer (bundles 3.12) |
| Permission denied on setup.sh | Missing execute permission | `chmod +x setup.sh` |
| ModuleNotFoundError | Dependencies not installed | Activate venv: `source venv/bin/activate`, then `pip install -r requirements.txt` |
| rumps import error on Linux | macOS-only dependency | Normal on Linux — rumps is in requirements-macos.txt, not requirements.txt |
| Qdrant binary not found | Not downloaded | Run installer again, or download manually for your platform |

## Server Startup Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Port 9119 already in use | Another process on that port | `lsof -i :9119` and kill, or change port in server.toml |
| Qdrant connection refused | Qdrant not running or wrong port | Check port 6333, restart server with `./nexe go` |
| Ollama not available | Ollama not installed or not running | Install from ollama.com. Server will auto-start Ollama on boot. |
| asyncio.Lock deadlock | Python 3.12 event loop issue | Fixed in v0.8.2 via lazy init in module_lifecycle.py. Update to latest. |

## Web UI Errors

| Error | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Wrong or missing API key | Check key in localStorage matches `.env` NEXE_PRIMARY_API_KEY |
| 403 CSRF | CSRF token mismatch | Clear browser cache and reload |
| Chat not responding | Model loading (first message) | Wait for loading indicator. Can take 10-60s for first load. |
| Streaming stops at 2nd message | _renderTimer bug (pre-v0.8.2) | Fixed in v0.8.2. Update to latest. |
| Old JS/CSS cached | Browser aggressive caching | Fixed with cache-busting (?v=timestamp). Hard refresh: Cmd+Shift+R |
| 429 Too Many Requests | Rate limit exceeded | Wait and retry. Limits per endpoint (5-30/min for UI). |

## API Errors

| Error | Cause | Solution |
|-------|-------|----------|
| 401 Missing X-API-Key | No auth header | Add `-H "X-API-Key: YOUR_KEY"` to request |
| 429 Rate Limited | Too many requests | Wait and retry. Check rate limits in `.env` |
| 408 Timeout | Model inference too slow | Increase NEXE_DEFAULT_MAX_TOKENS timeout. Large models need 600s. |
| Empty error message | httpx.ReadTimeout has empty str() | Fixed with repr(e). Check server logs. |

## Model Errors

| Error | Cause | Solution |
|-------|-------|----------|
| OOM Killed | Model too large for RAM | Use smaller model. 8GB RAM → 2B models max. |
| Model loading very slow | Large model or cold GPU | Normal for 32B+ models. Loading indicator shows progress. |
| MLX not available | Intel Mac or Linux | MLX is Apple Silicon only. Use llama.cpp or Ollama. |
| Qwen3.5 fails on MLX | Multimodal model incompatible | Use Ollama backend for Qwen3.5 models. |

## Memory/RAG Errors

| Error | Cause | Solution |
|-------|-------|----------|
| RAG returns nothing | Empty memory (cold start) | Upload docs, use `nexe knowledge ingest`, or chat to populate MEM_SAVE. |
| Wrong RAG results | Threshold too high | Lower threshold via UI slider or NEXE_RAG_*_THRESHOLD env vars. |
| Duplicate memories | Dedup threshold issue | Dedup checks similarity > 0.80. Very similar but different entries may both save. |
| Documents not visible | Wrong session | Documents are session-isolated. Upload in the same session you're chatting in. |

## Encryption Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Keyring not available | OS keyring not configured (Linux without Secret Service) | Set `NEXE_MASTER_KEY` env var or create `~/.nexe/master.key` file (chmod 600) |
| sqlcipher3 not installed | Missing dependency | `pip install sqlcipher3`. Falls back to plaintext SQLite with warning. |
| Cannot decrypt data | Wrong master key | Ensure the same key is used. Export with `./nexe encryption export-key`. |
| Migration failed | Corrupted database or interrupted migration | Backup .bak file is preserved. Restore from backup and retry. |
| Encryption status: disabled | Feature not enabled | Set `NEXE_ENCRYPTION_ENABLED=true` in .env or environment |

## Docker Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Qdrant not starting | Binary architecture mismatch | Docker auto-detects amd64/arm64. Check Dockerfile platform. |
| Cannot connect to Ollama | Network isolation | Ollama runs as separate docker-compose service. Check service name in config. |
| Storage not persisting | Volume not mounted | Mount `storage/` as Docker volume. |
