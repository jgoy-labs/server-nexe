# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-errors-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Common errors and solutions for server-nexe 1.0.1-beta. Covers installation errors, server startup, Web UI, API authentication, model loading, memory/RAG, streaming, encryption errors, and Bug #19 fixes (MEK fallback, personal_memory wipe)."
tags: [errors, troubleshooting, debugging, installation, startup, web-ui, api, models, memory, streaming, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Common Errors — server-nexe 1.0.1-beta

## Installation Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Python 3.11+ not found | System Python too old | Install Python 3.11+ via Homebrew, or use DMG installer (bundles 3.12) |
| Permission denied on setup.sh | Missing execute permission | `chmod +x setup.sh` |
| ModuleNotFoundError | Dependencies not installed | Activate venv: `source venv/bin/activate`, then `pip install -r requirements.txt` |
| rumps import error on Linux | macOS-only dependency | Normal on Linux — rumps is in requirements-macos.txt, not requirements.txt |

## Server Startup Errors

| Error | Cause | Solution |
|-------|-------|----------|
| Port 9119 already in use | Another process on that port | `lsof -i :9119` and kill, or change port in server.toml |
| Qdrant connection refused | Qdrant embedded failed to initialize | Restart the server with `./nexe go`. If the issue persists, check logs at `storage/logs/`. |
| Ollama not available | Ollama not installed or not running | Install from ollama.com. Server will auto-start Ollama on boot. |
| asyncio.Lock deadlock | Python 3.12 event loop issue | Fixed in v0.8.2 via lazy init in module_lifecycle.py. Update to latest. |
| Server already running (PID X) | Another active server instance | Use "Quit" from the tray, or `pkill -9 server-nexe`. Verify: `lsof -iTCP:9119` |
| Orphaned server (Quit from tray doesn't work) | Bug pre-v0.9.0 (fixed) — tray was not sending SIGTERM to server | Update to v0.9.9. Workaround: `pkill -f "core.app"` or `lsof -iTCP:9119 -sTCP:LISTEN` → `kill -9 <PID>` |

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
| Qwen3.5 fails on MLX (versions < v0.9.7) | Multimodal model incompatible | Since v0.9.7 the MLX backend supports VLM via mlx_vlm. Since v0.9.8 the "any-of" detector covers more architectures. If it still fails, use the Ollama backend as an alternative. |

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

## Historical errors fixed in v0.9.9

### Bug #18 — MEM_DELETE did not delete facts (P0)

**Symptom (pre-v0.9.9):** The user said "forget that my name is Jordi" and the system did not delete the fact from memory. `DELETE_THRESHOLD` of `0.70` was too high and no match exceeded the threshold.

**Fix (v0.9.9):**
- **`DELETE_THRESHOLD` adjusted from `0.70` to `0.20`** (discovered empirically with 8 real e2e tests against embedded Qdrant + fastembed).
- **`_filter_rag_injection`** neutralises `[MEM_SAVE:…]`, `[MEM_DELETE:…]`, `[OLVIDA|OBLIT|FORGET:…]`, `[MEMORIA:…]` patterns on both ingest and retrieval to prevent the model from self-deleting as a side effect.
- **2-turn `clear_all` confirmation:** if the user asks to delete EVERYTHING (not a specific fact), the system asks for confirmation on the next turn (`session._pending_clear_all`). Prevents accidental mass wipes.

### Bug #19a — `personal_memory` wiped on restart

**Symptom (pre-v0.9.9):** Every server restart triggered a defensive "dim-check" branch that silently deleted the `personal_memory` collection. Users lost memory between sessions.

**Fix (v0.9.9):** Defensive branch removed. Memory now persists across restarts without explicit user authorisation.

### Bug #19b — `.enc` sessions survive Keychain reset

**Symptom (pre-v0.9.9):** If the user reset the macOS Keychain (or lost it), the CryptoProvider could not recover the MEK (Master Encryption Key) and `.enc` sessions became unrecoverable even though `~/.nexe/master.key` was on disk.

**Fix (v0.9.9):** MEK fallback order corrected to **file → keyring → env → generate**. If the local file exists, it is used first (previously it failed directly on keyring). This allows `.enc` sessions to survive a Keychain reset provided `~/.nexe/master.key` remains intact.

| Error | Cause | Solution |
|-------|-------|----------|
| Memory lost after restart (pre-v0.9.9) | Bug #19a | Update to v0.9.9. No retroactive workaround: the memory was already lost. |
| .enc sessions do not decrypt after Keychain reset (pre-v0.9.9) | Bug #19b | Update to v0.9.9. If you have the `~/.nexe/master.key` file or the `NEXE_MASTER_KEY` env var, recovery is now automatic. |

## How to report an error

If you hit an error not covered on this page (or that persists despite the workaround), you can report it. Follow these 3 steps.

### 1. Gather evidence from the System Tray

The tray menu (see `INSTALLATION.md` — Tray App (NexeTray, macOS)) has a direct shortcut to the logs:

1. Open the tray menu (`server.nexe` icon in the menu bar).
2. Click **"Open logs"** → opens `storage/logs/server.log` in the editor associated with `.log`.
3. Identify the relevant lines — usually the last **50-100 lines** before the moment of the error.
4. **Alternative**: copy the full log if you want to give maximum context for triage.

### 2. ⚠️ Privacy: review the log BEFORE sending

**The log may contain personal data of yours** because it captures real server activity:

| Data type | Where it may appear in the log |
|-----------|-------------------------------|
| **Conversations** | Fragments of messages you sent to the chat (truncated to 200 chars by default, but still readable) |
| **RAG results** | Chunks of documents you uploaded (`.txt`, `.md`, `.pdf`) |
| **Personal memory** | Facts stored via MEM_SAVE (names, preferences, projects) |
| **Local paths** | `/Users/you/...` and folder names from your machine |
| **Session IDs** | Activity identifiers (useful for correlation, not personal per se) |
| **Stack traces** | May include internal paths from your installation |

**Before sending**, review and:
- Delete or obfuscate personal names and sensitive data
- Replace private paths with `[PATH]` or `~/server-nexe/`
- Consider whether to share the full log or only the relevant fragment
- **Never share** `~/.nexe/master.key` nor the value of `NEXE_MASTER_KEY` or `NEXE_PRIMARY_API_KEY`

### 3. Report channels

| Channel | Best for |
|---------|----------|
| **GitHub Issues** · `github.com/jgoy-labs/server-nexe/issues` | Technical bugs, stack traces, regressions, crashes. Requires a GitHub account |
| **Forum** · `server-nexe.com` | Usage questions, community help, workflow discussions, configuration doubts |

### What to include in the report (GitHub Issue)

- **Version**: you can see it in the tray menu as `server.nexe v1.0.1-beta` (or run `./nexe --version`)
- **OS + hardware**: `sw_vers` and `uname -m` (M1/M2/M3/M4)
- **Active backend**: MLX / llama.cpp / Ollama (visible at `/ui/backends` or in the tray)
- **Model in use**: name of the loaded model
- **Steps to reproduce**: what you were doing just before the error
- **Expected vs actual result**
- **Log fragment** (already reviewed for privacy)
- **Screenshot** if it's a visual error (Web UI, tray)

More context = fewer follow-up questions = faster resolution.

