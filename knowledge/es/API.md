# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "REST API de server-nexe: endpoints /v1/chat/completions (compatible OpenAI), /memory/store, /memory/search, /rag/search, /upload, /sessions. Autenticacion X-API-Key dual-key. Rate limiting por endpoint. Streaming SSE. Puerto 9119 por defecto. Ejemplos curl y Python."
tags: [api, rest, endpoints, chat, memory, rag, authentication, rate-limiting, streaming, openai-compatible, upload, sessions, bootstrap, health, backends, encryption, curl, python]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: api
author: "Jordi Goy"
expires: null
---

# Referencia REST API — server-nexe 0.9.0 pre-release

## URL Base

```
http://127.0.0.1:9119
```

Configurable via `personality/server.toml` seccion `[core.server]` o `.env` (HOST/PORT). Prioridad: server.toml > .env > por defecto.

Docs API (Swagger): `http://127.0.0.1:9119/docs`

## Autenticacion

La mayoria de endpoints requieren cabecera `X-API-Key`. Valor del fichero `.env` (`NEXE_PRIMARY_API_KEY`).

**Sistema dual-key:** Dos claves pueden estar activas simultaneamente para rotacion:
- `NEXE_PRIMARY_API_KEY` — siempre activa
- `NEXE_SECONDARY_API_KEY` — periodo de gracia para rotacion
- Seguimiento de expiracion via `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`

**Token bootstrap:** Para configuracion inicial, se genera un token de un solo uso al arranque (256-bit, TTL 30min). Se muestra en la salida de consola.

## Rate Limiting

El rate limiting se aplica a **todos los endpoints** — tanto API como Web UI.

### Endpoints API (configurables via `.env`)

| Variable | Por defecto | Aplica a |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/minuto | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/minuto | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/minuto | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/minuto | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/minuto | Todos los demas endpoints |

### Endpoints Web UI (por endpoint)

| Endpoint | Rate limit |
|----------|-----------|
| POST /ui/chat | 20/minuto |
| POST /ui/memory/save | 10/minuto |
| POST /ui/memory/recall | 30/minuto |
| POST /ui/upload | 5/minuto |
| POST /ui/files/cleanup | 5/minuto |
| GET /ui/session/{id} | 30/minuto |
| DELETE /ui/session/{id} | 10/minuto |

## Endpoints principales

### Chat

**POST /v1/chat/completions** (requiere API key, rate limit: 60/min)

Chat completion compatible con OpenAI con soporte de RAG y streaming.

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
- `temperature`: 0.0-2.0 (defecto 0.7)
- `max_tokens`: null = usar defecto del modelo, maximo 32000

**Marcadores de streaming** (inyectados en el stream SSE, parseados por la UI):
- `[MODEL:nombre]` — modelo activo
- `[MODEL_LOADING]` / `[MODEL_READY]` — estado de carga del modelo con timing
- `[RAG_AVG:0.75]` — puntuacion media de relevancia RAG
- `[RAG_ITEM:0.82|nexe_documentation|ARCHITECTURE.md]` — detalle por fuente
- `[MEM:2]` — numero de hechos auto-guardados via MEM_SAVE
- `[COMPACT:N]` — indicador de compactacion de contexto
- `[THINKING]` / `[/THINKING]` — tokens de razonamiento (modelos Ollama como qwen3.5)
- `[DOC_TRUNCATED:XX%]` — porcentaje de documento descartado por limite de contexto (nuevo 2026-04-02)

### Informacion del sistema

| Endpoint | Metodo | Auth | Descripcion |
|----------|--------|------|-------------|
| `/` | GET | No | Info del sistema (version, estado, puerto) |
| `/health` | GET | No | Health check basico |
| `/health/ready` | GET | No | Readiness check (verifica modulos requeridos) |
| `/health/circuits` | GET | No | Estado de circuit breakers (Ollama, Qdrant) |
| `/status` | GET | No | Estado en tiempo real: engine activo, modelo, modulos cargados |
| `/api/info` | GET | No | Info de la API y lista de endpoints disponibles |
| `/docs` | GET | No | Documentacion interactiva Swagger/OpenAPI |

### Modulos

| Endpoint | Metodo | Auth | Descripcion |
|----------|--------|------|-------------|
| `/modules` | GET | No | Listar modulos cargados y sus APIs |
| `/modules/{nombre}/routes` | GET | No | Rutas registradas por un modulo especifico |

### Bootstrap

| Endpoint | Metodo | Auth | Descripcion |
|----------|--------|------|-------------|
| `/api/bootstrap` | POST | Token | Inicializar sesion con token bootstrap |
| `/api/regenerate-bootstrap` | POST | localhost | Regenerar token bootstrap expirado |
| `/api/bootstrap/info` | GET | No | Estado del sistema bootstrap |

## Endpoints de memoria (prefijo: /v1/memory)

| Endpoint | Metodo | Auth | Descripcion |
|----------|--------|------|-------------|
| `/v1/memory/store` | POST | Si | Guardar texto en una coleccion |
| `/v1/memory/search` | POST | Si | Busqueda semantica en una coleccion |
| `/v1/memory/health` | GET | No | Salud del subsistema de memoria + colecciones Qdrant |

**Peticion de almacenamiento:**
```json
{
  "text": "Informacion a guardar",
  "collection": "user_knowledge",
  "metadata": {"source": "api", "tags": ["ejemplo"]}
}
```

**Peticion de busqueda:**
```json
{
  "query": "consulta de busqueda",
  "collection": "user_knowledge",
  "limit": 5,
  "threshold": 0.35
}
```

## Endpoints RAG (prefijo: /v1/rag)

| Endpoint | Metodo | Auth | Descripcion |
|----------|--------|------|-------------|
| `/v1/rag/search` | POST | Si | Busqueda semantica en el vector store RAG |
| `/v1/rag/add` | POST | Si | Anadir documentos al vector store RAG |
| `/v1/rag/documents/{id}` | DELETE | Si | Borrar documento del RAG |

## Endpoints de embeddings (prefijo: /v1/embeddings)

| Endpoint | Metodo | Auth | Descripcion |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Si | Generar vectores de embedding para textos |
| `/v1/embeddings/models` | GET | No | Listar modelos de embeddings disponibles |

## Endpoints Web UI (prefijo: /ui)

Estos endpoints sirven la interfaz web y son usados por el frontend JavaScript. Todos tienen validacion de entrada via `validate_string_input()`.

### Auth y configuracion

| Endpoint | Metodo | Auth | Rate limit | Descripcion |
|----------|--------|------|-----------|-------------|
| `/ui/auth` | GET | Si | default | Verificar validez de API key |
| `/ui/info` | GET | Si | default | Info del servidor (version, idioma, funcionalidades) |
| `/ui/lang` | POST | Si | default | Establecer idioma del servidor (ca/es/en) |
| `/ui/backends` | GET | Si | default | Listar backends con nombres de modelo y tamanos (GB) |
| `/ui/backend` | POST | Si | default | Cambiar backend activo |
| `/ui/health` | GET | No | default | Salud del modulo Web UI |

### Chat y memoria

| Endpoint | Metodo | Auth | Rate limit | Descripcion |
|----------|--------|------|-----------|-------------|
| `/ui/chat` | POST | Si | 20/min | Streaming SSE chat (MEM_SAVE, RAG, thinking tokens) |
| `/ui/memory/save` | POST | Si | 10/min | Guardar texto en memoria (valida content, session_id) |
| `/ui/memory/recall` | POST | Si | 30/min | Recuperar de memoria (valida query, session_id) |

### Sesiones

| Endpoint | Metodo | Auth | Rate limit | Descripcion |
|----------|--------|------|-----------|-------------|
| `/ui/session/new` | POST | Si | default | Crear nueva sesion |
| `/ui/session/{id}` | GET | Si | 30/min | Obtener datos de sesion (valida session_id) |
| `/ui/session/{id}/history` | GET | Si | 30/min | Obtener historial de chat de la sesion |
| `/ui/session/{id}` | DELETE | Si | 10/min | Borrar sesion |
| `/ui/session/{id}` | PATCH | Si | default | Renombrar sesion (nuevo 2026-04-01) |
| `/ui/session/{id}/clear-document` | POST | Si | default | Limpiar documento adjunto de la sesion (nuevo 2026-04-02) |
| `/ui/sessions` | GET | Si | default | Listar todas las sesiones |

### Ficheros

| Endpoint | Metodo | Auth | Rate limit | Descripcion |
|----------|--------|------|-----------|-------------|
| `/ui/upload` | POST | Si | 5/min | Subir documento (valida filename, aislado por sesion) |
| `/ui/files` | GET | Si | default | Listar ficheros subidos |
| `/ui/files/cleanup` | POST | Si | 5/min | Limpiar ficheros temporales |

**Upload:** Acepta .txt, .md, .pdf. Chunking dinamico segun tamano del documento (800/1000/1200/1500 chars). Validacion de magic bytes (SEC-004). Metadatos generados sin LLM (instantaneo). Documentos aislados a la sesion de subida via session_id.

## Comandos CLI de encriptacion

Estos son comandos CLI (no endpoints HTTP):

| Comando | Descripcion |
|---------|-------------|
| `./nexe encryption status` | Mostrar estado de encriptacion de todos los componentes de almacenamiento |
| `./nexe encryption encrypt-all` | Migrar todos los datos existentes a formato encriptado |
| `./nexe encryption export-key` | Exportar clave maestra (hex o base64, para backup) |

## Compatibilidad OpenAI

`/v1/chat/completions` es parcialmente compatible con el formato de API OpenAI:

**Soportado:** array de messages, model, temperature, max_tokens, stream, top_p
**Campos extra:** use_rag (boolean), engine (string)
**No implementado:** /v1/embeddings (usar /v1/embeddings/encode en su lugar), /v1/models, /v1/completions (legacy)

Compatible con herramientas que usan formato de API OpenAI: Cursor, Continue, Zed, scripts personalizados.

## Configuracion

| Ajuste | Ubicacion | Proposito |
|--------|----------|---------|
| Host/Puerto | server.toml `[core.server]` | Direccion de enlace del servidor |
| API keys | .env | NEXE_PRIMARY_API_KEY, NEXE_SECONDARY_API_KEY |
| Rate limits | .env | Variables NEXE_RATE_LIMIT_* |
| Timeout | .env | NEXE_DEFAULT_MAX_TOKENS (defecto 4096) |
| Origenes CORS | server.toml `[core.server]` | Origenes permitidos |
| Encriptacion | .env | NEXE_ENCRYPTION_ENABLED (defecto false) |

## Ejemplos rapidos

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
  -d '{"query": "como me llamo", "collection": "user_knowledge", "limit": 3}'
```
