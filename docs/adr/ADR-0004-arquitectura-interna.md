# ADR-0004: Arquitectura interna (thin shell / thick backend)

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

Cal decidir on viu la lògica de negoci: al Rust core de Tauri o al backend Python existent (server-nexe). Principis a preservar: modularitat, reutilització del que ja funciona, seguretat.

## Decisió

**Thin shell / thick backend:**

- **Tauri (Rust)** = finestra + permisos + lifecycle + IPC natiu (NO lògica de negoci)
- **server-nexe (Python)** = tota la lògica: plugins, RAG, memòria, auth, motors IA
- **Webview principal** = UI NAT empaquetada (assets estàtics dins l'app)
- **Webview secundari** (opcional) = "Agent Workspace" per preview de l'agent
- **NO servir la UI via localhost** (risc de seguretat documentat per Tauri)

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **Rust absorbint lògica de negoci** | Duplicaria server-nexe, violaria modularitat, alt cost dev |
| **UI servida via localhost:8000** | Vulnerabilitat (qualsevol procés local pot accedir), documentada pel propi Tauri |
| **Un sol webview** (sense agent separat) | Impossible mostrar preview navegador real amb webview natiu |
| **Frontend-only Tauri sense server** | Perdríem RAG, memòria, multi-LLM, seguretat ja feta a server-nexe |

## Conseqüències

**Positives:**
- server-nexe existent es reutilitza sencer (zero reescriptura)
- Rust fa allò en què és bo: lifecycle, seguretat, IPC natiu
- Separació neta de capes facilita testing i substitució
- El Rust core NO necessita saber de plugins específics

**Negatives / riscos:**
- IPC híbrid afegeix complexitat (veure ADR-0005)
- Dos runtimes (Rust + Python) = dos sets de crashes potencials
- Ordre d'arrencada important: backend primer, frontend segon

**Mitigacions:**
- Rust intercepta `WindowEvent::CloseRequested` → shutdown HTTP → kill sidecar
- Splash screen "Backend offline/Starting/Ready" amb health check
- Logging unificat a `nat-desktop.log`

## Referències

- original plan (not in template)
