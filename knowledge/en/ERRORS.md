# === METADATA RAG ===
versio: "1.0"
data: 2026-03-12
id: nexe-errors

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Common NEXE 0.8 errors guide: error messages, causes and solutions. Covers installation, startup, Web UI, authentication, model, memory and API errors."
tags: [errors, troubleshooting, solutions, debug, 401, 403, 404, qdrant, mlx, model, web-ui, installation]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# NEXE 0.8 — Common Errors and Solutions

A reference guide for the most common errors users encounter with NEXE, including likely causes and recommended solutions.

---

## Installation Errors

### `No s'ha pogut trobar Python 3.10+`
**Cause:** Python not installed or version too old.
**Solution:** `brew install python@3.12` and re-run `./setup.sh`

### `Permission denied: ./setup.sh` or `./nexe`
**Cause:** Script lacks execute permission.
**Solution:** `chmod +x setup.sh nexe`

### `ModuleNotFoundError`
**Cause:** Virtual environment not created correctly or dependencies not installed.
**Solution:** Re-run `./setup.sh` — reinstalls the environment from scratch.

### `NameError: name 'DIM' is not defined`
**Cause:** Bug in `installer/installer_setup_env.py` in an old version — the ANSI constant `DIM` was missing from the import.
**Solution:** `git pull` to get the fixed version and re-run `./setup.sh`.

### `Python version error` / `requires Python 3.10+`
**Cause:** Python 3.9 or earlier installed on the system.
**Solution:** `brew install python@3.11` or `brew install python@3.12`.

---

## Server Startup Errors

### `Port 9119 already in use`
**Cause:** Another NEXE instance (or another process) is already using port 9119.
**Solution:**
```bash
./nexe status
lsof -ti:9119 | xargs kill
./nexe go
```

### `Qdrant connection refused`
**Cause:** Qdrant service is not running.
**Solution:** `./nexe go` starts it automatically if `NEXE_AUTOSTART_QDRANT=true` is in `.env`. If the problem persists: `./nexe stop` and `./nexe go` again.

### `MLX not found` / `No module named 'mlx'`
**Cause:** MLX not installed or processor is not Apple Silicon.
**Solution:** MLX requires Apple Silicon (M1/M2/M3/M4). If you have Intel Mac or Linux, switch to `llama_cpp` or `ollama` in `.env`:
```
NEXE_MODEL_ENGINE=llama_cpp
```

### Server starts but does not respond
**Cause:** Model is loading (can take 10–30 s) or there is a silent error.
**Solution:** Wait for the model to finish loading. Check with:
```bash
curl http://localhost:9119/health
./nexe logs
```

### `OOM killed` / `Killed` (process killed)
**Cause:** Model is too large for the available RAM.
**Solution:** Choose a smaller model in `.env`. General guidelines:
- 8 GB RAM → Qwen3 1.7B or Qwen3 4B
- 16 GB RAM → Qwen3 8B or Mistral 7B
- 32 GB+ RAM → Qwen3 32B or Llama 3.1 70B

---

## Web UI Errors

### Login screen appears but key doesn't work (`Clau incorrecta`)
**Cause 1:** The entered key is incorrect.
**Solution:** Find the correct key with:
```bash
grep NEXE_PRIMARY_API_KEY .env
```
Copy it exactly, with no spaces or line breaks.

**Cause 2:** Server is running old code (without the login system).
**Solution:**
```bash
git pull
lsof -ti:9119 | xargs kill
./nexe go
```

### `GET /ui/auth 404 Not Found` in logs
**Cause:** The server doesn't have the `/ui/auth` endpoint — old code version.
**Solution:** `git pull` and restart the server.

### `POST /ui/chat 403 Forbidden` in logs
**Cause:** CSRF error — session cookie doesn't match or is from an older version.
**Solution:** Open the Web UI in incognito mode or clear cookies for `localhost:9119`. With the current version (API key login) this error should no longer appear.

### Web UI loads but chat doesn't respond
**Cause:** Model is still loading, or Qdrant is not active.
**Solution:** Wait 10–30 s and check:
```bash
curl http://localhost:9119/health
```

---

## API Authentication Errors

### `401 Unauthorized` on API requests
**Cause:** API key not sent or incorrect.
**Solution:**
```bash
curl -H "X-API-Key: $(grep NEXE_PRIMARY_API_KEY .env | cut -d= -f2)" \
  http://localhost:9119/v1/chat/completions
```

### API key has expired
**Cause:** `NEXE_PRIMARY_KEY_EXPIRES` in `.env` is a past date.
**Solution:** Generate a new key and update `.env`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Model Errors

### Very slow download
**Cause:** Slow connection or very large model (7B+ models are 4–20 GB).
**Solution:** Wait, or choose a smaller model.

### Model responds very slowly
**Cause:** Model too large for available RAM/GPU.
**Solution:** On Apple Silicon M1 with 8 GB RAM, Qwen3 4B is the recommended maximum.

---

## Memory / RAG Errors

### Memory doesn't recall previously saved information
**Cause:** Information was saved in a different session, or Qdrant restarted and lost its index.
**Solution:**
```bash
./nexe memory stats
./nexe memory recall "keyword from saved info"
```

---

## General Errors

### Code changes are not reflected in the running server
**Cause:** The running server is using old code (not restarted after update).
**Solution:**
```bash
lsof -ti:9119 | xargs kill
./nexe go
```
