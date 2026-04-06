# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-api-reference

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "API REST de server-nexe: endpoints /v1/chat/completions (compatible OpenAI), /memory/store, /memory/search, /rag/search, /upload, /sessions. Autenticacio X-API-Key dual-key. Rate limiting per endpoint. Streaming SSE. Port 9119 per defecte. Exemples curl i Python."
tags: [api, rest, endpoints, chat, memory, rag, authentication, rate-limiting, streaming, openai-compatible, upload, sessions, bootstrap, health, backends, encryption, curl, python]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: api
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Referencia de l'API REST — server-nexe 0.9.0 pre-release

## URL base

```
http://127.0.0.1:9119
```

Configurable via `personality/server.toml` seccio `[core.server]` o `.env` (HOST/PORT). Prioritat: server.toml > .env > valors per defecte.

Docs de l'API (Swagger): `http://127.0.0.1:9119/docs`

## Autenticacio

La majoria d'endpoints requereixen la capcalera `X-API-Key`. Valor del fitxer `.env` (`NEXE_PRIMARY_API_KEY`).

**Sistema dual-key:** Dues claus poden estar actives simultaneament per a rotacio:
- `NEXE_PRIMARY_API_KEY` — sempre activa
- `NEXE_SECONDARY_API_KEY` — periode de gracia per a rotacio
- Seguiment d'expiracio via `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`

**Bootstrap token:** Per a la configuracio inicial, es genera un token d'un sol us a l'arrencada (256 bits, TTL de 30min). Es mostra a la sortida de consola.

## Rate Limiting

El rate limiting s'aplica a **tots els endpoints** — tant API com Web UI.

### Endpoints de l'API (configurables via `.env`)

| Variable | Per defecte | S'aplica a |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/minut | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/minut | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/minut | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/minut | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/minut | Resta d'endpoints |

### Endpoints de la Web UI (per endpoint)

| Endpoint | Limit |
|----------|-----------|
| POST /ui/chat | 20/minut |
| POST /ui/memory/save | 10/minut |
| POST /ui/memory/recall | 30/minut |
| POST /ui/upload | 5/minut |
| POST /ui/files/cleanup | 5/minut |
| GET /ui/session/{id} | 30/minut |
| DELETE /ui/session/{id} | 10/minut |

## Endpoints principals

### Xat

**POST /v1/chat/completions** (requereix clau API, rate limit: 60/min)

Chat completion compatible amb OpenAI amb suport RAG i streaming.

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

- `use_rag`: true per defecte — cerca en 3 col·leccions Qdrant
- `engine`: "auto" (per defecte), "ollama", "mlx", "llama_cpp"
- `stream`: true retorna flux SSE amb marcadors
- `temperature`: 0.0-2.0 (per defecte 0.7)
- `max_tokens`: null = utilitza el per defecte del model, maxim 32000

**Marcadors de streaming** (injectats al flux SSE, parsejats per la UI):
- `[MODEL:name]` — model actiu
- `[MODEL_LOADING]` / `[MODEL_READY]` — estat de carrega del model amb temporitzacio
- `[RAG_AVG:0.75]` — puntuacio mitjana de rellevancia RAG
- `[RAG_ITEM:0.82|nexe_documentation|ARCHITECTURE.md]` — detall per font
- `[MEM:2]` — nombre de fets auto-guardats via MEM_SAVE
- `[COMPACT:N]` — indicador de compactacio de context
- `[THINKING]` / `[/THINKING]` — thinking tokens (models Ollama com qwen3.5)
- `[DOC_TRUNCATED:XX%]` — percentatge de document descartat per limit de context (nou 2026-04-02)

### Informacio del sistema

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/` | GET | No | Informacio del sistema (versio, estat, port) |
| `/health` | GET | No | Health check basic |
| `/health/ready` | GET | No | Comprovacio de disponibilitat (verifica moduls requerits) |
| `/health/circuits` | GET | No | Estat dels circuit breakers (Ollama, Qdrant) |
| `/status` | GET | No | Estat en temps real: motor actiu, model, moduls carregats |
| `/api/info` | GET | No | Informacio de l'API i llista d'endpoints disponibles |
| `/docs` | GET | No | Documentacio interactiva Swagger/OpenAPI |

### Moduls

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/modules` | GET | No | Llista de moduls carregats i les seves APIs |
| `/modules/{name}/routes` | GET | No | Rutes registrades per un modul especific |

### Bootstrap

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/api/bootstrap` | POST | Token | Inicialitzar sessio amb bootstrap token |
| `/api/regenerate-bootstrap` | POST | localhost | Regenerar bootstrap token expirat |
| `/api/bootstrap/info` | GET | No | Estat del sistema de bootstrap |

## Endpoints de memoria (prefix: /v1/memory)

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/v1/memory/store` | POST | Si | Guardar text a una col·leccio |
| `/v1/memory/search` | POST | Si | Cerca semantica en una col·leccio |
| `/v1/memory/health` | GET | No | Salut del subsistema de memoria + col·leccions Qdrant |

**Peticio de guardat:**
```json
{
  "text": "Information to store",
  "collection": "user_knowledge",
  "metadata": {"source": "api", "tags": ["example"]}
}
```

**Peticio de cerca:**
```json
{
  "query": "search query",
  "collection": "user_knowledge",
  "limit": 5,
  "threshold": 0.35
}
```

## Endpoints RAG (prefix: /v1/rag)

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/v1/rag/search` | POST | Si | Cerca semantica al magatzem de vectors RAG |
| `/v1/rag/add` | POST | Si | Afegir documents al magatzem de vectors RAG |
| `/v1/rag/documents/{id}` | DELETE | Si | Esborrar document del RAG |

## Endpoints d'embeddings (prefix: /v1/embeddings)

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Si | Generar vectors d'embedding per a textos |
| `/v1/embeddings/models` | GET | No | Llistar models d'embedding disponibles |

## Endpoints de la Web UI (prefix: /ui)

Aquests endpoints serveixen la interficie web i els utilitza el frontend JavaScript. Tots tenen validacio d'input via `validate_string_input()`.

### Autenticacio i configuracio

| Endpoint | Metode | Auth | Rate limit | Descripcio |
|----------|--------|------|-----------|-------------|
| `/ui/auth` | GET | Si | per defecte | Verificar validesa de la clau API |
| `/ui/info` | GET | Si | per defecte | Informacio del servidor (versio, idioma, funcionalitats) |
| `/ui/lang` | POST | Si | per defecte | Establir idioma del servidor (ca/es/en) |
| `/ui/backends` | GET | Si | per defecte | Llistar backends amb noms i mides de models (GB) |
| `/ui/backend` | POST | Si | per defecte | Canviar backend actiu |
| `/ui/health` | GET | No | per defecte | Salut del modul Web UI |

### Xat i memoria

| Endpoint | Metode | Auth | Rate limit | Descripcio |
|----------|--------|------|-----------|-------------|
| `/ui/chat` | POST | Si | 20/min | Xat amb streaming SSE (MEM_SAVE, RAG, thinking tokens) |
| `/ui/memory/save` | POST | Si | 10/min | Guardar text a memoria (valida contingut, session_id) |
| `/ui/memory/recall` | POST | Si | 30/min | Recuperar de memoria (valida query, session_id) |

### Sessions

| Endpoint | Metode | Auth | Rate limit | Descripcio |
|----------|--------|------|-----------|-------------|
| `/ui/session/new` | POST | Si | per defecte | Crear nova sessio |
| `/ui/session/{id}` | GET | Si | 30/min | Obtenir dades de la sessio (valida session_id) |
| `/ui/session/{id}/history` | GET | Si | 30/min | Obtenir historial de xat de la sessio |
| `/ui/session/{id}` | DELETE | Si | 10/min | Esborrar sessio |
| `/ui/session/{id}` | PATCH | Si | per defecte | Renombrar sessio (nou 2026-04-01) |
| `/ui/session/{id}/clear-document` | POST | Si | per defecte | Netejar document adjunt de la sessio (nou 2026-04-02) |
| `/ui/sessions` | GET | Si | per defecte | Llistar totes les sessions |

### Fitxers

| Endpoint | Metode | Auth | Rate limit | Descripcio |
|----------|--------|------|-----------|-------------|
| `/ui/upload` | POST | Si | 5/min | Pujar document (valida nom de fitxer, aillat per sessio) |
| `/ui/files` | GET | Si | per defecte | Llistar fitxers pujats |
| `/ui/files/cleanup` | POST | Si | 5/min | Netejar fitxers temporals |

**Pujada:** Accepta .txt, .md, .pdf. Chunking dinamic segons mida del document (800/1000/1200/1500 chars). Validacio de magic bytes (SEC-004). Metadades generades sense LLM (instantani). Documents aillats a la sessio de pujada via session_id.

## Comandes CLI d'encriptacio

Aquestes son comandes CLI (no endpoints HTTP):

| Comanda | Descripcio |
|---------|-------------|
| `./nexe encryption status` | Mostrar estat d'encriptacio de tots els components d'emmagatzematge |
| `./nexe encryption encrypt-all` | Migrar totes les dades existents a format encriptat |
| `./nexe encryption export-key` | Exportar clau mestra (hex o base64, per a copia de seguretat) |

## Compatibilitat amb OpenAI

`/v1/chat/completions` es parcialment compatible amb el format de l'API d'OpenAI:

**Suportat:** array de messages, model, temperature, max_tokens, stream, top_p
**Camps extra:** use_rag (boolean), engine (string)
**No implementat:** /v1/embeddings (utilitza /v1/embeddings/encode en el seu lloc), /v1/models, /v1/completions (legacy)

Compatible amb eines que utilitzen el format de l'API d'OpenAI: Cursor, Continue, Zed, scripts personalitzats.

## Configuracio

| Parametre | Ubicacio | Proposit |
|---------|----------|---------|
| Host/Port | server.toml `[core.server]` | Adreca de vinculacio del servidor |
| Claus API | .env | NEXE_PRIMARY_API_KEY, NEXE_SECONDARY_API_KEY |
| Rate limits | .env | Variables NEXE_RATE_LIMIT_* |
| Timeout | .env | NEXE_DEFAULT_MAX_TOKENS (per defecte 4096) |
| Origens CORS | server.toml `[core.server]` | Origens permesos |
| Encriptacio | .env | NEXE_ENCRYPTION_ENABLED (per defecte false) |

## Exemples rapids

```bash
# Health check
curl http://127.0.0.1:9119/health

# Xat (sense streaming)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

# Guardar a memoria
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is Jordi", "collection": "user_knowledge"}'

# Cercar a memoria
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "what is my name", "collection": "user_knowledge", "limit": 3}'
```
