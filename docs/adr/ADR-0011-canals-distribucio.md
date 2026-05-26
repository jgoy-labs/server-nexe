# ADR-0011: Canals de distribució — `lite` vs `full`

**Data:** 2026-04-18
**Estat:** Accepted (validació empírica pendent a Fase 5)
**Decidit per:** Jordi Goy

## Context

El bundle de nexe-app conté Rust shell (~10MB) + server-nexe Python venv relocatable (~250MB amb deps) + opcionalment Chromium per Playwright (~200MB). Pujar un bundle únic de ~500MB és fricció per adopció OSS (CDN cost, temps de descàrrega, prejudici sobre "apps pesants").

## Decisió

**Dos canals de distribució** des de Fase 5:

| Canal | Contingut | Mida estimada | Primer arrencat |
|---|---|---|---|
| **`lite`** | Shell + sidecar Python (sense Chromium) | ~80MB | `playwright install chromium` amb progress bar |
| **`full`** | Shell + sidecar Python + Chromium bundled | ~300MB | Llest per l'agent des del segon 1 |

**Usuari tria:**
- Primera visita → recomana `lite`
- Power user / offline / enterprise → `full`
- Docs `.dmg` / `.AppImage` diferenciats

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| Bundle únic `full` (~500MB) | Fricció d'adopció, cost CDN, mal missatge OSS |
| Bundle únic `lite` sempre | Primera experiència enganyosa (descàrrega extra invisible) |
| Tres canals (lite/medium/full) | Complicació sense guany clar |

## Conseqüències

**Positives:**
- Canal `lite` competeix amb apps d'Electron per mida (<100MB)
- Canal `full` és un-shot per enterprise/offline
- Separació permet CI builds paral·lels

**Negatives / riscos:**
- Mida exacta del venv relocatable és **empírica** i pot superar els estimats
- `playwright install` depèn d'accés a `github.com/microsoft/playwright` — no 100% offline
- Dos canals duplica el procés de test release

**Mitigacions:**
- **Abans de Fase 5**: mesurar mida real de `build-python-bundle.sh` output
- `playwright install` permet mirror intern com a fallback (docs)
- CI només verifica `lite` i `full` (no altres combinacions)

## Mides a validar empíricament

Pendent Fase 5:
- [ ] `du -sh <your-backend>/venv/` actual
- [ ] Mida Chromium per arquitectura (arm64 vs x86_64)
- [ ] Mida del shell Tauri `.dmg` sol (esperem ~10-15MB)

Si la mida real del `lite` supera 150MB, reobrir aquest ADR.

## Referències

- original plan (not in template)
- [ADR-0002 Empaquetament venv relocatable](ADR-0002-empaquetament-venv-relocatable.md)
- [ADR-0003 Agent Playwright Python](ADR-0003-agent-playwright-python.md)
