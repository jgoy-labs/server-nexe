# ADR-0005: IPC híbrid (HTTP/WS + Tauri Commands)

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

El frontend (webview) ha de comunicar-se amb dos backends:
1. **server-nexe** (Python, port 8000) — dades IA, plugins, memòria, auth
2. **Tauri core** (Rust) — funcions natives (file dialogs, system tray, notificacions, secrets)

Cal decidir un model IPC coherent.

## Decisió

**IPC híbrid segons el canal:**

| Canal | Ús |
|---|---|
| **HTTP REST** | CRUD, auth, estat plugins, health check |
| **WebSocket** | Chat streaming, events agent, preview screenshots del browser-runner |
| **Tauri Commands** (Rust) | File dialogs, notificacions, system tray, Stronghold (secrets), spawn/shutdown |
| **Tauri Events** | Backend → Frontend (lifecycle, errors, `plugin.registry.changed`) |

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **Només HTTP/WS** (tot via server-nexe) | Secrets Stronghold i lifecycle han de viure a Rust per seguretat |
| **Només Tauri Commands** (Rust pipeline a Python) | Duplicaria l'API de server-nexe a Rust, trencaria modularitat |
| **gRPC** | Overkill per aquest abast, complica build |
| **Un sol socket Unix** | Menys estàndard, debugging difícil |

## Conseqüències

**Positives:**
- Separació clara per tipus de recurs (dades ↔ natiu)
- Reaprofita l'API REST existent de server-nexe (OpenAI-compatible)
- Tauri Commands només per funcions pròpiament natives (baix acoblament)

**Negatives / riscos:**
- Desenvolupadors han d'aprendre quan usar cada canal
- Complexitat documental de l'API

**Mitigacions:**
- Convenció clara: "si és dada → HTTP/WS; si és recurs del SO → Tauri Commands"
- Documentació a l'ADR-0010 (contracte API, pendent)
- TypeScript client API per frontend (nou, no reescriure UI)

## Referències

- original plan (not in template)
