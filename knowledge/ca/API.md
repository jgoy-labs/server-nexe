# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referència completa de l'API REST de server-nexe 0.8.2. Cobreix tots els endpoints: chat completions (compatible OpenAI, streaming, RAG), memòria (store, search), cerca RAG, pujada documents, sessions, bootstrap, health checks, mòduls, backends, i18n. Inclou autenticació (X-API-Key dual-key), rate limiting, marcadors streaming (MODEL_LOADING, RAG_AVG, MEM_SAVE) i configuració."
tags: [api, rest, endpoints, chat, memoria, rag, autenticacio, rate-limiting, streaming, openai-compatible, upload, sessions, bootstrap, health, backends]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Referència API REST — server-nexe 0.8.2

## URL Base

```
http://127.0.0.1:9119
```

Configurable via `personality/server.toml` secció `[core.server]` o `.env` (HOST/PORT). Prioritat: server.toml > .env > per defecte.

Docs API (Swagger): `http://127.0.0.1:9119/docs`

## Autenticació

La majoria d'endpoints requereixen capçalera `X-API-Key`. Valor del fitxer `.env` (`NEXE_PRIMARY_API_KEY`).

**Sistema dual-key:** Dues claus poden estar actives simultàniament per rotació:
- `NEXE_PRIMARY_API_KEY` — sempre activa
- `NEXE_SECONDARY_API_KEY` — període de gràcia per rotació
- Control d'expiració via `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`

**Bootstrap token:** Per setup inicial, es genera un token d'un sol ús a l'arrencada (128-bit, TTL 30min). Mostrat a la sortida de consola.

## Rate Limiting

Configurable per endpoint via `.env`:

| Variable | Per defecte | Aplica a |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/minut | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/minut | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/minut | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/minut | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/minut | Tots els altres |

## Endpoints Core

### Chat

**POST /v1/chat/completions** (requereix API key)

Chat completion compatible OpenAI amb RAG i streaming.

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

- `use_rag`: true per defecte — cerca a 3 col·leccions Qdrant
- `engine`: "auto" (defecte), "ollama", "mlx", "llama_cpp"
- `stream`: true retorna stream SSE amb marcadors
- `max_tokens`: null = defecte del model, màx 32000

**Marcadors streaming** (injectats al stream SSE):
- `[MODEL:nom]` — model actiu
- `[MODEL_LOADING]` / `[MODEL_READY]` — estat càrrega model amb timing
- `[RAG_AVG:0.75]` — puntuació RAG mitjana
- `[RAG_ITEM:0.82|nexe_documentation|ARCHITECTURE.md]` — detall per font
- `[MEM:2]` — fets auto-guardats via MEM_SAVE
- `[THINKING]` / `[/THINKING]` — tokens de raonament (models Ollama com qwen3.5)

### Info Sistema

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/` | GET | No | Info sistema (versió, estat, port) |
| `/health` | GET | No | Health check bàsic |
| `/health/ready` | GET | No | Readiness check (verifica mòduls requerits) |
| `/health/circuits` | GET | No | Estat circuit breakers (Ollama, Qdrant) |
| `/status` | GET | No | Estat temps real: motor actiu, model, mòduls |
| `/api/info` | GET | No | Info API i llista endpoints |
| `/docs` | GET | No | Documentació Swagger/OpenAPI interactiva |

### Mòduls

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/modules` | GET | No | Llista mòduls carregats i les seves APIs |
| `/modules/{nom}/routes` | GET | No | Rutes registrades d'un mòdul específic |

## Endpoints Memòria (prefix: /v1/memory)

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/v1/memory/store` | POST | Sí | Guardar text a una col·lecció |
| `/v1/memory/search` | POST | Sí | Cerca semàntica en una col·lecció |
| `/v1/memory/health` | GET | No | Salut subsistema memòria + col·leccions Qdrant |

## Endpoints RAG (prefix: /v1/rag)

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/v1/rag/search` | POST | Sí | Cerca semàntica al vector store RAG |
| `/v1/rag/add` | POST | Sí | Afegir documents al vector store RAG |
| `/v1/rag/documents/{id}` | DELETE | Sí | Esborrar document del RAG |

## Endpoints Embeddings (prefix: /v1/embeddings)

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Sí | Generar vectors embedding per textos |
| `/v1/embeddings/models` | GET | No | Llistar models d'embeddings disponibles |

## Endpoints Web UI (prefix: /ui)

### Auth i Config

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/ui/auth` | GET | Sí | Verificar validesa API key |
| `/ui/info` | GET | Sí | Info servidor (versió, idioma, features) |
| `/ui/lang` | POST | Sí | Establir idioma servidor (ca/es/en) |
| `/ui/backends` | GET | Sí | Llistar backends amb noms i mides models (GB) |
| `/ui/backend` | POST | Sí | Canviar backend actiu |

### Chat i Memòria

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/ui/chat` | POST | Sí | Streaming SSE chat (amb MEM_SAVE, RAG, thinking tokens) |
| `/ui/memory/save` | POST | Sí | Guardar text a memòria |
| `/ui/memory/recall` | POST | Sí | Recordar de memòria (filtrat per session_id) |

### Sessions

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/ui/session/new` | POST | Sí | Crear nova sessió |
| `/ui/session/{id}` | GET | Sí | Obtenir dades sessió |
| `/ui/session/{id}/history` | GET | Sí | Obtenir historial xat sessió |
| `/ui/session/{id}` | DELETE | Sí | Esborrar sessió |
| `/ui/sessions` | GET | Sí | Llistar totes les sessions |

### Fitxers

| Endpoint | Mètode | Auth | Descripció |
|----------|--------|------|-------------|
| `/ui/upload` | POST | Sí | Pujar document (aïllat per sessió, indexat a user_knowledge) |
| `/ui/files` | GET | Sí | Llistar fitxers pujats |
| `/ui/files/cleanup` | POST | Sí | Netejar fitxers temporals |

**Upload:** Accepta .txt, .md, .pdf. Chunks 1500/200 chars. Metadades sense LLM (instantani). Documents aïllats a la sessió via session_id.

## Compatibilitat OpenAI

`/v1/chat/completions` és parcialment compatible amb el format API d'OpenAI:

**Suportat:** messages array, model, temperature, max_tokens, stream, top_p
**Camps extra:** use_rag (boolean), engine (string)
**No implementat:** /v1/embeddings estàndard (usar /v1/embeddings/encode), /v1/models, /v1/completions (legacy)

Compatible amb eines que usen format API OpenAI: Cursor, Continue, Zed, scripts custom.

## Exemples Ràpids

```bash
# Health check
curl http://127.0.0.1:9119/health

# Chat (sense streaming)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: LA_TEVA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hola"}]}'

# Guardar a memòria
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: LA_TEVA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Em dic Jordi", "collection": "user_knowledge"}'

# Cercar a memòria
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: LA_TEVA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "com em dic", "collection": "user_knowledge", "limit": 3}'
```
