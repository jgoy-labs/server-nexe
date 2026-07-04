# === METADATA RAG ===
versio: "2.0"
data: 2026-07-04
id: nexe-api-reference
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "server-nexe REST API: endpoints /v1/chat/completions (OpenAI-compatible), /memory/store, /memory/search, /rag/search, /upload, /sessions. X-API-Key dual-key authentication. Per-endpoint rate limiting. SSE streaming. Default port 9119. curl and Python examples."
tags: [api, rest, endpoints, chat, memory, rag, authentication, rate-limiting, streaming, openai-compatible, upload, sessions, bootstrap, health, backends, encryption, curl, python]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: api
author: "Jordi Goy with AI collaboration"
expires: null
---

# REST API Reference — server-nexe 1.0.7

## Base URL

```
http://127.0.0.1:9119
```

Configurable via `personality/server.toml` `[core.server]` section or `.env` (NEXE_HOST/NEXE_PORT). Priority: server.toml > .env > defaults.

API docs (Swagger): `http://127.0.0.1:9119/docs`

## Authentication

Most endpoints require `X-API-Key` header. Value from `.env` file (`NEXE_PRIMARY_API_KEY`).

**Dual-key system:** Two keys can be active simultaneously for rotation:
- `NEXE_PRIMARY_API_KEY` — always active
- `NEXE_SECONDARY_API_KEY` — grace period for rotation
- Expiry tracking via `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`

**Bootstrap token:** For initial setup, a one-time token is generated at startup (128-bit, 30min TTL). Shown in console output.

## Rate Limiting

Rate limiting is applied to **all endpoints** — both API and Web UI.

### Variables configurable via `.env`

| Variable | Default | Applies to |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_GLOBAL | 100/minute | Per-IP global limit — **the only one actually enforced** (`core/dependencies.py` + SlowAPI middleware) |
| NEXE_RATE_LIMIT_PUBLIC | (read but unused) | **Dead config** — read into `DEFAULT_RATE_LIMITS` but no limiter consumes it (advanced limiters removed, MC-123/124); no runtime effect |
| NEXE_RATE_LIMIT_AUTHENTICATED | (read but unused) | **Dead config** — no runtime effect |
| NEXE_RATE_LIMIT_ADMIN | (read but unused) | **Dead config** — no runtime effect |
| NEXE_RATE_LIMIT_HEALTH | (read but unused) | **Dead config** — no runtime effect |

**Note:** Per-endpoint limits (chat 20/min, memory 30/60 per min, upload 5/min...) are **hardcoded in the source** via `@limiter.limit` (e.g. `core/endpoints/chat.py`, `routes_files.py`) and are **not** configurable via `.env`.

### Web UI endpoints (per endpoint)

| Endpoint | Rate limit |
|----------|-----------|
| POST /ui/chat | 20/minute |
| POST /ui/memory/save | 10/minute |
| POST /ui/memory/recall | 30/minute |
| POST /ui/upload | 5/minute |
| POST /ui/files/cleanup | 5/minute |
| GET /ui/session/{id} | 30/minute |
| DELETE /ui/session/{id} | 10/minute |
| PATCH /ui/session/{id} | 10/minute |
| PATCH /ui/session/{id}/thinking | 10/minute |

## Core Endpoints

### Chat

**POST /v1/chat/completions** (requires API key, rate limit: 20/min)

OpenAI-compatible chat completion with RAG and streaming support.

```json
{
  "messages": [{"role": "user", "content": "Hello"}],
  "model": null,
  "engine": "auto",
  "use_rag": true,
  "stream": false,
  "temperature": 0.7,
  "max_tokens": null
}
```

- `model`: null by default (not "auto"). For **Ollama** a passed value selects the model with a partial-name fallback (e.g. `llama3` → `llama3.1:8b`); 404 only if no chat model matches. For **MLX / llama.cpp** the value is **ignored** — they run the single configured model — and the response reports the actual loaded model's name, never the requested one
- `use_rag`: true by default — searches 3 Qdrant collections
- `engine`: "auto" (default), "ollama", "mlx", "llama_cpp"
- `stream`: true returns SSE stream with markers
- `temperature`: 0.0-2.0 (default 0.7)
- `top_p`: 0 < top_p ≤ 1 (null by default) — nucleus sampling; null lets each engine use its own default (≈ 0.9)
- `max_tokens`: null = use model default, max 32000

**Streaming markers** (injected in SSE stream, parsed by UI):
- `[MODEL:name]` — active model
- `[MODEL_LOADING]` / `[MODEL_READY]` — model load state with timing
- `[RAG_AVG:0.75]` — average RAG relevance score
- `[RAG_ITEM:nexe_documentation|0.82]` — per-source detail (collection first, then score; only 2 fields)
- `[MEM:2]` — number of facts auto-saved via MEM_SAVE
- `[COMPACT:N]` — context compaction indicator
- `[THINKING]` / `[/THINKING]` — thinking tokens (Ollama models like qwen3.5)
- `[DOC_TRUNCATED:XX%]` — percentage of document discarded due to context limit (new 2026-04-02)

**`[ATTACHED IMAGE]` block:** When a message includes an image (VLM backend), the chat endpoint injects an `[ATTACHED IMAGE]` block that **prioritises the image over the RAG context**. The model processes the image directly and RAG is relegated to secondary context, preventing retrieved documents from distracting from the visual description.

### System Info

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | System info (version, status, port) |
| `/health` | GET | No | Basic health check |
| `/health/ready` | GET | No | Readiness check (verifies required modules) |
| `/health/circuits` | GET | Yes (X-API-Key) | Circuit breaker states (Ollama, Qdrant) |
| `/status` | GET | Yes (X-API-Key) | Real-time status: `configured_engine` (intent), `resolved_engine` (the engine chat will effectively run, node-aware), `model` (the configured default — MLX/llama.cpp report their actually-loaded model only in the chat response), loaded modules |
| `/api/info` | GET | No | API info and a representative subset of public endpoints (not exhaustive) |
| `/docs` | GET | No | Swagger/OpenAPI interactive documentation |
| `/admin/system/restart` | POST | Yes (X-API-Key) | Restart the server (used by the UI after config changes) |
| `/admin/system/shutdown` | POST | Yes (X-API-Key) | Shut down the server |
| `/admin/system/status` | GET | Yes (X-API-Key) | Admin system status |
| `/admin/system/health` | GET | No | Public health check the UI polls after a restart |

### Modules

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/modules` | GET | Yes (X-API-Key) | List loaded modules and their APIs |
| `/modules/{name}/routes` | GET | Yes (X-API-Key) | Routes registered by a specific module |

### Bootstrap

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/bootstrap` | POST | Token | Initialize session with bootstrap token |
| `/api/regenerate-bootstrap` | POST | localhost | Regenerate expired bootstrap token |
| `/api/bootstrap/info` | GET | No | Bootstrap system status |

## Memory Endpoints (prefix: /v1/memory)

| Endpoint | Method | Auth | Rate limit | Description |
|----------|--------|------|------------|-------------|
| `/v1/memory/store` | POST | Yes | **30/min** (hardcoded, `memory/memory/api/v1.py`) | Store text to a collection |
| `/v1/memory/search` | POST | Yes | **60/min** (hardcoded, `memory/memory/api/v1.py`) | Semantic search in a collection |
| `/v1/memory/health` | GET | No | default | Memory subsystem health + Qdrant collections |

**Store request:**
```json
{
  "content": "Information to store",
  "collection": "user_knowledge",
  "metadata": {"source": "api", "tags": ["example"]}
}
```

**Search request:**
```json
{
  "query": "search query",
  "collection": "user_knowledge",
  "limit": 5
}
```

## RAG Endpoints (prefix: /v1/rag)

> ⚠️ **NOT IMPLEMENTED (stub):** these endpoints return HTTP 501. Reserved for a future version.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/rag/search` | POST | Yes | Semantic search in RAG vector store (stub, 501) |
| `/v1/rag/add` | POST | Yes | Add documents to RAG vector store (stub, 501) |
| `/v1/rag/documents/{id}` | DELETE | Yes | Delete document from RAG (stub, 501) |

## Embeddings Endpoints (prefix: /v1/embeddings)

> ⚠️ **NOT IMPLEMENTED (stub):** these endpoints return HTTP 501. Reserved for a future version.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Yes | Generate embedding vectors for texts (stub, 501) |
| `/v1/embeddings/models` | GET | Yes | List available embedding models (stub, 501) |

## Web UI Endpoints (prefix: /ui)

These endpoints serve the web interface and are used by the JavaScript frontend. All have input validation via `validate_string_input()`.

### Auth & Config

| Endpoint | Method | Auth | Rate limit | Description |
|----------|--------|------|-----------|-------------|
| `/ui/auth` | GET | Yes | default | Verify API key validity |
| `/ui/info` | GET | Yes | default | Server info (version, language, features) |
| `/ui/lang` | POST | Yes | default | Set server language (ca/es/en) |
| `/ui/backends` | GET | Yes | default | List backends with model names and sizes (GB) |
| `/ui/backend` | POST | Yes | default | Switch active backend |
| `/ui/health` | GET | No | default | Web UI module health |

### Chat & Memory

| Endpoint | Method | Auth | Rate limit | Description |
|----------|--------|------|-----------|-------------|
| `/ui/chat` | POST | Yes | 20/min | SSE streaming chat (MEM_SAVE, RAG, thinking tokens) |
| `/ui/memory/save` | POST | Yes | 10/min | Save text to memory (validates content, session_id) |
| `/ui/memory/recall` | POST | Yes | 30/min | Recall from memory (validates query, session_id) |

### Sessions

| Endpoint | Method | Auth | Rate limit | Description |
|----------|--------|------|-----------|-------------|
| `/ui/session/new` | POST | Yes | default | Create new session |
| `/ui/session/{id}` | GET | Yes | 30/min | Get session data (validates session_id) |
| `/ui/session/{id}/history` | GET | Yes | 30/min | Get session chat history |
| `/ui/session/{id}` | DELETE | Yes | 10/min | Delete session |
| `/ui/session/{id}` | PATCH | Yes | 10/min | Rename session (new 2026-04-01) |
| `/ui/session/{id}/thinking` | PATCH | Yes | 10/min | Toggle thinking mode (reasoning tokens) per session (new v0.9.9) |
| `/ui/session/{id}/clear-document` | POST | Yes | default | Clear attached document from session (new 2026-04-02) |
| `/ui/sessions` | GET | Yes | default | List all sessions |

**Thinking toggle** (`PATCH /ui/session/{id}/thinking`): enables or disables emission of reasoning tokens for a specific session. Only available for compatible model families (`THINKING_CAPABLE`: qwen3.5, qwen3, qwq, deepseek-r1, gemma3/4, llama4, gpt-oss). Disabled by default. If the model does not support thinking, the endpoint returns 400 with an explanatory message and the UI offers automatic retry without thinking.

### Files

| Endpoint | Method | Auth | Rate limit | Description |
|----------|--------|------|-----------|-------------|
| `/ui/upload` | POST | Yes | 5/min | Upload document (validates filename, session-isolated) |
| `/ui/files` | GET | Yes | default | List uploaded files |
| `/ui/files/cleanup` | POST | Yes | 5/min | Clean up temporary files |

**Upload:** Accepts .txt, .md, .pdf. Dynamic chunking based on document size (800/1000/1200/1500 chars). Magic bytes validation (SEC-004). Metadata generated without LLM (instant). Documents isolated to uploading session via session_id.

## Encryption CLI Commands

These are CLI commands (not HTTP endpoints):

| Command | Description |
|---------|-------------|
| `./nexe encryption status` | Show encryption status of all storage components |
| `./nexe encryption encrypt-all` | Migrate all existing data to encrypted format |
| `./nexe encryption export-key` | Export master key (hex or base64, for backup) |

## OpenAI Compatibility

`/v1/chat/completions` is partially compatible with the OpenAI API format:

**Supported:** messages array, model, temperature, max_tokens, stream, top_p
**Extra fields:** use_rag (boolean), engine (string)
**Not implemented:** /v1/embeddings/encode and /v1/embeddings/models (stubs, return 501), /v1/models, /v1/completions (legacy)

Compatible with tools that use OpenAI API format: Cursor, Continue, Zed, custom scripts.

## Configuration

| Setting | Location | Purpose |
|---------|----------|---------|
| Host/Port | server.toml `[core.server]` | Server bind address |
| API keys | .env | NEXE_PRIMARY_API_KEY, NEXE_SECONDARY_API_KEY |
| Rate limits | .env | NEXE_RATE_LIMIT_GLOBAL (and security plugin variables); per-endpoint limits in source code |
| Timeout | .env | NEXE_OLLAMA_STREAM_TIMEOUT (default 300, seconds) |
| CORS origins | server.toml `[core.server]` | Allowed origins |
| Encryption | .env | NEXE_ENCRYPTION_ENABLED (default auto) |

## Quick Examples

```bash
# Health check
curl http://127.0.0.1:9119/health

# Chat (non-streaming)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

# Store to memory
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content": "My name is Jordi", "collection": "user_knowledge"}'

# Search memory
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "what is my name", "collection": "user_knowledge", "limit": 3}'
```
