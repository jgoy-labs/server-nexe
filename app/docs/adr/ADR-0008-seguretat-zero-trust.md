# ADR-0008: Seguretat — Zero Trust local

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

L'app viu al disc de l'usuari, però conviu amb altres processos i plugins third-party. Cal una postura de seguretat estricta des del dia 1, abans d'exposar API o marketplace.

## Decisió

**Zero Trust local — defense in depth:**

| Capa | Mesura |
|---|---|
| **CSP** | `default-src 'self'; connect-src ws://localhost:8000 http://localhost:8000` |
| **Capabilities Tauri** | Mínimes per finestra/webview (principi privilegi mínim) |
| **Shell scopes** | Restrictius — només binaris i args permesos |
| **Stronghold** | Per secrets de runtime (JWT keys, tokens, claus cripto). Xifrat Argon2, cross-platform |
| **Store** | Per configuració ordinària (preferències UI, últim port, estat finestres) — NO secrets |
| **Chromium perfils** | Efímers per tasca, persistents opcional |
| **Telemetry** | Zero per defecte |
| **Lifecycle** | Rust intercepta `CloseRequested` → `POST /api/v1/system/shutdown` → kill sidecar |
| **Single instance** | `tauri-plugin-single-instance` |
| **Plugins third-party** | Iframe sandboxed, sense `window.__TAURI__`, firewall postMessage |
| **Nivell confiança plugin** | Declarat al manifest (`trust = "first-party" \| "third-party"`) |

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **Zero sandboxing (tot accés lliure)** | Irresponsable si hi ha plugins comunitat |
| **Només CSP, sense capabilities** | Tauri demana capabilities explícites per IPC natiu |
| **Secrets al `.env` o Store** | `.env` és text clar al disc, Store no xifrat |
| **Telemetry opt-out** | Viola principi sobirania |

## Conseqüències

**Positives:**
- Postura defensiva abans d'obrir a comunitat
- Ús d'estàndards Tauri (Stronghold, capabilities) — no re-inventar
- Auditable i documentable públicament
- Resistent a "un plugin malintencionat compromet tot"

**Negatives / riscos:**
- Desenvolupament de plugins third-party té més fricció (no accés a IPC directe)
- Capabilities mínimes poden requerir iteracions quan apareguin casos d'ús nous
- Stronghold té corba d'aprenentatge

**Mitigacions:**
- Signatura de plugins prevista v2 (whitelist confiable)
- Review final CSP, capabilities, shell scopes a Fase 5 abans de release
- Tests de fuga sandbox com a criteri d'acceptació Fase 4

## Implementation status (starter v0)

### ✅ Actiu — implementat al codi

| Mesura | Notes |
|---|---|
| CSP estricta (host) | `tauri.conf.json` `script-src 'self'`, `connect-src` limitat |
| CSP estricta (plugin response) | `plugin_protocol_handler` (Sprint 0.9 #16) |
| Capabilities mínimes | Només `core:default` a `capabilities/default.json` |
| Anti-traversal (canonicalize) | `resolve_plugin_path` + tests unitaris |
| Validate plugin_id lowercase | Sprint 0.8 #8 (APFS cross-platform bug fix) |
| Tracing structured logs | `tracing` + `tracing-subscriber` amb EnvFilter |
| Zero telemetry | Per disseny — cap dep d'analytics |
| `withGlobalTauri: false` | ESM imports via Vite |
| Release binary hygiene | `[profile.release]` strip+lto+panic=abort (Sprint 0.9 #17) |
| `cargo audit` gate al CI | `--deny warnings` + `.cargo/audit.toml` ignores |
| Plugin integrity SHA-256 | Cache O(1), walk+hash complet (Sprint 0.15 #4, ADR-0014) |
| Isolation Pattern (postMessage) | Firewall JS per IPC plugins (Sprint 0.15 #3, ADR-0013) |
| Rate limiting per-plugin | Token bucket 1000 req/s (Sprint S06 F023) |
| `dragDropEnabled: false` | Prevenció XSS via File.path (Sprint S06 F028) |

### ⏳ Planificat — decisió presa, implementació pendent

| Mesura | Fase | Notes |
|---|---|---|
| Stronghold per secrets | Fase 2+ | `tauri-plugin-stronghold` quan l'app gestioni secrets |
| Single-instance lock | Sprint S09 | `tauri-plugin-single-instance` |
| Graceful lifecycle (shutdown HTTP) | Fase 2 | Placeholder al `RunEvent::ExitRequested`; requereix sidecar |
| Process tree kill | Fase 2 | `kill_process_tree` Unix/Windows; requereix sidecar |
| Chromium perfils efímers | Fase 3 | Requereix `browser-runner` plugin |
| Plugin signatures Ed25519 | Sprint S17 | Substitució hash auto-attestat per signatura criptogràfica |
| Signing macOS + notarització | Sprint S11b | Requereix Apple Developer ID del publicador |

## Referències

- original plan (not in template)
- [Tauri Security docs](https://tauri.app/security/)
- [Stronghold docs](https://tauri.app/plugin/stronghold/)
