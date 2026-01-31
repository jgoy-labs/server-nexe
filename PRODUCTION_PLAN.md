# Pla de Posada en Produccio - Server Nexe 0.8

Data: 2026-01-31
Projecte: /Users/jgoy/NatSytem/Projectes/server-nexe/
Objectiu: deixar el sistema llest per produccio amb passos clars, riscos i checklist.

## 1) Bloquejadors (fix abans de prod)

1. Bug /api/bootstrap/info (NameError timezone)
2. optional_api_key no accepta clau secundaria (rotacio)
3. bootstrap: request.client None + timestamps UTC inconsistents
4. Auto-start de serveis externs (Qdrant/Ollama) sense flag explicita en prod
5. CORS pot fallar si cors_origins es buit (config obligatoria)

## 2) Decisions d'infra

- Arquitectura: [bare metal / VM / container]
- Reverse proxy: [nginx / traefik / none]
- TLS: [terminacio TLS al proxy / al server]
- Domini: [ex. api.jgoy.net]
- Persistencia: storage/ (logs + DB tokens + qdrant data)

## 3) Variables d'entorn (minim prod)

- NEXE_ENV=production
- NEXE_PRIMARY_API_KEY=... (obligatoria)
- NEXE_PRIMARY_KEY_EXPIRES=... (recomanat)
- NEXE_SECONDARY_API_KEY=... (opcional)
- NEXE_SECONDARY_KEY_EXPIRES=... (opcional)
- NEXE_CSRF_SECRET=... (obligatoria)
- NEXE_BOOTSTRAP_DISPLAY=false

### Flags de serveis externs (recomanat prod)
- NEXE_AUTOSTART_QDRANT=false
- NEXE_AUTOSTART_OLLAMA=false
- QDRANT_HOST=... / QDRANT_PORT=...
- OLLAMA_HOST=... (si s'utilitza)

## 4) server.toml (minim)

core.server:
  host = "127.0.0.1" (si hi ha reverse proxy)
  port = 9119
  cors_origins = ["https://<domini-ui>"]
  csrf_cookie_secure = true
  csrf_cookie_samesite = "Strict" (o "Lax" si UI en domini diferent)
  workers = 1 (si no es replica cache/rate limit)

## 5) Reverse proxy (si aplica)

- Afegir headers: X-Forwarded-Proto, X-Forwarded-For
- TLS actiu i HSTS si cal
- Timeouts ajustats per streaming (chat)
- Limitar mides request si cal (ja hi ha RequestSizeLimiter)

## 6) Observabilitat

- Logs a storage/logs/ amb rotacio
- Prometheus metrics (si activat)
- Alertes: /health, 5xx, latencia, CPU/RAM

## 7) Seguretat

- CSRF actiu (starlette-csrf instal·lat)
- API keys rotacio amb expiracio
- CORS sense wildcards
- CSP revisat si UI en host diferent

## 8) Smoke tests abans de go-live

- GET /health -> 200
- GET /v1/health -> 200
- Auth: endpoint protegit amb X-API-Key
- Chat completions /v1/chat/completions (stream i no-stream)
- Memory store/search (si habilitat)
- UI carrega i opera (si UI activa)

## 9) Rollback

- Snapshot de storage/
- Backup de .env i server.toml
- Documentar com reiniciar supervisor/servei

## 10) Pendents de millora (post-prod)

- Tests per bootstrap info + optional_api_key secundaria
- Cancelacio del cleanup task de rate limits a shutdown
- Flags de auto-start i auto-ingest mes robusts
- Consistencia de versions publicades a /system/health i /v1

