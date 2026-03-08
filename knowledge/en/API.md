# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete reference for the NEXE 0.8 REST API. Covers X-API-Key authentication, chat, memory, RAG, admin and Prometheus metrics endpoints. Includes examples in Python, JavaScript and cURL with partial OpenAI compatibility."
tags: [api, rest, endpoints, chat, memory, rag, autenticació, rate-limiting]
chunk_size: 1200
priority: P1

# === OPCIONAL ===
lang: en
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# API Reference - NEXE 0.8

NEXE provides a **REST API** for integrating it with other applications. This documentation describes the available endpoints and their actual behaviour according to the current code.

## Table of Contents

1. [Introduction](#introduction)
2. [Base URL and server configuration](#base-url-and-server-configuration)
3. [Authentication](#authentication)
4. [Request/response format](#requestresponse-format)
5. [Endpoints](#endpoints)
6. [Rate limiting](#rate-limiting)
7. [Client examples](#client-examples)
8. [OpenAI compatibility](#openai-compatibility)
9. [Interactive documentation](#interactive-documentation)

---

## Introduction

The NEXE API follows REST principles and returns JSON. It provides versioned routes under `/v1` and system endpoints for monitoring and administration.

### Features

- **REST:** Endpoints with standard HTTP verbs
- **JSON:** Input and output typically in JSON
- **OpenAPI:** Automatic documentation at `/docs`
- **OpenAI compatibility (partial):** `/v1/chat/completions` with OpenAI-like format on some engines
- **Async:** Supports asynchronous operations

---

## Base URL and server configuration

### Default

```
http://127.0.0.1:9119
```

### Configuration

The host/port are preferably configured in `server.toml` (looked up in `server.toml`, `personality/server.toml` or `config/server.toml`). Example:

```toml
[core.server]
host = "127.0.0.1"
port = 9119
```

**Alternative (less recommended):** Environment variables via `.env` can also be used:

```bash
PORT=9119
HOST=127.0.0.1
```

**Priority:** server.toml > .env > defaults

### Remote access

**⚠️ Important:** By default, NEXE only listens on `127.0.0.1` for security reasons.

To access remotely:

1. Set `host = "0.0.0.0"` in `server.toml`.
2. **Enable authentication** (see next section).
3. Use HTTPS if exposing publicly (reverse proxy with nginx/caddy).

---

## Authentication

NEXE uses **API keys** via the `X-API-Key` header.

### Supported environment variables

- `NEXE_PRIMARY_API_KEY` (primary)
- `NEXE_PRIMARY_KEY_EXPIRES` (optional, ISO datetime)
- `NEXE_SECONDARY_API_KEY` (optional, old key in grace period)
- `NEXE_SECONDARY_KEY_EXPIRES` (optional)
- `NEXE_ADMIN_API_KEY` (legacy, fallback if no primary is set)

### Usage example

```bash
curl -H "X-API-Key: el-teu-token" \
  http://127.0.0.1:9119/health
```

### Development mode (bypass)

- `NEXE_DEV_MODE=true` allows bypass **only** if `NEXE_ENV != production`.
- For remote access in DEV mode, `NEXE_DEV_MODE_ALLOW_REMOTE=true` is required.
- If there is **no** valid key and DEV mode is not enabled, the API returns **500** (misconfiguration).

---

## Request/response format

- **JSON** by default (`Content-Type: application/json`).
- Some endpoints accept **multipart/form-data** (e.g. `/rag/upload`).
- Errors can be `"detail": "..."` or `"detail": { ... }` depending on the endpoint.

Typical error example:

```json
{
  "detail": "Invalid or expired API key"
}
```

---

## Endpoints

### System (core)

#### GET /
Basic system information.

**Response (example):**
```json
{
  "system": "Nexe 0.8",
  "description": "Sistema d'orquestració de mòduls en funcionament",
  "status": "Sistema preparat i operatiu",
  "version": "0.8.0",
  "type": "servidor_bàsic"
}
```

---

#### GET /health
Server health check.

**Response (example):**
```json
{
  "status": "operatiu",
  "message": "Servidor bàsic operatiu",
  "version": "0.8.0",
  "uptime": "operacional"
}
```

---

#### GET /health/ready
Readiness check. Validates required modules and health status.

**Response (example):**
```json
{
  "status": "healthy",
  "required_modules": ["ollama_module"],
  "missing_modules": [],
  "unhealthy_modules": [],
  "degraded_modules": [],
  "module_status": {"ollama_module": "healthy"},
  "timestamp": "2026-02-04T12:00:00"
}
```

---

#### GET /health/circuits
State of the circuit breakers (ollama, qdrant, http_external).

**Response (example):**
```json
{
  "circuits": [
    {
      "name": "ollama",
      "state": "closed",
      "failure_count": 0,
      "last_failure_time": null
    },
    {
      "name": "qdrant",
      "state": "closed",
      "failure_count": 0,
      "last_failure_time": null
    }
  ],
  "timestamp": "2026-02-04T12:00:00"
}
```

---

#### GET /status
Runtime state (current engine, configured model, loaded modules).

**Response (example):**
```json
{
  "engine": "ollama",
  "configured_engine": "auto",
  "model": "llama3.2",
  "modules_loaded": ["ollama_module", "mlx_module", "security"],
  "engines_available": {
    "mlx": true,
    "llama_cpp": false,
    "ollama": true
  },
  "timestamp": "2026-02-04T12:00:00"
}
```

---

#### GET /api/info
Basic API information and list of main endpoints.

**Response (example):**
```json
{
  "name": "Nexe 0.8",
  "version": "0.8.0",
  "description": "Sistema d'orquestració de mòduls en funcionament",
  "endpoints": [
    {"path": "/", "method": "GET", "description": "Endpoint arrel del sistema"},
    {"path": "/health", "method": "GET", "description": "Verificació de salut del sistema"},
    {"path": "/api/info", "method": "GET", "description": "Informació bàsica del sistema"}
  ]
}
```

---

#### GET /api/bootstrap/info
Information about the bootstrap state (frontend onboarding).

---

#### GET /modules
Lists module integration statistics.

#### GET /modules/{module_name}/routes
Routes exposed by a specific module.

---

### API v1 (metadata)

#### GET /v1
General information about the versioned API.

#### GET /v1/health
Health check specific to the v1 API.

---

### Chat

#### POST /v1/chat/completions
Generate a chat response. **Partially** compatible with OpenAI.

**Request:**
```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: el-teu-token" \
  -d '{
    "model": "phi3",
    "engine": "auto",
    "messages": [
      {"role": "system", "content": "Ets un assistent útil."},
      {"role": "user", "content": "Explica què és Python en 2 línies"}
    ],
    "temperature": 0.7,
    "max_tokens": 150,
    "stream": false,
    "use_rag": true
  }'
```

**Supported parameters:**

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `messages` | array | Yes | Array of messages | - |
| `model` | string | No | Model name (depends on engine) | Depends on engine |
| `engine` | string | No | `auto`, `ollama`, `mlx`, `llama_cpp` | `auto` |
| `temperature` | float | No | Creativity (0.0-2.0) | 0.7 |
| `max_tokens` | int | No | Maximum tokens (1-32000) | `null` (engine decides) |
| `stream` | bool | No | Streaming SSE | false |
| `use_rag` | bool | No | Enable RAG/memory | true |

**Important notes:**
- `top_p`, `frequency_penalty`, `presence_penalty` are **not** implemented.
- In **Ollama** mode, the **non-streaming** response uses the native Ollama format.
- In **MLX/Llama.cpp** mode, the response is OpenAI-like.

**OpenAI-like response (MLX/Llama.cpp, example):**
```json
{
  "id": "mlx-abc123",
  "object": "chat.completion",
  "created": 1706950400,
  "model": "mlx-local",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Python és un llenguatge de programació..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 42,
    "total_tokens": 67
  }
}
```

**Additional headers (non-streaming):**
- May include `nexe_engine` and `nexe_fallback` in the JSON.

**Additional headers (streaming):**
- `X-Nexe-Engine`: Engine used (ollama/mlx/llama_cpp)
- `X-Nexe-Fallback-From`: Requested engine if fallback occurred
- `X-Nexe-Fallback-Reason`: Reason for fallback (module_unavailable/execution_failed)

**Streaming (SSE):**
```
data: {"choices":[{"delta":{"content":"Hola"}}]}

data: [DONE]
```

---

### Memory (v1)

#### POST /v1/memory/store
Store information in semantic memory.

**Request:**
```bash
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "Content-Type: application/json" \
  -H "X-API-Key: el-teu-token" \
  -d '{
    "content": "El meu projecte favorit és NEXE",
    "metadata": {
      "category": "projectes",
      "tags": ["nexe", "desenvolupament"]
    },
    "collection": "nexe_chat_memory"
  }'
```

**Response (example):**
```json
{
  "success": true,
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Content stored successfully"
}
```

---

#### POST /v1/memory/search
Search information in memory.

**Request:**
```bash
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: el-teu-token" \
  -d '{
    "query": "projecte favorit",
    "limit": 5,
    "collection": "nexe_chat_memory"
  }'
```

**Response (example):**
```json
{
  "results": [
    {
      "content": "El meu projecte favorit és NEXE",
      "score": 0.94,
      "metadata": {
        "category": "projectes",
        "tags": ["nexe", "desenvolupament"]
      }
    }
  ],
  "total": 1
}
```

---

#### GET /v1/memory/health
Health check for the memory subsystem.

**Response (example):**
```json
{
  "status": "healthy",
  "collections": 3,
  "initialized": true
}
```

**If Qdrant is unavailable:**
```json
{
  "status": "unhealthy",
  "error": "Connection refused",
  "hint": "Ensure Qdrant is running"
}
```

---

### RAG (module)

⚠️ **IMPORTANT NOTE:** There are two sets of RAG endpoints:
- `/v1/rag/*` → Versioned endpoints **not implemented** (501), coming soon
- `/rag/*` → **Functional** endpoints of the RAG module (documented below)

These endpoints belong to the RAG module (`/rag`). They are used to add documents and perform direct searches.

#### POST /rag/document (auth required)
Add a text document.

**Request (JSON):**
```json
{
  "text": "Contingut del document",
  "metadata": {"source": "manual"},
  "chunk_size": 800,
  "chunk_overlap": 100,
  "source": "personality"
}
```

**Response (example):**
```json
{
  "status": "indexed",
  "document_id": "doc-abc123",
  "chunks_created": 5,
  "metadata": {
    "source": "manual",
    "indexed_at": "2026-02-04T12:34:56Z"
  }
}
```

---

#### POST /rag/search (auth required)
Search documents.

**Request (JSON):**
```json
{
  "query": "cerca",
  "top_k": 5,
  "filters": {},
  "source": "personality"
}
```

**Response (example):**
```json
{
  "results": [
    {
      "id": "doc-abc123",
      "text": "Text del document...",
      "score": 0.92,
      "metadata": {"source": "manual"}
    }
  ],
  "total": 1,
  "query_time_ms": 45
}
```

---

#### POST /rag/upload (auth required)
Upload a file and index it (multipart/form-data). **Maximum 50MB.**

**Request (example):**
```bash
curl -X POST http://127.0.0.1:9119/rag/upload \
  -H "X-API-Key: el-teu-token" \
  -F "file=@README.md" \
  -F 'metadata={"category":"docs"}'
```

**Response (example):**
```json
{
  "status": "success",
  "file_id": "f123abc",
  "filename": "README.md",
  "size_bytes": 45234,
  "chunks_created": 12,
  "message": "File uploaded and indexed successfully"
}
```

**Errors:**
- `413`: File too large (max 50MB)
- `400`: Unsupported file type
- `500`: Processing error

---

#### GET /rag/health
Health of the RAG module (public).

#### GET /rag/info
Info for the RAG module (public).

#### GET /rag/files/stats (auth required)
Statistics for uploaded files.

**Response (example):**
```json
{
  "total_files": 15,
  "total_chunks": 234,
  "total_size_mb": 12.5,
  "by_type": {
    "md": 10,
    "pdf": 3,
    "txt": 2
  }
}
```

#### GET /rag/ui
Web UI for the RAG module.

---

### Memory module (legacy)

#### GET /memory/health
Health check for the Memory module.

#### GET /memory/info
Info for the Memory module.

---

### Unimplemented endpoints (coming soon)

These endpoints exist but return **501 Not Implemented**:

**Versioned API (future):**
- `POST /v1/embeddings/encode` → coming soon
- `GET /v1/embeddings/models` → coming soon
- `GET /v1/documents/` → coming soon
- `POST /v1/rag/search` → coming soon
- `POST /v1/rag/add` → coming soon
- `DELETE /v1/rag/documents/{id}` → coming soon

**Note:** The `/rag/*` endpoints (without /v1) **ARE functional** (see RAG section).

---

### System administration

Admin endpoints under `/admin/system`:

#### POST /admin/system/restart (auth required)
Restarts the server via supervisor.

**Request:**
```bash
curl -X POST http://127.0.0.1:9119/admin/system/restart \
  -H "X-API-Key: el-teu-token"
```

**Response (example):**
```json
{
  "status": "restart_initiated",
  "message": "Servidor reiniciant en ~1 segon",
  "supervisor_pid": 12345,
  "expected_downtime_seconds": 5,
  "instructions": "La UI es reconnectarà automàticament"
}
```

---

#### GET /admin/system/status (auth required)
Supervisor status.

**Response (example):**
```json
{
  "supervisor_running": true,
  "supervisor_pid": 12345,
  "pid_file": "/tmp/core_supervisor.pid",
  "restart_available": true,
  "restart_command": "kill -HUP 12345",
  "shutdown_command": "kill -TERM 12345"
}
```

---

#### GET /admin/system/health (public)
Simple health check (no auth required).

**Response (example):**
```json
{
  "status": "healthy",
  "version": "0.8.0",
  "platform": "Nexe Framework",
  "uptime": "available"
}
```

---

### Metrics (Prometheus)

#### GET /metrics
Metrics in Prometheus format (text/plain).

**Response (example):**
```
# HELP nexe_chat_requests_total Total chat requests by engine
# TYPE nexe_chat_requests_total counter
nexe_chat_requests_total{engine="ollama",status="success"} 142.0

# HELP nexe_memory_operations_total Total memory operations
nexe_memory_operations_total{operation="store"} 23.0

# HELP nexe_chat_duration_seconds Chat request duration
# TYPE nexe_chat_duration_seconds histogram
nexe_chat_duration_seconds_bucket{engine="ollama",le="1.0"} 95.0
nexe_chat_duration_seconds_bucket{engine="ollama",le="5.0"} 140.0
```

---

#### GET /metrics/health
Health check for the metrics system.

**Response (example):**
```json
{
  "status": "healthy",
  "collectors_active": true,
  "metrics_count": 25
}
```

---

#### GET /metrics/json
Metrics in JSON format (more readable).

**Response (example):**
```json
{
  "chat": {
    "total_requests": 142,
    "by_engine": {
      "ollama": 100,
      "mlx": 42
    },
    "success_rate": 0.98
  },
  "memory": {
    "operations": 23,
    "storage_mb": 48.2
  },
  "uptime_seconds": 3600
}
```

---

## Rate limiting

Rate limiting based on `slowapi`, with configurable limits per environment:

- Global: `NEXE_RATE_LIMIT_GLOBAL` (default `100/minute`)
- Public: `NEXE_RATE_LIMIT_PUBLIC` (default `30/minute`)
- Authenticated: `NEXE_RATE_LIMIT_AUTHENTICATED` (default `300/minute`)
- Admin: `NEXE_RATE_LIMIT_ADMIN` (default `100/minute`)
- Health: `NEXE_RATE_LIMIT_HEALTH` (default `1000/minute`)

**Rate limit headers (if active):**

```
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
X-RateLimit-Used
```

**Configuration example (.env):**
```bash
NEXE_RATE_LIMIT_GLOBAL=200/minute
NEXE_RATE_LIMIT_PUBLIC=60/minute
NEXE_RATE_LIMIT_AUTHENTICATED=500/minute
```

**Response when limit is exceeded:**
```json
{
  "detail": "Rate limit exceeded. Try again in 30 seconds.",
  "retry_after": 30
}
```

**Status:** 429 Too Many Requests

Note: Some endpoints define specific limits using `@limiter.limit(...)` decorators.

---

## Client examples

### Python

```python
import requests

class NexeClient:
    def __init__(self, base_url="http://127.0.0.1:9119", api_key=None):
        self.base_url = base_url
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["X-API-Key"] = api_key

    def chat(self, messages, use_rag=True, engine="auto", **kwargs):
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers=self.headers,
            json={
                "messages": messages,
                "use_rag": use_rag,
                "engine": engine,
                **kwargs
            }
        )
        response.raise_for_status()
        return response.json()

    def store_memory(self, content, metadata=None, collection="nexe_chat_memory"):
        response = requests.post(
            f"{self.base_url}/v1/memory/store",
            headers=self.headers,
            json={"content": content, "metadata": metadata, "collection": collection}
        )
        response.raise_for_status()
        return response.json()

    def search_memory(self, query, limit=5, collection="nexe_chat_memory"):
        response = requests.post(
            f"{self.base_url}/v1/memory/search",
            headers=self.headers,
            json={"query": query, "limit": limit, "collection": collection}
        )
        response.raise_for_status()
        return response.json()["results"]

# Usage
client = NexeClient(api_key="el-teu-token")
resp = client.chat([{"role": "user", "content": "Hola!"}])
print(resp)
```

### JavaScript / Node.js

```javascript
class NexeClient {
  constructor(baseUrl = 'http://127.0.0.1:9119', apiKey = null) {
    this.baseUrl = baseUrl;
    this.headers = { 'Content-Type': 'application/json' };
    if (apiKey) this.headers['X-API-Key'] = apiKey;
  }

  async chat(messages, useRag = true, options = {}) {
    const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify({ messages, use_rag: useRag, ...options })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    return await response.json();
  }

  async storeMemory(content, metadata = null, collection = 'nexe_chat_memory') {
    const response = await fetch(`${this.baseUrl}/v1/memory/store`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify({ content, metadata, collection })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  }

  async searchMemory(query, limit = 5, collection = 'nexe_chat_memory') {
    const response = await fetch(`${this.baseUrl}/v1/memory/search`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify({ query, limit, collection })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    return data.results;
  }
}

// Usage
const client = new NexeClient('http://127.0.0.1:9119', 'el-teu-token');
const data = await client.chat([{ role: 'user', content: 'Hola!' }]);
console.log(data);
```

### cURL + jq

```bash
#!/bin/bash
BASE_URL="http://127.0.0.1:9119"
API_KEY="el-teu-token"

# Chat
chat() {
  local message="$1"
  curl -s -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"$message\"}]}" \
    | jq -r '.choices[0].message.content'
}

# Store memory
store_memory() {
  local content="$1"
  curl -s -X POST "$BASE_URL/v1/memory/store" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"content\":\"$content\"}" \
    | jq -r '.document_id'
}

# Search memory
search_memory() {
  local query="$1"
  curl -s -X POST "$BASE_URL/v1/memory/search" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"query\":\"$query\",\"limit\":3}" \
    | jq -r '.results[].content'
}

# Usage
chat "Hola, com estàs?"
store_memory "El meu projecte és NEXE"
search_memory "projecte"
```

---

## OpenAI compatibility

NEXE **partially** implements the OpenAI API:

| OpenAI | NEXE | Status |
|--------|------|--------|
| `/v1/chat/completions` | ✅ | Compatible in OpenAI-like format (MLX/Llama.cpp). Ollama may return native format. |
| `/v1/embeddings` | ❌ | Not implemented (501). |
| `/v1/models` | ❌ | Not implemented. |
| `/v1/completions` | ❌ | Legacy not supported. |

### Main differences

1. **`engine` parameter:** Allows forcing a specific engine (`ollama`, `mlx`, `llama_cpp`).
2. **`use_rag`:** NEXE extension to enable memory and documents.
3. **Streaming:** OpenAI-like SSE but not 100% identical.
4. **Function calling:** Not supported.
5. **Unimplemented parameters:** `top_p`, `frequency_penalty`, `presence_penalty`.

### Using NEXE with OpenAI clients

**Python (openai package):**

```python
import openai

# Point to NEXE
openai.api_base = "http://127.0.0.1:9119/v1"
openai.api_key = "el-teu-token"

response = openai.ChatCompletion.create(
    model="phi3",  # May be ignored depending on the engine
    messages=[
        {"role": "user", "content": "Hola!"}
    ]
)

print(response.choices[0].message.content)
```

**Langchain:**

```python
from langchain.chat_models import ChatOpenAI

llm = ChatOpenAI(
    openai_api_base="http://127.0.0.1:9119/v1",
    openai_api_key="el-teu-token",
    model_name="nexe"
)

response = llm.predict("Explica'm què és Python")
print(response)
```

---

## Interactive documentation

NEXE automatically generates Swagger documentation:

**Swagger UI:**
```
http://127.0.0.1:9119/docs
```

**ReDoc:**
```
http://127.0.0.1:9119/redoc
```

**OpenAPI JSON:**
```
http://127.0.0.1:9119/openapi.json
```

---

**Note:** This API is v0.8. Changes may occur in future versions. Check the updated documentation at `/docs`.
