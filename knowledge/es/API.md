# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referencia completa de la API REST de NEXE 0.8. Cubre autenticación X-API-Key, endpoints de chat, memory, RAG, admin y métricas Prometheus. Incluye ejemplos en Python, JavaScript y cURL con compatibilidad parcial OpenAI."
tags: [api, rest, endpoints, chat, memory, rag, autenticació, rate-limiting]
chunk_size: 1200
priority: P1

# === OPCIONAL ===
lang: es
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# API Reference - NEXE 0.8

NEXE ofrece una **API REST** para integrarlo con otras aplicaciones. Esta documentación describe los endpoints disponibles y los comportamientos reales según el código actual.

## Índice

1. [Introducción](#introducción)
2. [URL base y configuración del servidor](#url-base-y-configuración-del-servidor)
3. [Autenticación](#autenticación)
4. [Formato de requests/responses](#formato-de-requestsresponses)
5. [Endpoints](#endpoints)
6. [Rate limiting](#rate-limiting)
7. [Ejemplos de clientes](#ejemplos-de-clientes)
8. [Compatibilidad OpenAI](#compatibilidad-openai)
9. [Documentación interactiva](#documentación-interactiva)

---

## Introducción

La API de NEXE sigue principios REST y devuelve JSON. Dispone de rutas versionadas `/v1` y de endpoints de sistema para monitorización y administración.

### Características

- **REST:** Endpoints con verbos HTTP estándar
- **JSON:** Entrada y salida habitualmente en JSON
- **OpenAPI:** Documentación automática en `/docs`
- **Compatibilidad OpenAI (parcial):** `/v1/chat/completions` con formato OpenAI-like en algunos motores
- **Async:** Soporta operaciones asíncronas

---

## URL base y configuración del servidor

### Por defecto

```
http://127.0.0.1:9119
```

### Configuración

El host/port se configuran preferentemente en `server.toml` (se busca en `server.toml`, `personality/server.toml` o `config/server.toml`). Ejemplo:

```toml
[core.server]
host = "127.0.0.1"
port = 9119
```

**Alternativa (menos recomendada):** También se pueden usar variables de entorno `.env`:

```bash
PORT=9119
HOST=127.0.0.1
```

**Prioridad:** server.toml > .env > defaults

### Acceso remoto

**⚠️ Importante:** Por defecto, NEXE solo escucha en `127.0.0.1` por seguridad.

Para acceder remotamente:

1. Configura `host = "0.0.0.0"` en el `server.toml`.
2. **Activa la autenticación** (ver sección siguiente).
3. Usa HTTPS si expones públicamente (reverse proxy con nginx/caddy).

---

## Autenticación

NEXE usa **API keys** mediante el header `X-API-Key`.

### Variables de entorno soportadas

- `NEXE_PRIMARY_API_KEY` (principal)
- `NEXE_PRIMARY_KEY_EXPIRES` (opcional, ISO datetime)
- `NEXE_SECONDARY_API_KEY` (opcional, clave antigua en período de gracia)
- `NEXE_SECONDARY_KEY_EXPIRES` (opcional)
- `NEXE_ADMIN_API_KEY` (legacy, fallback si no hay primary)

### Ejemplo de uso

```bash
curl -H "X-API-Key: el-teu-token" \
  http://127.0.0.1:9119/health
```

### Modo desarrollo (bypass)

- `NEXE_DEV_MODE=true` permite bypass **solo** si `NEXE_ENV != production`.
- Para acceso remoto en DEV se requiere `NEXE_DEV_MODE_ALLOW_REMOTE=true`.
- Si **no** hay ninguna clave válida y DEV no está activado, la API devuelve **500** (misconfiguration).

---

## Formato de requests/responses

- **JSON** por defecto (`Content-Type: application/json`).
- Algunos endpoints aceptan **multipart/form-data** (p. ej. `/rag/upload`).
- Los errores pueden ser `"detail": "..."` o `"detail": { ... }` según el endpoint.

Ejemplo de error típico:

```json
{
  "detail": "Invalid or expired API key"
}
```

---

## Endpoints

### Sistema (core)

#### GET /
Información básica del sistema.

**Response (ejemplo):**
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

**Response (ejemplo):**
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
Readiness check. Valida módulos requeridos y estado de salud.

**Response (ejemplo):**
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
Estado de los circuit breakers (ollama, qdrant, http_external).

**Response (ejemplo):**
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
Estado runtime (motor actual, modelo configurado, módulos cargados).

**Response (ejemplo):**
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
Información básica de la API y lista de endpoints principales.

**Response (ejemplo):**
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
Información sobre el estado del bootstrap (frontend onboarding).

---

#### GET /modules
Lista estadísticas de integración de módulos.

#### GET /modules/{module_name}/routes
Rutas expuestas por un módulo concreto.

---

### API v1 (metadatos)

#### GET /v1
Información general de la API versionada.

#### GET /v1/health
Health check específico para la API v1.

---

### Chat

#### POST /v1/chat/completions
Generar una respuesta de chat. Compatible **parcialmente** con OpenAI.

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

**Parámetros soportados:**

| Parámetro | Tipo | Requerido | Descripción | Default |
|-----------|------|-----------|-------------|---------|
| `messages` | array | Sí | Array de mensajes | - |
| `model` | string | No | Nombre del modelo (depende del motor) | Depende del motor |
| `engine` | string | No | `auto`, `ollama`, `mlx`, `llama_cpp` | `auto` |
| `temperature` | float | No | Creatividad (0.0-2.0) | 0.7 |
| `max_tokens` | int | No | Máximo tokens (1-32000) | `null` (el motor decide) |
| `stream` | bool | No | Streaming SSE | false |
| `use_rag` | bool | No | Activar RAG/memoria | true |

**Notas importantes:**
- `top_p`, `frequency_penalty`, `presence_penalty` **no** están implementados.
- En modo **Ollama**, la respuesta **no streaming** es el formato nativo de Ollama.
- En modo **MLX/Llama.cpp**, la respuesta es OpenAI-like.

**Response OpenAI-like (MLX/Llama.cpp, ejemplo):**
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

**Headers adicionales (no streaming):**
- Puede incluir `nexe_engine` y `nexe_fallback` en el JSON.

**Headers adicionales (streaming):**
- `X-Nexe-Engine`: Motor utilizado (ollama/mlx/llama_cpp)
- `X-Nexe-Fallback-From`: Motor solicitado si hay fallback
- `X-Nexe-Fallback-Reason`: Motivo del fallback (module_unavailable/execution_failed)

**Streaming (SSE):**
```
data: {"choices":[{"delta":{"content":"Hola"}}]}

data: [DONE]
```

---

### Memoria (v1)

#### POST /v1/memory/store
Guardar información en la memoria semántica.

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

**Response (ejemplo):**
```json
{
  "success": true,
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Content stored successfully"
}
```

---

#### POST /v1/memory/search
Buscar información en la memoria.

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

**Response (ejemplo):**
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
Health check del subsistema de memoria.

**Response (ejemplo):**
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

### RAG (módulo)

⚠️ **NOTA IMPORTANTE:** Hay dos conjuntos de endpoints RAG:
- `/v1/rag/*` → Endpoints versionados **no implementados** (501) disponibles próximamente
- `/rag/*` → Endpoints **funcionales** del módulo RAG (documentados a continuación)

Estos endpoints son del módulo RAG (`/rag`). Se utilizan para añadir documentos y hacer búsquedas directas.

#### POST /rag/document (auth requerida)
Añadir documento de texto.

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

**Response (ejemplo):**
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
Buscar documentos.

**Request (JSON):**
```json
{
  "query": "cerca",
  "top_k": 5,
  "filters": {},
  "source": "personality"
}
```

**Response (ejemplo):**
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
Subir un fichero e indexarlo (multipart/form-data). **Máximo 50MB.**

**Request (ejemplo):**
```bash
curl -X POST http://127.0.0.1:9119/rag/upload \
  -H "X-API-Key: el-teu-token" \
  -F "file=@README.md" \
  -F 'metadata={"category":"docs"}'
```

**Response (ejemplo):**
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

**Errores:**
- `413`: File too large (max 50MB)
- `400`: Unsupported file type
- `500`: Processing error

---

#### GET /rag/health
Health del módulo RAG (público).

#### GET /rag/info
Info del módulo RAG (público).

#### GET /rag/files/stats (auth requerida)
Estadísticas de ficheros subidos.

**Response (ejemplo):**
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
UI web del módulo RAG.

---

### Módulo Memory (legacy)

#### GET /memory/health
Health check del módulo Memory.

#### GET /memory/info
Info del módulo Memory.

---

### Endpoints no implementados (próximamente)

Estos endpoints existen pero devuelven **501 Not Implemented**:

**API versionada (futura):**
- `POST /v1/embeddings/encode` → próximamente
- `GET /v1/embeddings/models` → próximamente
- `GET /v1/documents/` → próximamente
- `POST /v1/rag/search` → próximamente
- `POST /v1/rag/add` → próximamente
- `DELETE /v1/rag/documents/{id}` → próximamente

**Nota:** Los endpoints `/rag/*` (sin /v1) **SÍ son funcionales** (ver sección RAG).

---

### Administración del sistema

Endpoints de admin bajo `/admin/system`:

#### POST /admin/system/restart (auth requerida)
Reinicia el servidor vía supervisor.

**Request:**
```bash
curl -X POST http://127.0.0.1:9119/admin/system/restart \
  -H "X-API-Key: el-teu-token"
```

**Response (ejemplo):**
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

**Response (ejemplo):**
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

#### GET /admin/system/health (público)
Health check simple (no requiere auth).

**Response (ejemplo):**
```json
{
  "status": "healthy",
  "version": "0.8.0",
  "platform": "Nexe Framework",
  "uptime": "available"
}
```

---

### Métricas (Prometheus)

#### GET /metrics
Métricas en formato Prometheus (text/plain).

**Response (ejemplo):**
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
Health check del sistema de métricas.

**Response (ejemplo):**
```json
{
  "status": "healthy",
  "collectors_active": true,
  "metrics_count": 25
}
```

---

#### GET /metrics/json
Métricas en formato JSON (más legible).

**Response (ejemplo):**
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

Rate limiting basado en `slowapi`, con límites configurables por entorno:

- Global: `NEXE_RATE_LIMIT_GLOBAL` (default `100/minute`)
- Public: `NEXE_RATE_LIMIT_PUBLIC` (default `30/minute`)
- Authenticated: `NEXE_RATE_LIMIT_AUTHENTICATED` (default `300/minute`)
- Admin: `NEXE_RATE_LIMIT_ADMIN` (default `100/minute`)
- Health: `NEXE_RATE_LIMIT_HEALTH` (default `1000/minute`)

**Headers de rate limit (si está activo):**

```
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
X-RateLimit-Used
```

**Ejemplo de configuración (.env):**
```bash
NEXE_RATE_LIMIT_GLOBAL=200/minute
NEXE_RATE_LIMIT_PUBLIC=60/minute
NEXE_RATE_LIMIT_AUTHENTICATED=500/minute
```

**Response cuando se excede el límite:**
```json
{
  "detail": "Rate limit exceeded. Try again in 30 seconds.",
  "retry_after": 30
}
```

**Status:** 429 Too Many Requests

Nota: Algunos endpoints definen límites específicos con decoradores `@limiter.limit(...)`.

---

## Ejemplos de clientes

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

# Uso
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

// Uso
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

# Guardar memoria
store_memory() {
  local content="$1"
  curl -s -X POST "$BASE_URL/v1/memory/store" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"content\":\"$content\"}" \
    | jq -r '.document_id'
}

# Buscar en memoria
search_memory() {
  local query="$1"
  curl -s -X POST "$BASE_URL/v1/memory/search" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"query\":\"$query\",\"limit\":3}" \
    | jq -r '.results[].content'
}

# Uso
chat "Hola, com estàs?"
store_memory "El meu projecte és NEXE"
search_memory "projecte"
```

---

## Compatibilidad OpenAI

NEXE implementa **parcialmente** la API OpenAI:

| OpenAI | NEXE | Estado |
|--------|------|--------|
| `/v1/chat/completions` | ✅ | Compatible en formato OpenAI-like (MLX/Llama.cpp). Ollama puede devolver formato nativo. |
| `/v1/embeddings` | ❌ | No implementado (501). |
| `/v1/models` | ❌ | No implementado. |
| `/v1/completions` | ❌ | Legacy no soportado. |

### Diferencias principales

1. **Parámetro `engine`:** Permite forzar motor (`ollama`, `mlx`, `llama_cpp`).
2. **`use_rag`:** Extensión NEXE para activar memoria y documentos.
3. **Streaming:** SSE OpenAI-like pero no 100% idéntico.
4. **Function calling:** No soportado.
5. **Parámetros no implementados:** `top_p`, `frequency_penalty`, `presence_penalty`.

### Usar NEXE con clientes OpenAI

**Python (openai package):**

```python
import openai

# Apuntar a NEXE
openai.api_base = "http://127.0.0.1:9119/v1"
openai.api_key = "el-teu-token"

response = openai.ChatCompletion.create(
    model="phi3",  # Puede ser ignorado según el motor
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

## Documentación interactiva

NEXE genera documentación Swagger automáticamente:

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

**Nota:** Esta API es la v0.8. Puede haber cambios en futuras versiones. Consulta la documentación actualizada en `/docs`.
