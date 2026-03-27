# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referencia completa de la API REST de server-nexe 0.8.2. Cubre todos los endpoints: chat completions (compatible OpenAI, streaming, RAG), memoria (store, search), búsqueda RAG, subida documentos, sesiones, bootstrap, health checks, módulos, backends, i18n. Incluye autenticación (X-API-Key dual-key), rate limiting, marcadores streaming (MODEL_LOADING, RAG_AVG, MEM_SAVE) y configuración."
tags: [api, rest, endpoints, chat, memoria, rag, autenticacion, rate-limiting, streaming, openai-compatible, upload, sesiones, bootstrap, health, backends]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Referencia API REST — server-nexe 0.8.2

## URL Base

```
http://127.0.0.1:9119
```

Configurable vía `personality/server.toml` sección `[core.server]` o `.env` (HOST/PORT). Prioridad: server.toml > .env > por defecto.

Docs API (Swagger): `http://127.0.0.1:9119/docs`

## Autenticación

La mayoría de endpoints requieren cabecera `X-API-Key`. Valor del fichero `.env` (`NEXE_PRIMARY_API_KEY`).

**Sistema dual-key:** Dos claves pueden estar activas simultáneamente para rotación:
- `NEXE_PRIMARY_API_KEY` — siempre activa
- `NEXE_SECONDARY_API_KEY` — período de gracia para rotación

**Bootstrap token:** Para setup inicial, se genera un token de un solo uso al arranque (128-bit, TTL 30min).

## Rate Limiting

Configurable por endpoint vía `.env`:

| Variable | Por defecto | Aplica a |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/minuto | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/minuto | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/minuto | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/minuto | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/minuto | Todos los demás |

## Endpoints Core

### Chat

**POST /v1/chat/completions** (requiere API key)

Chat completion compatible OpenAI con RAG y streaming.

```json
{
  "messages": [{"role": "user", "content": "Hola"}],
  "model": "auto",
  "engine": "auto",
  "use_rag": true,
  "stream": false,
  "temperature": 0.7,
  "max_tokens": null
}
```

- `use_rag`: true por defecto — busca en 3 colecciones Qdrant
- `engine`: "auto" (defecto), "ollama", "mlx", "llama_cpp"
- `stream`: true retorna stream SSE con marcadores
- `max_tokens`: null = defecto del modelo, máx 32000

**Marcadores streaming** (inyectados en el stream SSE):
- `[MODEL:nombre]` — modelo activo
- `[MODEL_LOADING]` / `[MODEL_READY]` — estado carga modelo con timing
- `[RAG_AVG:0.75]` — puntuación RAG media
- `[RAG_ITEM:0.82|nexe_documentation|ARCHITECTURE.md]` — detalle por fuente
- `[MEM:2]` — hechos auto-guardados vía MEM_SAVE
- `[THINKING]` / `[/THINKING]` — tokens de razonamiento (modelos Ollama como qwen3.5)

### Info Sistema

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/` | GET | No | Info sistema (versión, estado, puerto) |
| `/health` | GET | No | Health check básico |
| `/health/ready` | GET | No | Readiness check (verifica módulos requeridos) |
| `/health/circuits` | GET | No | Estado circuit breakers (Ollama, Qdrant) |
| `/status` | GET | No | Estado tiempo real: motor activo, modelo, módulos |
| `/api/info` | GET | No | Info API y lista endpoints |
| `/docs` | GET | No | Documentación Swagger/OpenAPI interactiva |

### Módulos

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/modules` | GET | No | Lista módulos cargados y sus APIs |
| `/modules/{nombre}/routes` | GET | No | Rutas registradas de un módulo específico |

## Endpoints Memoria (prefijo: /v1/memory)

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/v1/memory/store` | POST | Sí | Guardar texto en una colección |
| `/v1/memory/search` | POST | Sí | Búsqueda semántica en una colección |
| `/v1/memory/health` | GET | No | Salud subsistema memoria + colecciones Qdrant |

## Endpoints RAG (prefijo: /v1/rag)

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/v1/rag/search` | POST | Sí | Búsqueda semántica en vector store RAG |
| `/v1/rag/add` | POST | Sí | Añadir documentos al vector store RAG |
| `/v1/rag/documents/{id}` | DELETE | Sí | Borrar documento del RAG |

## Endpoints Embeddings (prefijo: /v1/embeddings)

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Sí | Generar vectores embedding para textos |
| `/v1/embeddings/models` | GET | No | Listar modelos de embeddings disponibles |

## Endpoints Web UI (prefijo: /ui)

### Auth y Config

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/ui/auth` | GET | Sí | Verificar validez API key |
| `/ui/info` | GET | Sí | Info servidor (versión, idioma, features) |
| `/ui/lang` | POST | Sí | Establecer idioma servidor (ca/es/en) |
| `/ui/backends` | GET | Sí | Listar backends con nombres y tamaños modelos (GB) |
| `/ui/backend` | POST | Sí | Cambiar backend activo |

### Chat y Memoria

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/ui/chat` | POST | Sí | Streaming SSE chat (con MEM_SAVE, RAG, thinking tokens) |
| `/ui/memory/save` | POST | Sí | Guardar texto en memoria |
| `/ui/memory/recall` | POST | Sí | Recordar de memoria (filtrado por session_id) |

### Sesiones

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/ui/session/new` | POST | Sí | Crear nueva sesión |
| `/ui/session/{id}` | GET | Sí | Obtener datos sesión |
| `/ui/session/{id}/history` | GET | Sí | Obtener historial chat sesión |
| `/ui/session/{id}` | DELETE | Sí | Borrar sesión |
| `/ui/sessions` | GET | Sí | Listar todas las sesiones |

### Ficheros

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/ui/upload` | POST | Sí | Subir documento (aislado por sesión, indexado a user_knowledge) |
| `/ui/files` | GET | Sí | Listar ficheros subidos |
| `/ui/files/cleanup` | POST | Sí | Limpiar ficheros temporales |

**Upload:** Acepta .txt, .md, .pdf. Chunks 1500/200 chars. Metadatos sin LLM (instantáneo). Documentos aislados a la sesión vía session_id.

## Compatibilidad OpenAI

`/v1/chat/completions` es parcialmente compatible con el formato API de OpenAI:

**Soportado:** messages array, model, temperature, max_tokens, stream, top_p
**Campos extra:** use_rag (boolean), engine (string)
**No implementado:** /v1/embeddings estándar (usar /v1/embeddings/encode), /v1/models, /v1/completions (legacy)

Compatible con herramientas que usan formato API OpenAI: Cursor, Continue, Zed, scripts custom.

## Ejemplos Rápidos

```bash
# Health check
curl http://127.0.0.1:9119/health

# Chat (sin streaming)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: TU_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hola"}]}'

# Guardar en memoria
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: TU_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Me llamo Jordi", "collection": "user_knowledge"}'

# Buscar en memoria
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: TU_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "cómo me llamo", "collection": "user_knowledge", "limit": 3}'
```
