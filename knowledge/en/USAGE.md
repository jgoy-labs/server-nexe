# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Practical usage guide for NEXE. Starting and stopping the server, CLI commands, interactive chat with unified CLI+UI pipeline, memory system, document upload via /upload command, adaptive RAG chunk size by document size, RAG headers for optimal indexing, API usage and practical use cases."
tags: [usage, cli, chat, memory, rag, api, web-ui, upload, rag-header, unified-pipeline]
chunk_size: 900
priority: P1

# === OPCIONAL ===
lang: en
type: tutorial
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Usage Guide - NEXE 0.8

This guide teaches you how to use NEXE with practical examples. It assumes you already have NEXE installed (if not, refer to **INSTALLATION.md**).

## Table of Contents

1. [Starting and stopping the server](#starting-and-stopping-the-server)
2. [Basic CLI](#basic-cli)
3. [Interactive chat](#interactive-chat)
4. [Uploading documents to chat](#uploading-documents-to-chat)
5. [Memory system (RAG)](#memory-system-rag)
6. [RAG headers for documents](#rag-headers-for-documents)
7. [Document management](#document-management)
8. [Using the API](#using-the-api)
9. [Web UI](#web-ui)
10. [Practical use cases](#practical-use-cases)
11. [Tips and best practices](#tips-and-best-practices)

---

## Starting and stopping the server

### Start the server

```bash
cd server-nexe
./nexe go
```

**Expected output:**
```
🚀 Iniciant NEXE 0.8...
✓ Backend: MLX
✓ Model: Phi-3.5 Mini
✓ Qdrant: Connectat
✓ Port: 9119

Servidor operatiu a http://localhost:9119
Web UI a http://localhost:9119/ui
API docs a http://localhost:9119/docs

Prem Ctrl+C per aturar
```

### Check status

```bash
./nexe status
```

**Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEXE Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Servidor: ✓ Actiu (http://localhost:9119)
Backend: MLX
Model: Phi-3.5 Mini (2.4 GB)
RAM en ús: 3.2 GB
Uptime: 2h 15min

Memòria RAG:
  Documents indexats: 15
  Vectors emmagatzemats: 342
  Mida base de dades: 48 MB
```

### Stop the server

If running in the foreground: `Ctrl+C`

**Note:** There is no dedicated `./nexe stop` command. To stop a background server, use `Ctrl+C` or locate the process and kill it manually.

---

## Basic CLI

### Available commands

```bash
./nexe --help
```

**Main commands:**

| Command | Description |
|---------|-------------|
| `go` | Start the server |
| `status` | System status |
| `chat` | Interactive chat |
| `memory` | Memory management (store, recall, stats, cleanup) |
| `knowledge` | Document management (ingest, status) |
| `logs` | View logs |
| `--version` | NEXE version |

### Command-specific help

```bash
# Help for a specific command
./nexe chat --help
./nexe memory --help
```

---

## Interactive chat

The CLI uses exactly the **same pipeline as the Web UI**: server sessions, automatic memory and semantic search always active. No `--rag` flag needed.

### Start the chat

```bash
./nexe chat
```

**Session example:**
```
  🚀 Nexe Chat
  Engine: mlx  |  Model: Qwen3-32B-4bit  |  Memory: ✅ Active
  ─────────────────────────────────────────
  Commands: /upload <path> · /save <text> · /recall <query> · /help
  Type "exit" or Ctrl+C to quit

Tu: Hello, who are you?
  ⠹ 1.2s
Nexe: Hi! I'm Nexe, the expert assistant for Server Nexe.
How can I help you?

Tu: What projects do I have active?
  ⠸ 2.8s
Nexe: Based on my memory, you're working on NEXE 0.8 and NAT7...
```

The **spinner with timer** (`⠹ 2.8s`) shows the system is searching RAG and loading the model. It disappears when the first token arrives.

### Chat commands

| Command | Description |
|---------|-------------|
| `/upload <path>` | Upload a document to analyse |
| `/save <text>` | Save information to persistent memory |
| `/recall <query>` | Direct memory search |
| `/help` | Show all commands |
| `clear` | Reset session (fresh context, RAG intact) |
| `exit` / `quit` | Exit the chat |

### Session context

Within a session, the model **remembers everything you said**. Context persists until you `clear` or close the chat.

- `clear` → new session, history reset. **RAG is not cleared**: previously uploaded documents remain accessible via semantic search.
- Closing and reopening chat → new session, but RAG memory persists across sessions.

### Command options

```bash
# Specific engine
./nexe chat --engine mlx

# Note: --rag and --system are ignored (UI pipeline always manages them)
```

---

## Uploading documents to chat

You can upload documents directly in the CLI chat and ask questions about them. Works the same as dragging a file into the Web UI.

### /upload command

```bash
# Inside the chat:
Tu: /upload /path/to/report.pdf
📎 Uploading report.pdf...
✅ report.pdf indexed (24 parts). You can now ask questions about the document.

Tu: give me an executive summary
Nexe: The document covers...
```

**Paths with spaces:** use `\ ` to escape spaces:
```
/upload /Users/jordi/Documents/My\ Project/report.md
```

### Supported formats

`.pdf`, `.txt`, `.md`, `.markdown` and other text formats.

### How upload works

1. **Session slot**: the document is attached to the current session. The first message receives it as full context (up to 50 parts).
2. **RAG indexing**: all chunks are saved to `nexe_web_ui`. They persist across sessions and are retrieved by semantic search.

### Multiple documents

```
/upload doc1.pdf          → indexed + attached to session
You: summarise doc1?      → receives doc1 as full context
/upload doc2.pdf          → indexed + overwrites session slot
You: summarise doc2?      → receives doc2 as full context
You: compare doc1 and doc2 → both accessible via semantic RAG
```

**Recommendation:** ask the main question **right after each `/upload`** to get full context. Later questions access via RAG.

---

## Memory system (RAG)

The RAG system allows you to store information and retrieve it automatically.

### Store information

```bash
# Store a sentence
./nexe memory store "El meu color favorit és el blau"

# Store structured information
./nexe memory store "Projecte: NEXE - Estat: v0.8 - Plataforma: macOS"
```

### Retrieve from memory

```bash
# Search/retrieve information
./nexe memory recall "color favorit"

# Results:
# [1] El meu color favorit és el blau (similaritat: 0.92)
```

### Clean memory

```bash
# Clean old memory (cleanup)
./nexe memory cleanup
```

### Memory statistics

```bash
./nexe memory stats
```

**Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Estadístiques de Memòria
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total entrades: 342
Mida total: 48.2 MB
Vectors: 342
Col·leccions: 3 (nexe_web_ui, nexe_documentation, user_knowledge)

Model d'embeddings: nomic-embed-text (Ollama) + fallbacks
Dimensió vectors: 768

Última actualització: fa 2 hores
```

---

## RAG headers for documents

The **RAG header** is the key to high-quality semantic search. When a document has a header, the system uses `chunk_size`, `abstract` and `tags` to index it optimally. Without a header, the system auto-generates one.

### Adaptive chunk size (no header)

When uploading a document without a header (via `/upload` or Web UI), the system automatically picks `chunk_size` based on size:

| Document size | Chunk size | Equivalent |
|---------------|-----------|------------|
| < 20,000 chars | 800 | ~7 pages |
| < 100,000 chars | 1,000 | ~33 pages |
| < 300,000 chars | 1,200 | ~100 pages |
| ≥ 300,000 chars | 1,500 | > 100 pages |

A 170-page document (~510,000 chars) will use `chunk_size: 1500` automatically.

### RAG header format

For best quality, add a header to your `.md` or `.txt` document:

```markdown
# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: unique-document-name

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Concise description of the content. Max 500 chars. The model uses this to understand what the document is about."
tags: [tag1, tag2, tag3]
chunk_size: 1200
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Author"
expires: null
---

[Document content here...]
```

### Header fields

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `id` | Yes | unique text | Document identifier |
| `abstract` | Yes | text (max 500) | Summary for the model |
| `tags` | Yes | [list] | Search keywords |
| `chunk_size` | Yes | 400–2000 | Fragment size (800 = normal doc, 1500 = large doc) |
| `priority` | Yes | P0–P3 | P0 = highest priority, P3 = low |
| `lang` | No | ca/es/en/multi | Document language |
| `type` | No | docs/tutorial/api/faq/notes | Type |
| `collection` | No | user_knowledge | Where it's indexed |

### Recommended priorities

- **P0**: Critical documentation (specs, contracts)
- **P1**: Important documentation (guides, tutorials)
- **P2**: General notes (default for uploads without header)
- **P3**: Secondary reference material

### Example for a 170-page report

```markdown
# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: report-INF-2026-00007

abstract: "Technical report INF-2026-00007. NAT7 system performance analysis for Q1 2026. Includes metrics, conclusions and recommendations."
tags: [report, NAT7, performance, Q1-2026, analysis]
chunk_size: 1500
priority: P1

lang: en
type: docs
collection: user_knowledge
---

[Report content...]
```

---

## Document management

NEXE can index local documents so you can query them using natural language.

### Index knowledge

```bash
# Index a file or directory
./nexe knowledge ingest /path/to/docs/

# View indexed knowledge status
./nexe knowledge status

# Supported formats:
# - Markdown (.md)
# - Plain text (.txt)
# - Other formats depending on configuration
```

### Query documents

Once indexed, documents are used automatically in chat with `--rag`:

```bash
./nexe chat --rag

Tu: Quina és l'arquitectura de NEXE?

NEXE: Segons el document ARCHITECTURE.md, NEXE està
estructurat en tres capes principals: Core (servidor
FastAPI), Plugins (backends modulars) i Memory
(sistema RAG amb Qdrant)...
```

**Note:** System documentation (inside `knowledge/`) is automatically indexed into the `nexe_documentation` collection at server startup.

---

## Using the API

NEXE provides an OpenAI-compatible REST API for integration with other tools.

### Main endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/info` | GET | System information |
| `/v1/chat/completions` | POST | Chat completion (OpenAI-compatible) |
| `/v1/memory/store` | POST | Store to memory |
| `/v1/memory/search` | POST | Search memory |
| `/docs` | GET | API documentation (Swagger) |

**Important:** All `/v1/*` endpoints require authentication with the `X-API-Key` header.

### Examples with curl

#### Health check

```bash
curl http://localhost:9119/health
```

**Response:**
```json
{
  "status": "ok",
  "message": "NEXE server is running",
  "version": "0.8.0",
  "uptime": 7200
}
```

#### Chat completion

```bash
curl -X POST http://localhost:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "model": "phi3",
    "messages": [
      {"role": "user", "content": "Hola, com estàs?"}
    ],
    "temperature": 0.7,
    "max_tokens": 150
  }'
```

**Response:**
```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1706950400,
  "model": "phi3",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hola! Estic bé, gràcies per preguntar. Sóc un assistent d'IA funcionant en local. Com et puc ajudar avui?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 28,
    "total_tokens": 40
  }
}
```

#### Store to memory

```bash
curl -X POST http://localhost:9119/v1/memory/store \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "text": "El meu framework favorit és FastAPI",
    "collection": "user_knowledge",
    "metadata": {"category": "preferències"}
  }'
```

#### Search memory

```bash
curl -X POST http://localhost:9119/v1/memory/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "query": "framework favorit",
    "collection": "user_knowledge",
    "limit": 5
  }'
```

### Using Python

```python
import requests

# Configuration
BASE_URL = "http://localhost:9119"
API_KEY = "YOUR_API_KEY"  # Des de .env NEXE_PRIMARY_API_KEY

# Chat
def chat(message):
    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        headers={"X-API-Key": API_KEY},
        json={
            "messages": [{"role": "user", "content": message}],
            "temperature": 0.7
        }
    )
    return response.json()["choices"][0]["message"]["content"]

# Example
resposta = chat("Explica'm què és Python")
print(resposta)

# Memory
def store_memory(text, collection="user_knowledge"):
    response = requests.post(
        f"{BASE_URL}/v1/memory/store",
        headers={"X-API-Key": API_KEY},
        json={"text": text, "collection": collection}
    )
    return response.json()

def search_memory(query, collection="user_knowledge"):
    response = requests.post(
        f"{BASE_URL}/v1/memory/search",
        headers={"X-API-Key": API_KEY},
        json={"query": query, "collection": collection, "limit": 3}
    )
    return response.json()

# Example
store_memory("El meu projecte actual és NEXE")
results = search_memory("projecte actual")
print(results)
```

### Using curl and jq

```bash
# Chat with formatted response
curl -s -X POST http://localhost:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"messages":[{"role":"user","content":"Hola"}]}' \
  | jq -r '.choices[0].message.content'

# System information
curl -s http://localhost:9119/api/info | jq
```

---

## Web UI

NEXE includes a basic (experimental) web interface.

### Accessing the Web UI

1. Start the server: `./nexe go`
2. Open your browser at: `http://localhost:9119/ui`
3. A **login screen** will appear — enter your API key

The API key is in `.env` → `NEXE_PRIMARY_API_KEY`. To find it:

```bash
grep NEXE_PRIMARY_API_KEY .env
```

The key is stored in the browser's `localStorage`: you won't need to enter it again on future visits. To log out or change the key, open DevTools → Application → Local Storage → delete `nexe_api_key`.

**External access (Tailscale):** use the same key, replacing `localhost` with your Tailscale IP: `http://100.x.x.x:9119/ui`

### Web UI features

**Available:**
- Interactive chat
- Conversation history
- Toggle RAG on/off
- Basic parameters (temperatura, max_tokens)

**Not available (yet):**
- Document management
- Memory visualization
- Advanced configuration
- Statistics and charts

**Note:** The Web UI is very basic and is not the project's priority. The CLI and API are more complete.

---

## Practical use cases

### 1. Personal assistant with memory

**Goal:** Have an assistant that remembers information about you.

```bash
# 1. Store personal information
./nexe memory store "El meu nom és Jordi"
./nexe memory store "Treballo en desenvolupament d'IA"
./nexe memory store "Els meus projectes són NEXE i JGOY Quest"
./nexe memory store "M'agrada programar en Python i treballar amb FastAPI"

# 2. Use chat with memory
./nexe chat --rag

Tu: Qui sóc jo?
NEXE: Ets Jordi, treballes en desenvolupament d'IA
i els teus projectes actuals són NEXE i JGOY Quest...

Tu: Quin llenguatge faig servir?
NEXE: T'agrada programar en Python i treballes
amb FastAPI...
```

### 2. Project knowledge base

**Goal:** Index your project documentation.

```bash
# 1. Index the documentation
./nexe knowledge ingest ./projecte/docs/

# 2. Query it using natural language
./nexe chat --rag

Tu: Com funciona el sistema d'autenticació?
NEXE: Segons el fitxer auth.md, el sistema usa
dual-key authentication amb X-API-Key header...

Tu: On està el fitxer de configuració?
NEXE: El fitxer de configuració principal està
a personality/server.toml...
```

### 3. Assisted development

**Goal:** Use NEXE for coding help.

```bash
./nexe chat

Tu: Escriu una funció Python per llegir un fitxer JSON

NEXE: Aquí tens una funció per llegir un fitxer JSON:

\`\`\`python
import json

def llegir_json(fitxer):
    try:
        with open(fitxer, 'r', encoding='utf-8') as f:
            dades = json.load(f)
        return dades
    except FileNotFoundError:
        print(f"Error: El fitxer {fitxer} no existeix")
        return None
    except json.JSONDecodeError:
        print(f"Error: El fitxer {fitxer} no és JSON vàlid")
        return None
\`\`\`

Tu: Com gestiono errors millor?
NEXE: [Explica gestió d'errors en Python...]
```

### 4. Semantic search in notes

**Goal:** Search for information in your notes.

```bash
# 1. Index notes
./nexe knowledge ingest ~/notes/

# 2. Search without remembering exact words
./nexe memory recall "on vaig guardar la recepta de pa"

# Finds: "Notes de cuina - recepta pa casolà.md"
```

### 5. Engine experimentation

**Goal:** Try different backends.

```bash
# Try with MLX (Apple Silicon)
./nexe chat --engine mlx
Tu: Explica'm què és la relativitat

# Try with Ollama
./nexe chat --engine ollama
Tu: Explica'm què és la relativitat

# Note: El model específic es configura via .env (NEXE_DEFAULT_MODEL)
```

---

## Tips and best practices

### Performance

1. **Choose the right model:**
   - Small models (2-4GB): Fast, less accurate
   - Medium models (7-8B): Good balance
   - Large models (70B): Slow, highly accurate

2. **Use the right backend:**
   - Apple Silicon → MLX (fastest)
   - Intel Mac → llama.cpp with Metal
   - Linux/Win → llama.cpp or Ollama

3. **Adjust the temperature:**
   - 0.0-0.3: Precise, deterministic responses
   - 0.5-0.7: Balance between creativity and precision
   - 0.8-1.0: Creative, variable responses

### RAG Memory

1. **Store structured information:**
   ```bash
   # Better:
   ./nexe memory store "Projecte: NEXE | Versió: 0.8 | Estat: Actiu"

   # Worse:
   ./nexe memory store "nexe està en versió 0.8 i està actiu"
   ```

2. **Use metadata when indexing documents:**
   ```bash
   ./nexe docs add report.md --tags "important,2026" --category "informes"
   ```

3. **Re-index when updating documents:**
   ```bash
   # Re-index all knowledge
   ./nexe knowledge ingest ./docs/
   ```

4. **Clean old memory periodically:**
   ```bash
   ./nexe memory cleanup
   ```

### Limitations to keep in mind

1. **Limited context:**
   - Local models have small context windows (2K-8K tokens)
   - Do not expect them to remember very long conversations without RAG

2. **Quality vs. speed:**
   - Small models are fast but less accurate
   - Large models are slow but more capable
   - Choose based on the task

3. **RAM usage:**
   - Monitor RAM usage with large models
   - If it runs slowly, close other applications

4. **Languages:**
   - Multilingual models work well in English
   - Salamandra is better for specific Catalan use cases
   - English-only models may mix languages

### Security

1. **Do not expose the port publicly:**
   - By default, NEXE listens only on localhost (127.0.0.1:9119)
   - Authentication is **mandatory** with X-API-Key (NEXE_PRIMARY_API_KEY in .env)

2. **Review what you index:**
   - Do not index files containing secrets (.env, keys, etc.)
   - Memory is stored unencrypted

3. **Logs:**
   - Logs may contain sensitive information
   - Review them before sharing

---

## Next steps

Now that you know how to use NEXE:

1. **ARCHITECTURE.md** - Understand how it works internally
2. **RAG.md** - Dive deeper into the memory system
3. **API.md** - Complete API reference
4. **PLUGINS.md** - Learn about the plugin system
5. **LIMITATIONS.md** - Know the current limitations

**Experiment!** NEXE is a learning project. Try things, break things, learn.

---

**Note:** This documentation is also indexed in NEXE's RAG. You can ask it about itself!

```bash
./nexe chat --rag

Tu: Com puc cercar a la memòria?
NEXE: Pots usar la comanda `./nexe memory search "query"`...
```
