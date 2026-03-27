# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Usage guide for server-nexe 0.8.2. Covers CLI commands (go, chat, memory, knowledge, status), Web UI features (i18n selector, loading indicator, RAG info panel, model sizes, upload overlay, backend fallback), MEM_SAVE automatic memory, document upload with session isolation, API usage examples (curl, Python), and practical use cases."
tags: [usage, cli, web-ui, chat, memory, knowledge, upload, i18n, loading-indicator, mem-save, api-examples, use-cases]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Usage Guide — server-nexe 0.8.2

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
- **Upload overlay:** Spinner + timer + filename during document upload. Input blocked until complete. Shows chunk count and time after completion.
- **Session persistence:** API key and preferences in localStorage. Sessions survive page refresh.
- **Auto-scroll:** Chat and thinking boxes auto-scroll to bottom during streaming.

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
- User says "Forget my name" → model deletes the matching memory entry
- Next conversation: "What's my name?" → RAG retrieves "name=Jordi" → model answers correctly

No extra commands needed. Works in both CLI and Web UI. Indicators: `[MEM:N]` badge shows count of saved facts.

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

## Practical Use Cases

1. **Personal assistant with memory:** Ask about your projects, preferences, deadlines. MEM_SAVE remembers context automatically.
2. **Private knowledge base:** Upload technical docs, query them in natural language. Session-isolated per conversation.
3. **AI-assisted development:** OpenAI-compatible API works with Cursor, Continue, Zed. Point them to http://127.0.0.1:9119/v1.
4. **Semantic search:** Use /v1/memory/search for similarity-based document retrieval without exact keyword matching.
5. **Model experimentation:** Switch between MLX, llama.cpp, and Ollama backends to compare speed and quality.

## Tips

- **First run:** Memory is empty. Talk to the server, upload docs, or use `nexe knowledge ingest` to populate RAG.
- **Slow first response:** Model loading takes time (10-60s). The loading indicator shows progress.
- **Backend disconnected:** Server auto-falls back to the first available backend. Check with `./nexe status`.
- **Large models:** 32B+ models need 32+ GB RAM and may take minutes to load. Timeout is 600s.
