# Contracte API v0.1 — nexe-app ↔ server-nexe

**Data:** 2026-04-19
**Versió:** v0.1 — Fase 0 (mínim viable + auth baseline)
**Estat:** Accepted (auth requirement S10, 2026-04-19)

Contracte entre el frontend de `nexe-app` (Tauri webview) i el backend `server-nexe` (Python FastAPI, port 8000). Defineix els endpoints mínims que han d'existir per a que l'app arranqui, mostri estat i acabi net.

---

## Convencions

- Base URL dev: `http://127.0.0.1:8000`
- Base URL release: `http://127.0.0.1:<dynamic>` (port assignat per Rust si 8000 ocupat)
- Format: JSON (UTF-8)
- Timeouts: health check 30s inicial, shutdown 5s
- **Autenticació: Bearer token OBLIGATORI a TOTES les crides** (S10 F013/F020).

---

## Authentication (v0.1 — S10)

**Zero Trust local:** tot i que tots els endpoints escolten a `127.0.0.1`, qualsevol procés local podria fer-ne una petició. Amb un token compartit entre shell (Rust) i sidecar (Python), només l'app pot autenticar-se.

### Flow

1. **Rust** genera `session_token = uuid::Uuid::new_v4()` a `setup()` — UNA vegada per process launch.
2. **Rust** injecta `NEXE_AUTH_TOKEN=<token>` com a env var al spawn del sidecar (Fase 2).
3. **Sidecar Python** llegeix `os.environ["NEXE_AUTH_TOKEN"]` a l'arrencada i requereix `Authorization: Bearer <token>` a totes les request.
4. **Frontend** obté el token via `invoke('get_auth_token')` i l'envia a cada fetch:
   ```js
   const token = await invoke('get_auth_token');
   fetch('http://127.0.0.1:8000/health', {
     headers: { 'Authorization': `Bearer ${token}` }
   })
   ```

### Middleware FastAPI de referència

```python
# server-nexe/middleware/auth.py
from fastapi import Request, HTTPException
import os, hmac

EXPECTED_TOKEN = os.environ.get("NEXE_AUTH_TOKEN")

async def require_bearer(request: Request, call_next):
    if not EXPECTED_TOKEN:
        raise RuntimeError("NEXE_AUTH_TOKEN env var missing — shell didn't wire us")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    provided = auth.removeprefix("Bearer ")
    # Constant-time compare per evitar timing attacks
    if not hmac.compare_digest(provided, EXPECTED_TOKEN):
        raise HTTPException(401, "invalid token")
    return await call_next(request)
```

### Errors auth

- **401** — `Authorization` absent o mal format
- **403** — Token present però incorrecte

Format estàndard (§Annex):
```json
{"error": {"code": "unauthorized", "message": "missing or invalid bearer token"}}
```

### Excepcions (TBD)

Inicialment TOTS els endpoints requereixen auth. Si es detecten casos on no és viable (ex: WebSocket handshake amb alguns clients), es documentarà aquí com a excepció explícita.

---

---

## Taula resum

| # | Tipus | Path | Ús | Fase |
|---|---|---|---|---|
| 1 | GET | `/health` | Splash screen, "alive check" | 0 |
| 2 | GET | `/v1/meta/compatibility` | Version check app ↔ backend | 0 |
| 3 | POST | `/v1/chat/completions` | Chat OpenAI-compatible | 0 |
| 4 | GET | `/v1/plugins/registry` | Catàleg plugins amb metadata UI | 0 |
| 5 | POST | `/api/v1/system/shutdown` | Graceful shutdown abans de kill | 0 |
| 6 | WS | `/v1/chat/stream` | Streaming tokens LLM | 0 |
| 7 | WS | `/v1/events` | Events lifecycle + `plugin.registry.changed` | 0 |

---

## 1. `GET /health`

Health check per al splash screen i verificació periòdica.

### Request
Sense body.

### Response 200

```json
{
  "status": "ok",
  "version": "1.2.3",
  "uptime_seconds": 42,
  "timestamp": "2026-04-17T22:30:00Z"
}
```

### Errors
- **503** — Backend arrencant (Qdrant inicialitzant, plugins carregant)
  ```json
  {"status": "starting", "message": "plugins loading", "progress": 0.6}
  ```

### Usat per
- **Rust** → splash loop (reintenta cada 500ms fins a 30s)
- **Frontend** → health badge al dashboard

---

## 2. `GET /v1/meta/compatibility`

Check de compatibilitat entre l'app desktop i el backend. Si no són compatibles, l'app mostra error clar i no permet arrencar.

### Request
Parameter query opcional:
- `?app_version=0.1.0` — versió de l'app

### Response 200

```json
{
  "backend_version": "1.2.3",
  "backend_api_version": "v1",
  "min_app_version": "0.1.0",
  "max_app_version": "0.9.x",
  "compatible": true,
  "features": ["plugins.v1", "streaming", "browser-runner"]
}
```

### Response 409 — Incompatible

```json
{
  "compatible": false,
  "reason": "backend too old",
  "backend_version": "0.9.0",
  "required_backend_min": "1.0.0"
}
```

### Usat per
- **Rust** → al spawn del sidecar, check abans d'exposar UI

---

## 3. `POST /v1/chat/completions`

Endpoint OpenAI-compatible per a chat. Ja existeix a server-nexe.

### Request

```json
{
  "model": "qwen2.5-coder:7b",
  "messages": [
    {"role": "system", "content": "Ets NAT..."},
    {"role": "user", "content": "Hola"}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 2048
}
```

### Response 200

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1713391800,
  "model": "qwen2.5-coder:7b",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hola!"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}
}
```

### Errors
- **400** — Model no trobat, messages buits
- **503** — LLM backend (Ollama) offline

### Streaming
Per streaming veure `WS /v1/chat/stream` (§6). L'opció `stream: true` al body HTTP també pot retornar SSE, però el WS és la via canònica per nexe-app.

### Usat per
- **Frontend** → chat component
- **Agent browser-runner** (Fase 3) → planning LLM

---

## 4. `GET /v1/plugins/registry`

Catàleg de plugins registrats al backend amb metadata suficient per construir el dashboard dinàmicament.

### Request
Sense body.

### Response 200

```json
{
  "plugins": [
    {
      "id": "browser-runner",
      "version": "0.1.0",
      "trust": "first-party",
      "enabled": true,
      "ui": {
        "type": "iframe",
        "entry": "ui/index.html",
        "title": "Browser Runner",
        "icon": "browser"
      },
      "requires": {
        "browser": true,
        "microphone": false
      },
      "endpoints": [
        {"method": "POST", "path": "/v1/browser/navigate"},
        {"method": "GET",  "path": "/v1/browser/screenshot"}
      ]
    }
  ],
  "registry_version": 17,
  "last_updated": "2026-04-17T22:30:00Z"
}
```

### Usat per
- **Frontend** → dashboard dinàmic (llista tiles)
- **Rust** → validació capabilities

---

## 5. `POST /api/v1/system/shutdown`

Graceful shutdown del backend. Tauri crida aquest endpoint abans de matar el procés sidecar, perquè Qdrant i SQLite puguin tancar sessions netament.

### Request

```json
{
  "timeout_seconds": 5,
  "reason": "user_quit"
}
```

### Response 202 — Shutdown iniciat

```json
{"status": "shutting_down", "expected_duration_ms": 2000}
```

### Conseqüències
- Qdrant commit final
- SQLite WAL flush
- Plugins notificats (event `system.shutdown`)
- Connexions WebSocket tancades amb codi 1001

### Usat per
- **Rust** → `WindowEvent::CloseRequested` (Quit del tray o ⌘Q)

### Notes
- Si no hi ha resposta en 5s, Rust mata el procés amb SIGTERM → SIGKILL
- Tot i així, Rust mata el procés després de rebre 202 (evita zombis si el backend es queda penjat)

---

## 6. `WS /v1/chat/stream`

WebSocket per streaming de tokens del LLM. Missatges JSON.

### Handshake
```
GET /v1/chat/stream HTTP/1.1
Upgrade: websocket
```

### Client → Server (primer missatge)

```json
{
  "type": "start",
  "payload": {
    "model": "qwen2.5-coder:7b",
    "messages": [...],
    "temperature": 0.7
  }
}
```

### Server → Client (events)

Token chunk:
```json
{"type": "token", "payload": {"delta": "Ho", "index": 0}}
```

Final:
```json
{
  "type": "done",
  "payload": {
    "finish_reason": "stop",
    "usage": {"prompt_tokens": 12, "completion_tokens": 50}
  }
}
```

Error:
```json
{"type": "error", "payload": {"code": "model_not_found", "message": "..."}}
```

Control (cancel):
```json
{"type": "cancel"}
```
*Client → Server. Interromp la generació.*

### Usat per
- **Frontend** → chat streaming UX

---

## 7. `WS /v1/events`

WebSocket d'events del backend cap al frontend/rust. Unidireccional (server → client).

### Handshake
Igual que /v1/chat/stream.

### Events emesos

**`plugin.registry.changed`**
```json
{
  "type": "plugin.registry.changed",
  "payload": {
    "registry_version": 18,
    "changes": [
      {"plugin_id": "rag", "action": "enabled"},
      {"plugin_id": "browser-runner", "action": "updated", "version": "0.2.0"}
    ]
  }
}
```

**`system.status`**
```json
{
  "type": "system.status",
  "payload": {"status": "degraded", "reason": "qdrant disconnected"}
}
```

**`system.shutdown`**
```json
{"type": "system.shutdown", "payload": {"reason": "user_quit"}}
```

*Emès pel servidor just abans de tancar. El client ha de desconnectar-se.*

### Usat per
- **Frontend** → recarregar dashboard quan registry canvia
- **Frontend** → mostrar banner degraded/maintenance
- **Rust** → logging

---

## Endpoints NO al contracte v0

Aquests estan previstos però no són mínim Fase 0:

| Endpoint | Fase | Motiu diferit |
|---|---|---|
| `POST /v1/auth/login` | 1 | Auth no necessari a localhost pur encara |
| `POST /v1/auth/refresh` | 1 | Idem |
| `POST /v1/browser/navigate` | 3 | Browser-runner plugin |
| `POST /v1/browser/action` | 3 | Idem |
| `GET /v1/browser/screenshot` | 3 | Idem |
| `WS /v1/browser/screenshots` | 3 | Streaming preview |
| `GET /v1/plugins/:id/ui/*` | 4 | Assets plugins (o via `plugin://`) |
| `POST /v1/stt/transcribe` | 6 | Speech service (v2) |
| `POST /v1/tts/synthesize` | 6 | Idem |

---

## Annex — Codis d'error estàndard

Tots els endpoints retornen errors amb aquest format:

```json
{
  "error": {
    "code": "snake_case_code",
    "message": "Descripció humana",
    "details": {}
  }
}
```

Codis comuns:
- `backend_starting` (503)
- `model_not_found` (404)
- `plugin_not_enabled` (403)
- `incompatible_versions` (409)
- `rate_limited` (429)
- `internal_error` (500)

---

*v0 — subjecte a evolució. Cada canvi breaking incrementa la versió (v1, v2). Versions paral·leles es poden servir sota `/v0/...` i `/v1/...`.*
