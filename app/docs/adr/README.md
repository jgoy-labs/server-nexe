# ADRs — Architecture Decision Records

Registre de decisions arquitectòniques per **nexe-app**. Cada ADR captura una decisió clau amb context, alternatives i conseqüències.

## Convenció

- Format: `ADR-NNNN-titol-curt.md`
- Estats: `Proposed` · `Accepted` · `Deprecated` · `Superseded by ADR-XXXX`
- No modificar un ADR acceptat: crear-ne un de nou que el deprecate

## Index

| # | Títol | Estat | Data |
|---|---|---|---|
| [0001](ADR-0001-shell-tauri-v2.md) | Shell: Tauri v2 | Accepted | 2026-04-17 |
| [0002](ADR-0002-empaquetament-venv-relocatable.md) | Empaquetament Python: venv relocatable | Superseded by ADR-0018 | 2026-04-17 |
| [0003](ADR-0003-agent-playwright-python.md) | Agent navegador: Playwright Python | Accepted | 2026-04-17 |
| [0004](ADR-0004-arquitectura-interna.md) | Arquitectura interna: separació UI/agent | Accepted | 2026-04-17 |
| [0005](ADR-0005-ipc-hibrid.md) | IPC: HTTP/WS + Tauri Commands | Accepted | 2026-04-17 |
| [0006](ADR-0006-video-audio-progressiu.md) | Vídeo i àudio: progressiu (v1/v2) | Accepted | 2026-04-17 |
| [0007](ADR-0007-plugins-tres-nivells.md) | Plugins: 3 nivells (core/first/third) | Accepted | 2026-04-17 |
| [0008](ADR-0008-seguretat-zero-trust.md) | Seguretat: Zero Trust local | Accepted | 2026-04-17 |
| [0009](ADR-0009-plugin-uri-scheme.md) | Protocol `plugin://` per UI plugins | Accepted (spike ok) | 2026-04-17 |
| [0010](ADR-0010-contracte-api-v0.md) | Contracte API v0 (7 endpoints) | Accepted | 2026-04-18 |
| [0011](ADR-0011-canals-distribucio.md) | Canals distribució lite/full | Accepted (mida pendent) | 2026-04-18 |
| [0012](ADR-0012-plugin-scheme-linux.md) | `plugin://` Linux WebKitGTK | Accepted — Verified (Sprint 0.15) | 2026-04-18 |
| [0013](ADR-0013-isolation-pattern.md) | Isolation Pattern | Accepted — Active (Sprint 0.15) | 2026-04-18 |
| [0014](ADR-0014-plugin-integrity.md) | Plugin integrity SHA-256 | Accepted — Active (Sprint 0.18, atomic snapshot) | 2026-04-21 |
| [0015](ADR-0015-reproducible-builds-path.md) | Reproducible builds path | Accepted (baseline, SLSA deferred) | 2026-04-18 |
| [0016](ADR-0016-migracio-server-nexe-peca-per-peca.md) | Migració server-nexe peça per peça amb millores | Accepted | 2026-04-20 |

| [0018](ADR-0018-python-sidecar-packaging.md) | Python sidecar packaging: PBS + uv | Accepted | 2026-04-23 |

## Pendents

- ADR-0019 UI integration + state machine (Fase 1)
- ADR-0020 Graceful shutdown + kill process tree (Fase 2)

## Font

Decisions basades en:
- original plan (not in template)
- 4 informes HOMAD independents (external audit inputs (not in template))
