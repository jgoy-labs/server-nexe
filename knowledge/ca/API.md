# === METADATA RAG ===
versio: "2.0"
data: 2026-07-04
id: nexe-api-reference
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "API REST de server-nexe: endpoints /v1/chat/completions (compatible OpenAI), /memory/store, /memory/search, /rag/search, /upload, /sessions. Autenticacio X-API-Key dual-key. Rate limiting per endpoint. Streaming SSE. Port 9119 per defecte. Exemples curl i Python."
tags: [api, rest, endpoints, chat, memory, rag, authentication, rate-limiting, streaming, openai-compatible, upload, sessions, bootstrap, health, backends, encryption, curl, python]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: api
author: "Jordi Goy with AI collaboration"
expires: null
---

# Referencia de l'API REST — server-nexe 1.0.7

## URL base

```
http://127.0.0.1:9119
```

Configurable via `personality/server.toml` seccio `[core.server]` o `.env` (NEXE_HOST/NEXE_PORT). Prioritat: server.toml > .env > valors per defecte.

Docs de l'API (Swagger): `http://127.0.0.1:9119/docs`

## Autenticacio

La majoria d'endpoints requereixen la capcalera `X-API-Key`. Valor del fitxer `.env` (`NEXE_PRIMARY_API_KEY`).

**Sistema dual-key:** Dues claus poden estar actives simultaneament per a rotacio:
- `NEXE_PRIMARY_API_KEY` — sempre activa
- `NEXE_SECONDARY_API_KEY` — periode de gracia per a rotacio
- Seguiment d'expiracio via `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`

**Bootstrap token:** Per a la configuracio inicial, es genera un token d'un sol us a l'arrencada (128 bits, TTL de 30min). Es mostra a la sortida de consola.

## Rate Limiting

El rate limiting s'aplica a **tots els endpoints** — tant API com Web UI.

### Variables configurables via `.env`

| Variable | Per defecte | S'aplica a |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_GLOBAL | 100/minut | Limit global per-IP — **l'unic que s'aplica de veritat** (`core/dependencies.py` + middleware SlowAPI) |
| NEXE_RATE_LIMIT_PUBLIC | (llegida pero sense us) | **Config morta** — es llegeix a `DEFAULT_RATE_LIMITS` pero cap limiter la consumeix (limiters avancats eliminats, MC-123/124); sense efecte en runtime |
| NEXE_RATE_LIMIT_AUTHENTICATED | (llegida pero sense us) | **Config morta** — sense efecte en runtime |
| NEXE_RATE_LIMIT_ADMIN | (llegida pero sense us) | **Config morta** — sense efecte en runtime |
| NEXE_RATE_LIMIT_HEALTH | (llegida pero sense us) | **Config morta** — sense efecte en runtime |

**Nota:** Els límits per endpoint (chat 20/min, memory 30/60 per min, upload 5/min...) estan **hardcoded al codi** via `@limiter.limit` (p. ex. `core/endpoints/chat.py`, `routes_files.py`) i **no** són configurables per `.env`.

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
| PATCH /ui/session/{id} | 10/minut |
| PATCH /ui/session/{id}/thinking | 10/minut |

## Endpoints principals

### Xat

**POST /v1/chat/completions** (requereix clau API, rate limit: 20/min)

Chat completion compatible amb OpenAI amb suport RAG i streaming.

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

- `model`: null per defecte (no "auto"). Per a **Ollama** un valor passat selecciona el model amb fallback per nom parcial (p. ex. `llama3` → `llama3.1:8b`); 404 només si cap model de chat hi encaixa. Per a **MLX / llama.cpp** el valor s'**ignora** — corren l'únic model configurat — i la resposta reporta el nom del model realment carregat, mai el demanat
- `use_rag`: true per defecte — cerca en 3 col·leccions Qdrant
- `engine`: "auto" (per defecte), "ollama", "mlx", "llama_cpp", o "api" (un proveïdor extern: opt-in explícit, vegeu a sota)
- `stream`: true retorna flux SSE amb marcadors
- `temperature`: 0.0-2.0 (per defecte 0.7)
- `top_p`: 0 < top_p ≤ 1 (null per defecte) — nucleus sampling; null deixa que cada motor usi el seu propi default (≈ 0.9)
- `max_tokens`: null = utilitza el per defecte del model, maxim 32000
- `reasoning_effort` (o `reasoning: {"effort": ...}`): `"none"` o absent = el model no raona (per defecte); qualsevol altre valor = raona, i el raonament torna apart de la resposta, com a `reasoning` (`message.reasoning`, o `delta.reasoning` en streaming). Encara no hi ha nivells: qualsevol valor que no sigui `"none"` vol dir encès.

**Marcadors de streaming** (injectats al flux SSE, parsejats per la UI):
- `[MODEL:name]` — model actiu
- `[MODEL_LOADING]` / `[MODEL_READY]` — estat de carrega del model amb temporitzacio
- `[RAG_AVG:0.75]` — puntuacio mitjana de rellevancia RAG
- `[RAG_ITEM:nexe_documentation|0.82]` — detall per font (col·leccio primer, despres puntuacio; nomes 2 camps)
- `[MEM:2]` — nombre de fets auto-guardats via MEM_SAVE
- `[COMPACT:N]` — indicador de compactacio de context
- `<think>…</think>` — el raonament del model, nomes al stream de la UI web (es mostra al bloc desplegable de pensar); `/v1` l'envia com a `reasoning`
- `[DOC_TRUNCATED:XX%]` — percentatge de document descartat per limit de context (nou 2026-04-02)

**Final del flux — per que s'ha aturat la resposta** (nou 2026-08-31):

L'ultim chunk abans de `[DONE]` porta `finish_reason`, com al cami no-streaming: `"stop"` si la
resposta ha acabat sola i `"length"` si ha quedat tallada. Quan el motor no ho reporta es degrada
a `"stop"` — una absencia no es un truncament.

Una resposta tallada pot ser-ho de dues maneres que demanen reaccions oposades, i el chunk les
distingeix amb `x_nexe_truncation` (a l'arrel del chunk, extensio propia, no OpenAI):

- `"ceiling"` — el model ha topat amb el sostre de tokens: **falta la cua**. Demanar la
  continuacio i enganxar-la al final es correcte.
- `"overflow"` — s'han perdut tokens **del mig** mentre la generacio continuava (cua SSE plena),
  i el final que ha arribat es el natural. **No demanis la continuacio**: afegiria text nou sobre
  un forat intern i el resultat semblaria coherent sense ser-ho. Aquesta resposta no es pot
  reparar continuant-la.

El camp **no hi es** quan no s'ha tallat res. Si passen les dues coses alhora mana `"overflow"`.

**Bloc `[IMATGE ADJUNTA]`:** Quan un missatge inclou una imatge (backend VLM), l'endpoint de xat injecta un bloc `[IMATGE ADJUNTA]` que **prioritza la imatge sobre el context RAG**. El model processa la imatge directament i el RAG queda relegat a context secundari, evitant que documents recuperats distreguin la descripcio visual.

### Traça d'un torn (què ha fet un torn recent)

Cada resposta de xat porta l'id del torn a la capçalera **`X-Nexe-Turn-Id`** (en flux o JSON; el cos JSON també conserva `turn_id`).
`GET /v1/turns/{turn_id}/trace` (cal la clau d'API) torna els passos d'aquell torn: el resultat, la durada, el motor, el codi
d'error i el motiu de cancel·lació de cada pas, les crides al LLM que ha fet (`outcome`: `ok` o `cancelled`), i `final` quan no
queda res pendent (les feines de després, `compact` i `describe_image`, s'afegeixen al mateix registre quan acaben). Un torn
en curs ja hi és, amb els passos que porta fets. Es guarda en memòria per als **últims 256 torns** del servidor que corre; `404`
si l'id és desconegut o més antic. Mai conté el que has escrit ni el que ha contestat el model. El registre durador és el log:
una línia `turn.trace` quan es tanca la connexió i una de curta, `turn.step`, per cada feina de després.

Cada crida al LLM de la traça porta `tokens_in`, `tokens_out` i `cached_in` (els tokens que el **motor** diu que ha gastat, i els de la caché del prefix que ha reaprofitat). El que un motor no diu és `null`, **mai `0`**: MLX diu entrada, sortida i caché; llama.cpp, Ollama i les APIs (DeepSeek, OpenAI) diuen entrada i sortida. El peu del missatge a la web mostra aquest recompte tal qual; si el motor no el dona, mostra una estimació amb un `~` davant. `/metrics` suma el total a `core_turn_tokens_total{engine,kind}` (`kind`: `in`, `out`, `cached`).

`/metrics` compta els motors igual a les dues portes: `core_chat_engine_requests_total{engine,status}` i
`core_chat_engine_duration_seconds{engine}` (temps fins al primer esdeveniment del motor, una fila per motor demanat, el
re-prompt inclòs), més `core_turn_steps_total{step,outcome}` i `core_turn_step_duration_seconds{step}`.

### Proveïdors d'API externs (opt-in)

`"engine": "api"` envia la petició a un proveïdor extern compatible amb OpenAI (DeepSeek o OpenAI) en lloc d'un motor local. És un **opt-in explícit** i mai un recanvi: l'API només respon quan la demanes pel nom. Un motor local que falla no el respon l'API, i un proveïdor que falla no el respon un motor local. `"engine": "auto"`, o un `NEXE_MODEL_ENGINE=api` oblidat a l'entorn, no arriba mai al núvol.

El que surt de la màquina: la conversa, els documents recuperats i la memòria d'aquella petició, més els passos interns que corren al mateix motor (compactar la conversa, descriure una imatge, el re-prompt de memòria). Res més, i mai la clau.

Una petició amb `"engine": "api"` es refusa si no es compleix **tot** això:

1. `api_module` és a `NEXE_APPROVED_MODULES` (si no, `503`: el motor API no està carregat; les comprovacions de sota es fan primer).
2. L'interruptor global és encès: `NEXE_ALLOW_CLOUD_ENGINES=1` (apagat per defecte; és l'interruptor «Permet motors al núvol» de la web, i es torna a llegir a cada petició). Apagat: `403` `cloud_engines_disabled`.
3. `model` és un model d'un proveïdor amb la clau configurada al servidor: `deepseek-chat` o `deepseek-reasoner` (`DEEPSEEK_API_KEY`), o `gpt-*` (`OPENAI_API_KEY`). La clau viu només al `.env` del servidor: el client no l'envia mai i res no la mostra. Sense model, o un model local: `400` `cloud_model_not_allowed`. Sense clau: `400` `cloud_provider_not_configured`.
4. La petició porta el seu propi consentiment: `"nexe_cloud_consent": "<clau del proveïdor>"` (`"deepseek"` o `"openai"`). `/v1` no té sessió on recordar-lo, així que es demana a **cada** petició, per a un sol proveïdor. Si falta, o és el d'un altre proveïdor: `403` `cloud_consent_required`.

```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: LA_TEVA_CLAU" -H "Content-Type: application/json" \
  -d '{"engine": "api", "model": "deepseek-chat", "nexe_cloud_consent": "deepseek",
       "messages": [{"role": "user", "content": "Hola"}]}'
```

Amb l'SDK d'OpenAI: `extra_body={"engine": "api", "nexe_cloud_consent": "deepseek"}`. El cos d'un refús és `{"code", "message", "provider"}`, mai una clau. Una petició que la porta refusa (els `400` i `403` d'aquí a dalt) no desa res i no envia res.

- La resposta porta `X-Nexe-Engine: api` (`nexe_engine` en un cos JSON), `model` és el que has dit, i no hi ha capçalera de recanvi.
- `temperature` i `max_tokens` **no** es reenvien (alguns models dels proveïdors els renomenen o els refusen): valen els valors per defecte del proveïdor. Sí que van `top_p` i les imatges (per a un model que sap llegir-les: `gpt-4o`, `gpt-4.1`, `gpt-5`). `reasoning_effort` no canvia res del que s'envia (que un model del proveïdor raoni és la seva naturalesa): només decideix si el raonament que torna es retorna, com a `reasoning`. `resume` (Continua) es refusa amb `400`: un proveïdor no pot reprendre a mig frase.
- Errors: una clau refusada (401/403) és `502`; un saldo (402), un límit de peticions (429), qualsevol 5xx o una petició que el proveïdor rebutja és `503`; un temps d'espera és `504` (`NEXE_API_TIMEOUT`, segons entre dos trossos, 120 per defecte). El text diu el proveïdor i l'estat HTTP, mai la clau ni el cos del proveïdor.
- Té una porta de concurrència pròpia (`NEXE_CLOUD_ENGINE_SLOTS`, 4 per defecte): una resposta del núvol no ocupa mai el lloc dels motors locals. Un límit de temps, o un client que se'n va, atura la lectura HTTP.
- La línia de traça del torn, i un missatge de la web desat d'un proveïdor, porten `left_machine: true`.

Admin: `GET /admin/providers/status` (quines claus hi ha, mai la clau) i `POST /admin/providers/{provider}/check` (una petició mínima). CLI: `nexe providers status` i `nexe providers check <proveïdor>`.

### Informacio del sistema

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/` | GET | No | Informacio del sistema (versio, estat, port) |
| `/health` | GET | No | Health check basic |
| `/health/ready` | GET | No | Comprovacio de disponibilitat. Nomes els subsistemes **critics** (autenticacio i interficie) fan que respongui `unhealthy`; si el que falla o falta es degradable (RAG, embeddings, un motor) respon `degraded` i la interficie carrega igualment, perque l'usuari hi pugui entrar a arreglar-ho. Un modul degradable que informa que no esta be **es mostra, no bloqueja**: la interficie ho diu a l'indicador d'estat i al costat d'on s'escriu |
| `/health/circuits` | GET | Sí (X-API-Key) | Estat dels circuit breakers (Ollama, Qdrant) |
| `/status` | GET | Sí (X-API-Key) | Estat en temps real: `configured_engine` (intenció), `resolved_engine` (el motor que el chat correrà efectivament, node-aware), `model` (el default configurat — MLX/llama.cpp reporten el model realment carregat només a la resposta de chat), moduls carregats, `operational_state` (`normal`/`degraded`/`limited`/`refused`) i `impaired_subsystems` (que no funciona). La interficie ho consulta per avisar l'usuari quan un subsistema no ha arrencat, en comptes de deixar-lo xatejar creient que la memoria funciona |
| `/api/info` | GET | No | Informacio de l'API i un subconjunt representatiu d'endpoints publics (no exhaustiu) |
| `/docs` | GET | No | Documentacio interactiva Swagger/OpenAPI |
| `/admin/system/restart` | POST | Sí (X-API-Key) | Reinicia el servidor (l'usa la UI despres de canvis de config) |
| `/admin/system/shutdown` | POST | Sí (X-API-Key) | Atura el servidor |
| `/admin/system/status` | GET | Sí (X-API-Key) | Estat del sistema (admin) |
| `/admin/system/health` | GET | No | Health check public que la UI consulta despres d'un reinici |

### Moduls

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/modules` | GET | Sí (X-API-Key) | Llista de moduls carregats i les seves APIs |
| `/modules/{name}/routes` | GET | Sí (X-API-Key) | Rutes registrades per un modul especific |

### Bootstrap

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/api/bootstrap` | POST | Token | Inicialitzar sessio amb bootstrap token |
| `/api/regenerate-bootstrap` | POST | localhost | Regenerar bootstrap token expirat |
| `/api/bootstrap/info` | GET | No | Estat del sistema de bootstrap |

## Endpoints de memoria (prefix: /v1/memory)

| Endpoint | Metode | Auth | Rate limit | Descripcio |
|----------|--------|------|------------|-------------|
| `/v1/memory/store` | POST | Si | **30/min** (hardcoded, `memory/memory/api/v1.py`) | Guardar text a una col·leccio |
| `/v1/memory/search` | POST | Si | **60/min** (hardcoded, `memory/memory/api/v1.py`) | Cerca semantica en una col·leccio |
| `/v1/memory/health` | GET | Si | per defecte | Salut del subsistema de memoria + col·leccions Qdrant |

**Peticio de guardat:**
```json
{
  "content": "Information to store",
  "collection": "user_knowledge",
  "metadata": {"source": "api", "tags": ["example"]}
}
```

**Peticio de cerca:**
```json
{
  "query": "search query",
  "collection": "user_knowledge",
  "limit": 5
}
```

## Endpoints RAG retirats (/v1/rag, /v1/documents)

`/v1/rag/search`, `/v1/rag/add`, `DELETE /v1/rag/documents/{id}` i `GET /v1/documents/` eren stubs que retornaven 501; s'han eliminat i ara responen **404**. La recuperacio es fa dins el xat (`use_rag` a `/v1/chat/completions`); una cerca semantica directa en una col·leccio es `POST /v1/memory/search`.

## Endpoints d'embeddings (prefix: /v1/embeddings)

> ⚠️ **NO IMPLEMENTAT (stub):** aquests endpoints retornen HTTP 501. Reservats per a una versió futura.

| Endpoint | Metode | Auth | Descripcio |
|----------|--------|------|-------------|
| `/v1/embeddings/encode` | POST | Si | Generar vectors d'embedding per a textos (stub, 501) |
| `/v1/embeddings/models` | GET | Si | Llistar models d'embedding disponibles (stub, 501) |

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
| `/ui/session/{id}` | PATCH | Si | 10/min | Renombrar sessio (nou 2026-04-01) |
| `/ui/session/{id}/thinking` | PATCH | Si | 10/min | Commutador del mode thinking (reasoning tokens) per sessio (nou v0.9.9) |
| `/ui/session/{id}/clear-document` | POST | Si | per defecte | Netejar document adjunt de la sessio (nou 2026-04-02) |
| `/ui/sessions` | GET | Si | per defecte | Llistar totes les sessions |

**Thinking toggle** (`PATCH /ui/session/{id}/thinking`): permet activar o desactivar l'emissio de reasoning tokens per a una sessio concreta. Nomes disponible per a famílies de models compatibles (`THINKING_CAPABLE`: qwen3.5, qwen3, qwq, deepseek-r1, gemma3/4, llama4, gpt-oss). Per defecte està desactivat. Si el model no suporta thinking, l'endpoint retorna 400 amb missatge explicatiu i la UI ofereix retry automatic sense thinking.

### Fitxers

| Endpoint | Metode | Auth | Rate limit | Descripcio |
|----------|--------|------|-----------|-------------|
| `/ui/upload` | POST | Si | 5/min | Pujar document (valida nom de fitxer, aillat per sessio) |
| `/ui/files` | GET | Si | per defecte | Llistar fitxers pujats |
| `/ui/files/cleanup` | POST | Si | 5/min | Netejar fitxers temporals |

**Pujada:** Accepta PDF, .docx, .xlsx, .pptx, .epub, text, codi font i dades (.csv, .json, .xml, .yaml, .toml) — veure RAG.md. Chunking dinamic segons mida del document (800/1000/1200/1500 chars). Validacio de magic bytes (SEC-004). Metadades generades sense LLM (instantani). Documents aillats a la sessio de pujada via session_id.

## Comandes CLI d'encriptacio

Aquestes son comandes CLI (no endpoints HTTP):

| Comanda | Descripcio |
|---------|-------------|
| `./nexe encryption status` | Mostrar estat d'encriptacio de tots els components d'emmagatzematge |
| `./nexe encryption encrypt-all` | Migrar totes les dades existents a format encriptat |
| `./nexe encryption export-key` | Exportar clau mestra (hex o base64, per a copia de seguretat) |

## Compatibilitat amb OpenAI

`/v1/chat/completions` es parcialment compatible amb el format de l'API d'OpenAI:

**Suportat:** array de messages, model, temperature, max_tokens, stream, top_p, reasoning_effort (el raonament torna com a `reasoning`)
**Camps extra:** use_rag (boolean), engine (string)
**No implementat:** /v1/embeddings/encode i /v1/embeddings/models (stubs, retornen 501), /v1/models, /v1/completions (legacy)

Compatible amb eines que utilitzen el format de l'API d'OpenAI: Cursor, Continue, Zed, scripts personalitzats.

## Configuracio

| Parametre | Ubicacio | Proposit |
|---------|----------|---------|
| Host/Port | server.toml `[core.server]` | Adreca de vinculacio del servidor |
| Claus API | .env | NEXE_PRIMARY_API_KEY, NEXE_SECONDARY_API_KEY |
| Rate limits | .env | NEXE_RATE_LIMIT_GLOBAL (i variables del plugin security); límits per endpoint al codi |
| Timeout | .env | NEXE_OLLAMA_STREAM_TIMEOUT (per defecte 300, segons) |
| Origens CORS | server.toml `[core.server]` | Origens permesos |
| Encriptacio | .env | NEXE_ENCRYPTION_ENABLED (per defecte auto) |

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
  -d '{"content": "My name is Jordi", "collection": "user_knowledge"}'

# Cercar a memoria
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "what is my name", "collection": "user_knowledge", "limit": 3}'
```
