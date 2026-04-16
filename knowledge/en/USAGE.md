# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-usage-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "How to use server-nexe 1.0.0-beta: CLI (nexe go, nexe chat, nexe memory, nexe knowledge, nexe status), Web UI (http://localhost:9119) with thinking toggle, automatic MEM_SAVE memory, MEM_DELETE (threshold 0.20) with 2-turn clear_all confirmation, PDF/TXT document upload, encryption commands. API examples with curl and Python. How to install models, change language (NEXE_LANG), manage memory."
tags: [usage, cli, web-ui, chat, memory, knowledge, upload, i18n, loading-indicator, mem-save, api-examples, use-cases, encryption, how-to, commands]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Usage Guide — server-nexe 1.0.0-beta

## Table of contents

- [Starting the Server](#starting-the-server)
- [CLI Commands](#cli-commands)
- [Web UI](#web-ui)
  - [Features](#features)
  - [Document Upload](#document-upload)
- [MEM_SAVE — Automatic Memory](#mem_save--automatic-memory)
  - [Full wipe (`CLEAR_ALL`) — 2-turn confirmation](#full-wipe-clear_all--2-turn-confirmation)
- [Encryption](#encryption)
- [API Usage](#api-usage)
  - [Chat (curl)](#chat-curl)
  - [Chat (Python)](#chat-python)
  - [Store to memory](#store-to-memory)
- [Use cases](#use-cases)
- [Tips](#tips)

## In 30 seconds

- **CLI:** `./nexe go` starts server + Qdrant + tray
- **Web UI** at `http://127.0.0.1:9119/ui` (chat, document upload, sessions)
- **OpenAI-compatible API:** `/v1/chat/completions`
- **Automatic MEM_SAVE** (the model saves facts from the conversation)
- **System tray menu** for start/stop, logs, uninstall

---

## Starting the Server

```bash
./nexe go    # Start server → http://127.0.0.1:9119
```

On macOS with tray app installed, the server starts automatically at login.

## CLI Commands

| Command | Description |
|---------|-------------|
| `./nexe go` | Start server (Qdrant + FastAPI + tray) |
| `./nexe chat` | Interactive CLI chat |
| `./nexe chat --rag` | Chat with RAG memory enabled |
| `./nexe chat --verbose` | Chat with RAG weight details per source |
| `./nexe status` | Server status |
| `./nexe modules` | List loaded modules and CLIs |
| `./nexe memory store "text"` | Save text to memory |
| `./nexe memory recall "query"` | Search memory |
| `./nexe memory stats` | Memory statistics |
| `./nexe knowledge ingest` | Index documents from knowledge/ folder |
| `./nexe health` | Health check |
| `./nexe encryption status` | Check encryption status |
| `./nexe encryption encrypt-all` | Migrate data to encrypted format |
| `./nexe encryption export-key` | Export master key for backup |

## Web UI

Access at `http://127.0.0.1:9119/ui`. Requires API key (stored in localStorage after first login).

### Features

- **Chat with streaming:** Real-time token streaming with all 3 backends
- **Model loading indicator:** Blue spinner with chronometer when switching models. Transitions to green "Model loaded (Xs)" permanently in conversation.
- **Model sizes in dropdown:** Shows GB next to each model name (Ollama via /api/tags, MLX via safetensors, llama.cpp via gguf file size)
- **RAG info panel:** Toggle button next to threshold slider. Shows explanation of what the RAG filter does.
- **RAG weight bars:** Color-coded relevance scores (green > 0.7, yellow 0.4-0.7, orange < 0.4). Expandable to show individual sources.
- **Threshold slider:** Adjusts RAG similarity threshold in real-time. Labels: "More info" (low threshold) / "High filter" (high threshold).
- **Language selector:** Footer dropdown CA/ES/EN. Changes all UI text instantly via `applyI18n()`. Server is source of truth (POST /ui/lang).
- **Backend dropdown:** Shows all configured backends. Marks disconnected backends. Auto-fallback to first available backend if selected one is down.
- **Thinking tokens:** Auto-scroll thinking box for models like qwen3.5 that emit thinking tokens.
- **Per-session thinking toggle (v0.9.9):** ✨ sparkles icon next to the input + 🧠 dropdown in the session header to enable/disable thinking mode (reasoning tokens) for that session. Only available for compatible families (`THINKING_CAPABLE`: qwen3.5, qwen3, qwq, deepseek-r1, gemma3/4, llama4, gpt-oss). Default OFF. If the current model does not support thinking, the UI shows a warning and offers automatic retry without thinking. Internal endpoint: `PATCH /ui/session/{id}/thinking`.
- **Upload overlay:** Spinner + timer + filename during document upload. Input blocked until complete. Shows chunk count and time after completion.
- **Session persistence:** API key and preferences in localStorage. Sessions survive page refresh.
- **Auto-scroll:** Chat and thinking boxes auto-scroll to bottom during streaming.
- **Collapsible sidebar:** Toggle with panel-left icon, state persistent in localStorage. (new 2026-04-01)
- **Rename sessions:** Pencil button for inline rename via PATCH endpoint. (new 2026-04-01)
- **Copy text button:** Copy responses to clipboard with visual copy/check feedback. (new 2026-04-01)
- **Collection toggles:** Sidebar checkboxes to enable/disable Memory/Knowledge/Docs individually. Persistent in localStorage. CLI: `--collections`. (new 2026-04-01)
- **Welcome screen:** Clickable features ("Chat" focuses input, "Documents" opens upload). (new 2026-04-02)
- **Blue MEM_SAVE block:** Saved memories shown as collapsible blue `<details>` (like orange thinking). (new 2026-04-01)
- **Document truncation warning:** Yellow notice when document is too large for context. (new 2026-04-02)
- **Auto light/dark mode:** Detects system preference via `matchMedia`. (existing)

### Document Upload

Upload documents via the paperclip button in the chat input. Supported: .txt, .md, .pdf.

- Documents indexed into `user_knowledge` collection with session_id
- Only visible within the uploading session (no cross-session contamination)
- Metadata generated without LLM (instant, no model blocking)
- Shows "Loaded (N fragments, Xs)" message after completion
- Documents marked "per-chat" to indicate session isolation

## MEM_SAVE — Automatic Memory

The model automatically extracts and saves facts from conversations:

- User says "My name is Jordi" → model saves `[MEM_SAVE: name=Jordi]`
- User says "Forget my name" → MEM_DELETE: similarity search (**threshold 0.20** since v0.9.9, previously 0.70), deletes closest match, anti-re-save guard
- Next conversation: "What's my name?" → RAG retrieves "name=Jordi" → model answers correctly

No extra commands needed. Works in both CLI and Web UI. Indicators: `[MEM:N]` badge shows count of saved facts.

### Full wipe (`CLEAR_ALL`) — 2-turn confirmation

If you ask to delete **all** memory ("delete everything", "forget everything", "olvida todo"), the system does **not delete immediately**. It follows a 2-turn flow:

1. **Turn 1:** Detects the pattern and asks for confirmation ("Are you sure? This will erase all memory. Reply 'yes' to confirm.").
2. **Turn 2:** If you reply `yes`/`confirm`/`ok`, the deletion runs. Any other reply cancels the operation.

This prevents accidental mass wipes caused by an ambiguous message or injection from a document.

## Encryption

Encryption at rest defaults to `auto` — it activates automatically if `sqlcipher3` is available. To force it on or manage it manually:

```bash
# Check current status
./nexe encryption status

# Enable and migrate existing data
export NEXE_ENCRYPTION_ENABLED=true
./nexe encryption encrypt-all

# Export master key (for backup — store securely!)
./nexe encryption export-key
```

What gets encrypted: SQLite databases (memories.db via SQLCipher), chat sessions (.json → .enc), RAG document text (TextStore). Qdrant payloads already contain no text (vectors + IDs only).

## API Usage

### Chat (curl)
```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "use_rag": true}'
```

### Chat (Python)
```python
import requests

response = requests.post(
    "http://127.0.0.1:9119/v1/chat/completions",
    headers={"X-API-Key": "YOUR_KEY"},
    json={"messages": [{"role": "user", "content": "Hello"}], "use_rag": True}
)
print(response.json()["choices"][0]["message"]["content"])
```

### Store to memory
```bash
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Project deadline is March 30", "collection": "user_knowledge"}'
```

## Use cases

See **[[USE_CASES|practical use cases]]** for the full list with detailed context (personal assistant, private knowledge base, AI-assisted dev with Cursor/Continue/Zed, semantic search, model experimentation, secure local AI) and guidance on **when server-nexe is NOT the best tool**.

## Tips

- **First run:** Memory is empty. Talk to the server, upload docs, or use `nexe knowledge ingest` to populate RAG.
- **Slow first response:** Model loading takes time (10-60s). The loading indicator shows progress.
- **Backend disconnected:** Server auto-falls back to the first available backend. Check with `./nexe status`.
- **Large models:** 32B+ models need 32+ GB RAM and may take minutes to load. Timeout is 600s.
- **Encryption:** Enable encryption early — migrating large datasets later takes time. Export and store the master key securely.
