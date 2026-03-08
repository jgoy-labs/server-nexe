# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referència completa de l'API REST de NEXE 0.8. Cobreix autenticació X-API-Key, endpoints de chat, memory, RAG, admin i mètriques Prometheus. Inclou exemples en Python, JavaScript i cURL amb compatibilitat parcial OpenAI."
tags: [api, rest, endpoints, chat, memory, rag, autenticació, rate-limiting]
chunk_size: 1200
priority: P1

# === OPCIONAL ===
lang: ca
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# API Reference - NEXE 0.8

NEXE ofereix una **API REST** per integrar-lo amb altres aplicacions. Aquesta documentació descriu els endpoints disponibles i els comportaments reals segons el codi actual.

## Índex

1. [Introducció](#introducció)
2. [URL base i configuració del servidor](#url-base-i-configuració-del-servidor)
3. [Autenticació](#autenticació)
4. [Format de requests/responses](#format-de-requestsresponses)
5. [Endpoints](#endpoints)
6. [Rate limiting](#rate-limiting)
7. [Exemples de clients](#exemples-de-clients)
8. [Compatibilitat OpenAI](#compatibilitat-openai)
9. [Documentació interactiva](#documentació-interactiva)

---

## Introducció

L'API de NEXE segueix principis REST i retorna JSON. Disposa de rutes versionades `/v1` i d'endpoints de sistema per monitoratge i administració.

### Característiques

- **REST:** Endpoints amb verbs HTTP estàndard
- **JSON:** Entrada i sortida habitualment en JSON
- **OpenAPI:** Documentació automàtica a `/docs`
- **Compatibilitat OpenAI (parcial):** `/v1/chat/completions` amb format OpenAI-like en alguns motors
- **Async:** Suporta operacions asíncrones

---

## URL base i configuració del servidor

### Per defecte

```
http://127.0.0.1:9119
```

### Configuració

El host/port es configuren preferentment a `server.toml` (es busca en `server.toml`, `personality/server.toml` o `config/server.toml`). Exemple:

```toml
[core.server]
host = "127.0.0.1"
port = 9119
```

**Alternativa (menys recomanada):** També es poden usar variables d'entorn `.env`:

```bash
PORT=9119
HOST=127.0.0.1
```

**Prioritat:** server.toml > .env > defaults

### Accés remot

**⚠️ Important:** Per defecte, NEXE només escolta a `127.0.0.1` per seguretat.

Per accedir remotament:

1. Configura `host = "0.0.0.0"` al `server.toml`.
2. **Activa autenticació** (veure secció següent).
3. Usa HTTPS si exposes públicament (reverse proxy amb nginx/caddy).

---

## Autenticació

NEXE fa servir **API keys** via header `X-API-Key`.

### Variables d'entorn suportades

- `NEXE_PRIMARY_API_KEY` (principal)
- `NEXE_PRIMARY_KEY_EXPIRES` (opcional, ISO datetime)
- `NEXE_SECONDARY_API_KEY` (opcional, clau antiga en període de gràcia)
- `NEXE_SECONDARY_KEY_EXPIRES` (opcional)
- `NEXE_ADMIN_API_KEY` (legacy, fallback si no hi ha primary)

### Exemple d'ús

```bash
curl -H "X-API-Key: el-teu-token" \
  http://127.0.0.1:9119/health
```

### Mode desenvolupament (bypass)

- `NEXE_DEV_MODE=true` permet bypass **només** si `NEXE_ENV != production`.
- Per accés remot en DEV cal `NEXE_DEV_MODE_ALLOW_REMOTE=true`.
- Si **no** hi ha cap clau vàlida i DEV no està activat, l'API retorna **500** (misconfiguration).

---

## Format de requests/responses

- **JSON** per defecte (`Content-Type: application/json`).
- Alguns endpoints accepten **multipart/form-data** (p. ex. `/rag/upload`).
- Els errors poden ser `"detail": "..."` o `"detail": { ... }` segons l'endpoint.

Exemple d'error típic:

```json
{
  "detail": "Invalid or expired API key"
}
```

---

## Endpoints

### Sistema (core)

#### GET /
Informació bàsica del sistema.

**Response (exemple):**
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
Health check del servidor.

**Response (exemple):**
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
Readiness check. Valida mòduls requerits i estat de salut.

**Response (exemple):**
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
Estat dels circuit breakers (ollama, qdrant, http_external).

**Response (exemple):**
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
Estat runtime (engine actual, model configurat, mòduls carregats).

**Response (exemple):**
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
Informació bàsica de l'API i llista d'endpoints principals.

**Response (exemple):**
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
Informació sobre l'estat del bootstrap (frontend onboarding).

---

#### GET /modules
Llista estadístiques d'integració de mòduls.

#### GET /modules/{module_name}/routes
Rutes exposades per un mòdul concret.

---

### API v1 (metadades)

#### GET /v1
Informació general de l'API versionada.

#### GET /v1/health
Health check específic per l'API v1.

---

### Chat

#### POST /v1/chat/completions
Generar una resposta de chat. Compatible **parcialment** amb OpenAI.

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

**Paràmetres suportats:**

| Paràmetre | Tipus | Requerit | Descripció | Default |
|-----------|-------|----------|------------|---------|
| `messages` | array | Sí | Array de missatges | - |
| `model` | string | No | Nom del model (depèn de motor) | Depèn del motor |
| `engine` | string | No | `auto`, `ollama`, `mlx`, `llama_cpp` | `auto` |
| `temperature` | float | No | Creativitat (0.0-2.0) | 0.7 |
| `max_tokens` | int | No | Màxim tokens (1-32000) | `null` (motor decideix) |
| `stream` | bool | No | Streaming SSE | false |
| `use_rag` | bool | No | Activar RAG/memòria | true |

**Notes importants:**
- `top_p`, `frequency_penalty`, `presence_penalty` **no** estan implementats.
- En mode **Ollama**, la resposta **no streaming** és el format natiu d'Ollama.
- En mode **MLX/Llama.cpp**, la resposta és OpenAI-like.

**Response OpenAI-like (MLX/Llama.cpp, exemple):**
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

**Headers addicionals (no streaming):**
- Pot incloure `nexe_engine` i `nexe_fallback` al JSON.

**Headers addicionals (streaming):**
- `X-Nexe-Engine`: Motor utilitzat (ollama/mlx/llama_cpp)
- `X-Nexe-Fallback-From`: Motor sol·licitat si hi ha fallback
- `X-Nexe-Fallback-Reason`: Motiu del fallback (module_unavailable/execution_failed)

**Streaming (SSE):**
```
data: {"choices":[{"delta":{"content":"Hola"}}]}

data: [DONE]
```

---

### Memòria (v1)

#### POST /v1/memory/store
Guardar informació a la memòria semàntica.

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

**Response (exemple):**
```json
{
  "success": true,
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Content stored successfully"
}
```

---

#### POST /v1/memory/search
Cercar informació a la memòria.

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

**Response (exemple):**
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
Health check del subsistema de memòria.

**Response (exemple):**
```json
{
  "status": "healthy",
  "collections": 3,
  "initialized": true
}
```

**Si Qdrant no disponible:**
```json
{
  "status": "unhealthy",
  "error": "Connection refused",
  "hint": "Ensure Qdrant is running"
}
```

---

### RAG (mòdul)

⚠️ **NOTA IMPORTANT:** Hi ha dos conjunts d'endpoints RAG:
- `/v1/rag/*` → Endpoints versionats **no implementats** (501) disponibles pròximament
- `/rag/*` → Endpoints **funcionals** del mòdul RAG (documentats a continuació)

Aquests endpoints són del mòdul RAG (`/rag`). S'utilitzen per afegir documents i fer cerques directes.

#### POST /rag/document (auth requerida)
Afegir document de text.

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

**Response (exemple):**
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

#### POST /rag/search (auth requerida)
Cercar documents.

**Request (JSON):**
```json
{
  "query": "cerca",
  "top_k": 5,
  "filters": {},
  "source": "personality"
}
```

**Response (exemple):**
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

#### POST /rag/upload (auth requerida)
Pujar un fitxer i indexar-lo (multipart/form-data). **Màxim 50MB.**

**Request (exemple):**
```bash
curl -X POST http://127.0.0.1:9119/rag/upload \
  -H "X-API-Key: el-teu-token" \
  -F "file=@README.md" \
  -F 'metadata={"category":"docs"}'
```

**Response (exemple):**
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
Health del mòdul RAG (públic).

#### GET /rag/info
Info del mòdul RAG (públic).

#### GET /rag/files/stats (auth requerida)
Estadístiques de fitxers pujats.

**Response (exemple):**
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
UI web del mòdul RAG.

---

### Mòdul Memory (legacy)

#### GET /memory/health
Health check del mòdul Memory.

#### GET /memory/info
Info del mòdul Memory.

---

### Endpoints no implementats (pròximament)

Aquests endpoints existeixen però retornen **501 Not Implemented**:

**API versionada (futura):**
- `POST /v1/embeddings/encode` → pròximament
- `GET /v1/embeddings/models` → pròximament
- `GET /v1/documents/` → pròximament
- `POST /v1/rag/search` → pròximament
- `POST /v1/rag/add` → pròximament
- `DELETE /v1/rag/documents/{id}` → pròximament

**Nota:** Els endpoints `/rag/*` (sense /v1) **SÍ que són funcionals** (vegeu secció RAG).

---

### Administració del sistema

Endpoints d'admin sota `/admin/system`:

#### POST /admin/system/restart (auth requerida)
Reinicia el servidor via supervisor.

**Request:**
```bash
curl -X POST http://127.0.0.1:9119/admin/system/restart \
  -H "X-API-Key: el-teu-token"
```

**Response (exemple):**
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

#### GET /admin/system/status (auth requerida)
Status del supervisor.

**Response (exemple):**
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

#### GET /admin/system/health (públic)
Health check simple (no requereix auth).

**Response (exemple):**
```json
{
  "status": "healthy",
  "version": "0.8.0",
  "platform": "Nexe Framework",
  "uptime": "available"
}
```

---

### Mètriques (Prometheus)

#### GET /metrics
Mètriques en format Prometheus (text/plain).

**Response (exemple):**
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
Health check del sistema de mètriques.

**Response (exemple):**
```json
{
  "status": "healthy",
  "collectors_active": true,
  "metrics_count": 25
}
```

---

#### GET /metrics/json
Mètriques en format JSON (més llegible).

**Response (exemple):**
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

Rate limiting basat en `slowapi`, amb límits configurables per entorn:

- Global: `NEXE_RATE_LIMIT_GLOBAL` (default `100/minute`)
- Public: `NEXE_RATE_LIMIT_PUBLIC` (default `30/minute`)
- Authenticated: `NEXE_RATE_LIMIT_AUTHENTICATED` (default `300/minute`)
- Admin: `NEXE_RATE_LIMIT_ADMIN` (default `100/minute`)
- Health: `NEXE_RATE_LIMIT_HEALTH` (default `1000/minute`)

**Headers de rate limit (si està actiu):**

```
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
X-RateLimit-Used
```

**Exemple de configuració (.env):**
```bash
NEXE_RATE_LIMIT_GLOBAL=200/minute
NEXE_RATE_LIMIT_PUBLIC=60/minute
NEXE_RATE_LIMIT_AUTHENTICATED=500/minute
```

**Response quan excedeix límit:**
```json
{
  "detail": "Rate limit exceeded. Try again in 30 seconds.",
  "retry_after": 30
}
```

**Status:** 429 Too Many Requests

Nota: Alguns endpoints defineixen límits específics amb decoradors `@limiter.limit(...)`.

---

## Exemples de clients

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

# Ús
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

// Ús
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

# Guardar memòria
store_memory() {
  local content="$1"
  curl -s -X POST "$BASE_URL/v1/memory/store" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"content\":\"$content\"}" \
    | jq -r '.document_id'
}

# Cercar memòria
search_memory() {
  local query="$1"
  curl -s -X POST "$BASE_URL/v1/memory/search" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"query\":\"$query\",\"limit\":3}" \
    | jq -r '.results[].content'
}

# Ús
chat "Hola, com estàs?"
store_memory "El meu projecte és NEXE"
search_memory "projecte"
```

---

## Compatibilitat OpenAI

NEXE implementa **parcialment** l'API OpenAI:

| OpenAI | NEXE | Estat |
|--------|------|-------|
| `/v1/chat/completions` | ✅ | Compatible en format OpenAI-like (MLX/Llama.cpp). Ollama pot retornar format natiu. |
| `/v1/embeddings` | ❌ | No implementat (501). |
| `/v1/models` | ❌ | No implementat. |
| `/v1/completions` | ❌ | Legacy no suportat. |

### Diferències principals

1. **Paràmetre `engine`:** Permet forçar motor (`ollama`, `mlx`, `llama_cpp`).
2. **`use_rag`:** Extensió NEXE per activar memòria i documents.
3. **Streaming:** SSE OpenAI-like però no 100% idèntic.
4. **Function calling:** No suportat.
5. **Paràmetres no implementats:** `top_p`, `frequency_penalty`, `presence_penalty`.

### Usar NEXE amb clients OpenAI

**Python (openai package):**

```python
import openai

# Apuntar a NEXE
openai.api_base = "http://127.0.0.1:9119/v1"
openai.api_key = "el-teu-token"

response = openai.ChatCompletion.create(
    model="phi3",  # Pot ser ignorat segons motor
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

## Documentació interactiva

NEXE genera documentació Swagger automàticament:

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

**Nota:** Aquesta API és la v0.8. Pot haver-hi canvis en futures versions. Consulta la documentació actualitzada a `/docs`.
