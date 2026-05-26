# ADR-0007: Plugins a 3 nivells (core / first-party / third-party)

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

server-nexe té un sistema de plugins amb `manifest.toml`. Al saltar a app desktop, cal decidir:
- Com es renderitza la UI de cada plugin
- Quin nivell de confiança té cada plugin (accés a IPC Tauri, filesystem, etc.)
- Com s'habilita contribució de la comunitat sense comprometre seguretat

## Decisió

**Tres nivells clars:**

| Nivell | Tipus | Càrrega UI | Accés IPC Tauri | Exemples |
|---|---|---|---|---|
| **Mòduls core** | Integrats a server-nexe | Part UI web empaquetada, no passen per sistema plugins | Via API HTTP | Dashboard, RAG, Doctor, Memory, Security |
| **First-party** | Oficials (repo `plugins-nexe`) | Empaquetats al bundle, manifest TOML, UI via iframe o ruta | Via API HTTP | browser-runner, speech-service |
| **Third-party** | Comunitat | Iframe sandboxed (`sandbox="allow-scripts"`) | **NO** (sense `window.__TAURI__`) | Plugins comunitat (futur) |

**Comunicació third-party → app:** exclusivament via `window.postMessage` amb firewall JS (whitelist d'accions).

Extensió del `manifest.toml`:
```toml
[ui]
type = "iframe"           # iframe | route
entry = "ui/index.html"
title = "RAG"
icon = "search"
trust = "first-party"     # first-party | third-party

[desktop]
capabilities = ["none"]

[requires]
browser = false
microphone = false
comfyui = false
```

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **Un sol nivell (tot igual)** | No es pot obrir a comunitat sense risc seguretat |
| **Dos nivells (oficial / tercer)** | Barreja mòduls core (ja fets) amb plugins dinàmics (nou sistema) |
| **Només core (no plugins dinàmics)** | Trenca promesa modularitat, limita comunitat |
| **Sense iframe (rutes directes)** | Third-party pot accedir `window.__TAURI__` i escapar sandbox |

## Conseqüències

**Positives:**
- Mòduls core ja funcionen tal qual — zero reescriptura de l'UI web existent
- Plugin marketplace és viable (barrera baixa per third-party)
- Aïllament clar → seguretat demostrable
- `GET /v1/plugins/registry` permet dashboard dinàmic

**Negatives / riscos:**
- Three-tier és més complex de documentar que una-sola-via
- Third-party via iframe + postMessage té latència superior a IPC directe
- Hot-reload diferent per tier: first-party (observat per notify crate), third-party (manual)

**Mitigacions:**
- Signatura de plugins prevista per v2
- Compatibilitat per versió al manifest (bloqueja arrencada si incompatible)
- Protocol `plugin://` per servir assets: spike a Fase 0 (pendent, futur ADR-0009)

## Referències

- original plan (not in template)

## Nota F071 — Priorització plugin:// (Fase 0)

**Context:** la consultoria va assenyalar que sofisticar el protocol `plugin://` (integrity, CSP, rate limit) **abans** de tancar el sidecar core podria ser un ordre de prioritats invertit per a un starter standard.

**Decisió explícita:** acceptable per Fase 0.

- `plugin://` és la base de renderització dels plugins. Sense fonaments sòlids aquí, qualsevol plugin a Fase 1+ seria vulnerable.
- El sidecar core (server-nexe) és un component independent que s'integrarà a Fase 2 via el contracte API v0.
- L'ordre actual (plugin:// segur → sidecar Fase 2) minimitza deute tècnic a la capa més exposada.

**Revisió:** quan el sidecar s'integri (Sprint S12), validar que el token auth i el lifecycle graceful no requereixin canvis retroactius al handler.
