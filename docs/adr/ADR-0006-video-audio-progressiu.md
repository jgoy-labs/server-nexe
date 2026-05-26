# ADR-0006: Vídeo i àudio — progressiu (v1 bàsic, v2 ampli)

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

nexe-app vol suportar multimèdia (STT/TTS, generació visual via ComfyUI, streaming). Implementar-ho tot a v1 alenteix l'alliberament. Cal prioritzar.

## Decisió

**Escala progressiva:**

| Capacitat | v1 | v2 |
|---|---|---|
| Reproducció/streaming bàsic | ✅ | — |
| STT (speech-to-text) | — | Vosk (offline lleuger, bindings Rust/FFI) |
| TTS (text-to-speech) | — | Piper (OHF-Voice/piper1-gpl) |
| whisper.cpp com alternativa STT | — | Opcional (més precís, més pesat) |
| WebRTC | — | Feature-flagged (pot trencar a Linux WebKitGTK) |
| Connector ComfyUI | — | API local via WebSocket → canvas HTML5 |

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **Tot a v1** | Retarda release mesos; multimèdia té riscos per plataforma |
| **Cap multimèdia** | Limita massa l'abast del producte |
| **Cloud STT/TTS (OpenAI Whisper API, ElevenLabs)** | Viola sobirania |
| **Piper per STT** | Piper és TTS, no STT — requereix altre motor |
| **WebRTC a v1** | Suport inconsistent a WebKitGTK, risc alt |

## Conseqüències

**Positives:**
- v1 arriba abans (MVP clar: Fases 0-2 = 5-7 setmanes)
- v2 aprofita aprenentatges de v1
- STT/TTS offline → 100% sobirà
- Feature flags permeten activar WebRTC per usuaris early-adopters

**Negatives / riscos:**
- Usuaris primerencs no tenen veu/ComfyUI integrat
- Afegir multimèdia a v2 requereix entitlements macOS (càmera/micròfon) + permisos WebKitGTK

**Mitigacions:**
- Doc clar del que NO hi ha a v1 (veure §10 del pla)
- Plugin `speech-service` (a `plugins-nexe`) preparat com a abstracció multi-backend
- Tests específics de permisos media per plataforma a Fase 6

## Referències

- original plan (not in template)
