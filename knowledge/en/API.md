# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete REST API reference for server-nexe 0.8.5 pre-release. Covers all endpoints: chat completions (OpenAI-compatible, streaming, RAG), memory (store, search), RAG search, document upload, sessions, bootstrap, health checks, modules, backends, i18n, encryption CLI. Includes authentication (X-API-Key dual-key), rate limiting per endpoint, streaming markers, and configuration."
tags: [api, rest, endpoints, chat, memory, rag, authentication, rate-limiting, streaming, openai-compatible, upload, sessions, bootstrap, health, backends, encryption]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# REST API Reference — server-nexe 0.8.5 pre-release

## Base URL

```
http://127.0.0.1:9119
```

Configurable via `personality/server.toml` `[core.server]` section or `.env` (HOST/PORT). Priority: server.toml > .env > defaults.

API docs (Swagger): `http://127.0.0.1:9119/docs`

## Authentication

Most endpoints require `X-API-Key` header. Value from `.env` file (`NEXE_PRIMARY_API_KEY`).

**Dual-key system:** Two keys can be active simultaneously for rotation:
- `NEXE_PRIMARY_API_KEY` — always active
- `NEXE_SECONDARY_API_KEY` — grace period for rotation
- Expiry tracking via `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`

**Bootstrap token:** For initial setup, a one-time token is generated at startup (256-bit, 30min TTL). Shown in console output.

## Rate Limiting

Rate limiting is applied to **all endpoints** — both API and Web UI.

### API endpoints (configurable via `.env`)

| Variable | Default | Applies to |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/minute | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/minute | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/minute | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/minute | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/minute | All other endpoints |

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

## Core Endpoints

### Chat

**POST /v1/chat/completions** (requires API key, rate limit: 60/min)

OpenAI-compatible chat completion with RAG and streaming support.

```json
{
  "messages": [{"role": "user", "content": "Hello"}],
  "model": "auto",
  "engine": "auto",
  "use_rag": true,
  "stream": false,
  "temperature": 0.7,
  "max_tokens": null
}
```

- `use_rag`: true by default — searches 3 Qdrant collections
- `engine`: "auto" (default), "ollama", "mlx", "llama_cpp"
- `stream`: true returns SSE stream with markers
- `temperature`: 0.0-2.0 (default 0.7)
- `max_tokens`: null = use model default, max 32000

**Streaming markers** (injected in SSE stream, parsed by UI):
- `[MODEL:name]` — active model
- `[MODEL_LOADING]` / `[MODEL_READY]` — model load state with timing
- `[RAG_AVG:0.75]` — average RAG relevance score
- `[RAG_ITEM:0.82|nexe_documentation|ARCHITECTURE.md]` — per-source detail
- `[MEM:2]` — number of facts auto-saved via MEM_SAVE
- `[COMPACT:N]` — context compaction indicator
- `[THINKING]` / `[/THINKING]` — thinking tokens (Ollama models like qwen3.5)

### System Info

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | System info (version, status, port) |
| `/health` | GET | No | Basic health check |
| `/health/ready` | GET | No | Readiness check (verifies required modules) |
| `/health/circuits` | GET | No | Circuit breaker states (Ollama, Qdrant) |
| `/status` | GET | No | Real-time status: active engine, model, loaded modules |
| `/api/info` | GET | No | API info and list of available endpoints |
| `/docs` | GET | No | Swagger/OpenAPI interactive documentation |

### Modules

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/modules` | GET | No | List loaded modules and their APIs |
| `/modules/{name}/routes` | GET | No | Routes registered by a specific module |

### Bootstrap

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/bootstrap` | POST | Token | Initialize session with bootstrap token |
| `/api/regenerate-bootstrap` | POST | localhost | Regenerate expired bootstrap token |
| `/api/bootstrap/info` | GET | No | Bootstrap system status |

## Memory Endpoints (prefix: /v1/memory)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/memory/store` | POST | Yes | Store text to a collection |
| `/v1/memory/search` | POST | Yes | Semantic search in a collection |
| `/v1/memory/health` | GET | No | Memory subsystem health + Qdrant collections |

**Store request:**
```json
{
  "text": "Information to store",
  "collection": "user_knowledge",
  "metadata": {"source": "api", "tags": ["example"]}
}
```

**Search request:**
```json
{
  "query": "search query",
  "collection": "user_knowledge",
  "limit": 5,
  "threshold": 0.35
}
```

## RAG Endpoints (prefix: /v1/rag)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/rag/search` | POST | Yes | Semantic search in RAG vector store |
| `/v1/rag/add` | POST | Yes | Add documents to RAG vector store |
| `/v1/rag/documents/{id}` | DELETE | Yes | Delete document from RAG |

## Embeddings Endpoints (prefix: /v1/embeddings)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Yes | Generate embedding vectors for texts |
| `/v1/embeddings/models` | GET | No | List available embedding models |

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
| `/ui/sessions` | GET | Yes | default | List all sessions |

### Files

| Endpoint | Method | Auth | Rate limit | Description |
|----------|--------|------|-----------|-------------|
| `/ui/upload` | POST | Yes | 5/min | Upload document (validates filename, session-isolated) |
| `/ui/files` | GET | Yes | default | List uploaded files |
| `/ui/files/cleanup` | POST | Yes | 5/min | Clean up temporary files |

**Upload:** Accepts .txt, .md, .pdf. Chunks at 1500/200 chars. Metadata generated without LLM (instant). Documents isolated to uploading session via session_id.

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
**Not implemented:** /v1/embeddings (use /v1/embeddings/encode instead), /v1/models, /v1/completions (legacy)

Compatible with tools that use OpenAI API format: Cursor, Continue, Zed, custom scripts.

## Configuration

| Setting | Location | Purpose |
|---------|----------|---------|
| Host/Port | server.toml `[core.server]` | Server bind address |
| API keys | .env | NEXE_PRIMARY_API_KEY, NEXE_SECONDARY_API_KEY |
| Rate limits | .env | NEXE_RATE_LIMIT_* variables |
| Timeout | .env | NEXE_DEFAULT_MAX_TOKENS (default 4096) |
| CORS origins | server.toml `[core.server]` | Allowed origins |
| Encryption | .env | NEXE_ENCRYPTION_ENABLED (default false) |

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
  -d '{"text": "My name is Jordi", "collection": "user_knowledge"}'

# Search memory
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "what is my name", "collection": "user_knowledge", "limit": 3}'
```
