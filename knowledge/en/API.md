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
- `engine`: "auto" (default), "ollama", "mlx", "llama_cpp", or "api" (an external provider: explicit opt-in, see below)
- `stream`: true returns SSE stream with markers
- `temperature`: 0.0-2.0 (default 0.7)
- `top_p`: 0 < top_p ≤ 1 (null by default) — nucleus sampling; null lets each engine use its own default (≈ 0.9)
- `max_tokens`: null = use model default, max 32000
- `reasoning_effort` (or `reasoning: {"effort": ...}`): `"none"` or absent = the model does not reason (default); any other value = it reasons, and the reasoning comes back apart from the answer, as `reasoning` (`message.reasoning`, or `delta.reasoning` when streaming). Levels are not graded yet: any value other than `"none"` means on.

**Streaming markers** (injected in SSE stream, parsed by UI):
- `[MODEL:name]` — active model
- `[MODEL_LOADING]` / `[MODEL_READY]` — model load state with timing
- `[RAG_AVG:0.75]` — average RAG relevance score
- `[RAG_ITEM:nexe_documentation|0.82]` — per-source detail (collection first, then score; only 2 fields)
- `[MEM:2]` — number of facts auto-saved via MEM_SAVE
- `[COMPACT:N]` — context compaction indicator
- `<think>…</think>` — the model's reasoning, in the web UI stream only (shown in the collapsible thinking block); `/v1` sends it as `reasoning` instead
- `[DOC_TRUNCATED:XX%]` — percentage of document discarded due to context limit (new 2026-04-02)

**End of stream — why the answer stopped** (new 2026-08-31):

The last chunk before `[DONE]` carries `finish_reason`, like the non-streaming path: `"stop"` when
the answer ended on its own, `"length"` when it was cut. If the engine does not report one it
degrades to `"stop"` — an absent reason is not a truncation.

A cut answer can be cut in two ways that demand opposite reactions, and the chunk tells them apart
with `x_nexe_truncation` (at the root of the chunk; our own extension, not OpenAI):

- `"ceiling"` — the model hit the token ceiling: **the tail is missing**. Asking for the
  continuation and appending it is correct.
- `"overflow"` — tokens were dropped **from the middle** while generation carried on (the SSE queue
  filled up), and the ending that arrived is the natural one. **Do not ask for the continuation**:
  it would append new text over an internal hole, and the result would read as coherent without
  being so. Such an answer cannot be repaired by continuing it.

The field is **absent** when nothing was cut. If both happen at once, `"overflow"` wins.

**`[ATTACHED IMAGE]` block:** When a message includes an image (VLM backend), the chat endpoint injects an `[ATTACHED IMAGE]` block that **prioritises the image over the RAG context**. The model processes the image directly and RAG is relegated to secondary context, preventing retrieved documents from distracting from the visual description.

### Turn trace (what a recent turn did)

Every chat answer carries its turn id in the **`X-Nexe-Turn-Id`** header (streamed or JSON; JSON bodies keep `turn_id` too).
`GET /v1/turns/{turn_id}/trace` (API key required) returns that turn's steps: each step's outcome, duration, engine, error code
and cancel reason, the LLM calls it made (`outcome`: `ok` or `cancelled`), and `final` once nothing is pending (the
post-commit jobs, `compact` and `describe_image`, join the same record when they end). A turn in progress is already there,
with the steps it has done. It is kept in memory for the **last 256 turns** of the running server; `404` for an unknown or
older id. It never contains what you wrote or what the model answered. The durable record is the log: one `turn.trace` line
when the wire closes and a short `turn.step` line per post-commit job.

Each LLM call in the trace carries `tokens_in`, `tokens_out` and `cached_in` (the tokens the **engine** says it spent, and the prefix-cache tokens it reused). What an engine does not say is `null`, **never `0`**: MLX reports input, output and cache; llama.cpp, Ollama and the APIs (DeepSeek, OpenAI) report input and output. The web message footer shows that count as it is; when the engine gives none, it shows an estimate with a `~` in front. `/metrics` totals it in `core_turn_tokens_total{engine,kind}` (`kind`: `in`, `out`, `cached`).

`/metrics` counts the engines the same at both doors: `core_chat_engine_requests_total{engine,status}` and
`core_chat_engine_duration_seconds{engine}` (time up to the engine's first event, one row per engine asked, the re-prompt
included), plus `core_turn_steps_total{step,outcome}` and `core_turn_step_duration_seconds{step}`.

### External API providers (opt-in)

`"engine": "api"` sends the request to an external OpenAI-compatible provider (DeepSeek or OpenAI) instead of a local engine. It is an **explicit opt-in** and never a fallback: the API answers only when you ask for it by name. A local engine that fails is not answered by the API, and a provider that fails is not answered by a local engine. `"engine": "auto"`, or a `NEXE_MODEL_ENGINE=api` left in the environment, never reaches the cloud.

What leaves the machine: the conversation, the retrieved documents and the memory of that request, plus the internal steps that run on the same engine (conversation compaction, image description, the memory re-prompt). Nothing else, and never the key.

A request for `"engine": "api"` is refused unless **all** of this holds:

1. `api_module` is in `NEXE_APPROVED_MODULES` (otherwise `503`: the API engine is not loaded; the checks below are made first).
2. The global switch is on: `NEXE_ALLOW_CLOUD_ENGINES=1` (off by default; it is the web UI's "Allow cloud engines" switch, and it is read again at every request). Off: `403` `cloud_engines_disabled`.
3. `model` is a model of a provider whose key is configured on the server: `deepseek-chat` or `deepseek-reasoner` (`DEEPSEEK_API_KEY`), or `gpt-*` (`OPENAI_API_KEY`). The key lives in the server's `.env` only: the client never sends it, and nothing ever shows it. No model, or a local one: `400` `cloud_model_not_allowed`. No key: `400` `cloud_provider_not_configured`.
4. The request carries its own consent: `"nexe_cloud_consent": "<provider key>"` (`"deepseek"` or `"openai"`). `/v1` has no session to remember a consent, so it is asked on **every** request, for one provider. Missing, or another provider's: `403` `cloud_consent_required`.

```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"engine": "api", "model": "deepseek-chat", "nexe_cloud_consent": "deepseek",
       "messages": [{"role": "user", "content": "Hello"}]}'
```

With the OpenAI SDK: `extra_body={"engine": "api", "nexe_cloud_consent": "deepseek"}`. The body of a refusal is `{"code", "message", "provider"}`, never a key. A request the gate refuses (the `400`s and `403`s above) stores nothing and sends nothing.

- The answer carries `X-Nexe-Engine: api` (`nexe_engine` in a JSON body), `model` is the one you named, and there is no fallback header.
- `temperature` and `max_tokens` are **not** forwarded (some provider models rename or refuse them): the provider's defaults apply. `top_p` and images (for a model that can read them: `gpt-4o`, `gpt-4.1`, `gpt-5`) are. `reasoning_effort` changes nothing in what is sent (whether a provider's model reasons is its own nature): it only decides whether the reasoning that comes back is returned, as `reasoning`. `resume` (Continue) is refused with `400`: a provider cannot resume mid-sentence.
- Errors: a refused key (401/403) is `502`; a balance (402), a rate limit (429), any 5xx or a request the provider rejects is `503`; a timeout is `504` (`NEXE_API_TIMEOUT`, seconds between two chunks, default 120). The text names the provider and the HTTP status, never the key or the provider's body.
- It has a concurrency gate of its own (`NEXE_CLOUD_ENGINE_SLOTS`, default 4), so a cloud answer never holds the local engines' slot. A deadline, or a client that leaves, stops the HTTP read.
- The turn's trace line, and a web message saved from a provider, carry `left_machine: true`.

Admin: `GET /admin/providers/status` (which keys are configured, never the key) and `POST /admin/providers/{provider}/check` (one minimal request). CLI: `nexe providers status` and `nexe providers check <provider>`.

### System Info

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | System info (version, status, port) |
| `/health` | GET | No | Basic health check |
| `/health/ready` | GET | No | Readiness check. Only **critical** subsystems (authentication and the interface) make it answer `unhealthy`; when what is failing or missing is degradable (RAG, embeddings, an engine) it answers `degraded` and the interface loads anyway, so the user can get in and fix it. A degradable module reporting itself unhealthy is **shown, not used as a door**: the interface says so in the status indicator and next to where you type |
| `/health/circuits` | GET | Yes (X-API-Key) | Circuit breaker states (Ollama, Qdrant) |
| `/status` | GET | Yes (X-API-Key) | Real-time status: `configured_engine` (intent), `resolved_engine` (the engine chat will effectively run, node-aware), `model` (the configured default — MLX/llama.cpp report their actually-loaded model only in the chat response), loaded modules, `operational_state` (`normal`/`degraded`/`limited`/`refused`) and `impaired_subsystems` (what is not working). The interface polls this to warn the user when a subsystem failed to start, instead of letting them chat believing memory works |
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
| `/v1/memory/health` | GET | Yes | default | Memory subsystem health + Qdrant collections |

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

## Retired RAG endpoints (/v1/rag, /v1/documents)

`/v1/rag/search`, `/v1/rag/add`, `DELETE /v1/rag/documents/{id}` and `GET /v1/documents/` were stubs that returned 501; they were removed and now answer **404**. Retrieval happens inside the chat (`use_rag` in `/v1/chat/completions`); a direct semantic search in a collection is `POST /v1/memory/search`.

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

**Upload:** Accepts PDF, .docx, .xlsx, .pptx, .epub, text, source code and data (.csv, .json, .xml, .yaml, .toml) — see RAG.md. Dynamic chunking based on document size (800/1000/1200/1500 chars). Magic bytes validation (SEC-004). Metadata generated without LLM (instant). Documents isolated to uploading session via session_id.

## Encryption CLI Commands

These are CLI commands (not HTTP endpoints):

| Command | Description |
|---------|-------------|
| `./nexe encryption status` | Show encryption status of all storage components |
| `./nexe encryption encrypt-all` | Migrate all existing data to encrypted format |
| `./nexe encryption export-key` | Export master key (hex or base64, for backup) |

## OpenAI Compatibility

`/v1/chat/completions` is partially compatible with the OpenAI API format:

**Supported:** messages array, model, temperature, max_tokens, stream, top_p, reasoning_effort (the reasoning comes back as `reasoning`)
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
