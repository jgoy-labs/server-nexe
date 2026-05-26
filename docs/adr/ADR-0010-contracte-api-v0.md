# ADR-0010: Contracte API v0 — 7 endpoints mínims

**Data:** 2026-04-18
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

nexe-app i server-nexe es comuniquen per HTTP/WS (veure ADR-0005 IPC híbrid). Cal formalitzar el contracte v0 dels endpoints mínims perquè l'scaffold de Fase 1 es pugui fer contra una superfície estable i acordada.

## Decisió

**7 endpoints mínims (5 HTTP + 2 WS)** documentats al detall a `docs/api-contract-v0.md`:

1. `GET /health` — splash screen, alive check
2. `GET /v1/meta/compatibility` — version app ↔ backend
3. `POST /v1/chat/completions` — chat OpenAI-compatible (existent)
4. `GET /v1/plugins/registry` — catàleg plugins amb metadata UI
5. `POST /api/v1/system/shutdown` — graceful shutdown abans de kill
6. `WS /v1/chat/stream` — streaming tokens LLM
7. `WS /v1/events` — events lifecycle + `plugin.registry.changed`

Sense auth a v0 (localhost-only). Auth afegida a Fase 1.

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| API extensa a v0 (browser, auth, STT/TTS) | Sobredimensionada per MVP |
| API minimalista (sols `/health` + chat) | Insuficient per lifecycle + plugins Fase 4 |
| GraphQL en comptes de REST | Compatibilitat OpenAI bé val més |

## Conseqüències

**Positives:**
- Contracte explícit → implementacions paral·leles de Rust/UI independents
- JSON schemas escrits → tests de regressió possibles
- Endpoints diferits documentats al mateix doc

**Negatives / riscos:**
- Canvis breaking incrementen versió (`/v0/...` vs `/v1/...`); cal mantenir compatibilitat mentre UI s'actualitzi
- Events WS tipats només per string; schema binding formal (ex: TypeScript types) pendent

**Mitigacions:**
- Afegir tests de contracte als CI un cop server-nexe implementi els 7 endpoints
- Generar types TypeScript des del JSON schema a Fase 1

## Referències

- [docs/api-contract-v0.md](../api-contract-v0.md)
- [ADR-0005 IPC híbrid](ADR-0005-ipc-hibrid.md)
- Consultoria 2026-04-17 (finding addicional: `backend.ready` event al WS `/v1/events`)
