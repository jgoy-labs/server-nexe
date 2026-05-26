# ADR-0018: Python sidecar packaging — PBS + uv

**Data:** 2026-04-23
**Estat:** Accepted
**Supersedes:** ADR-0002 (venv relocatable)
**Decidit per:** Jordi Goy
**Finding:** F016

## Context

ADR-0002 va decidir empaquetar el sidecar Python com a venv relocatable via `build-python-bundle.sh`. L'enfocament funciona a macOS però és **insostenible cross-platform** (F016):

- `*.dylib` / `*.so` tenen paths absoluts rígids que trenquen en reubicar
- Cada plataforma requereix tractament diferent dels binaris compilats
- La relocabilitat depèn de hacks (`install_name_tool`, `patchelf`) fràgils

A més, server-nexe instal·la motors d'inferència **dinàmicament** post-install (mlx-lm, llama-cpp-python via `installer_setup_env.py`), cosa que descarta qualsevol eina que congeli l'aplicació en temps de build.

## Decisió

**python-build-standalone (PBS) + uv** per crear un sidecar autocontingut:

1. `uv venv --python 3.12` descarrega un Python PBS relocatable per a la plataforma target
2. `uv pip install -r requirements.txt` instal·la deps al venv
3. Un launcher script (`nexe-sidecar`) arrenca el servidor amb `PYTHONNOUSERSITE=1`
4. El venv complet es bundleja dins el paquet Tauri (`Resources/sidecar/`)

### Per què PBS + uv

- **Ja usat**: server-nexe's `build-python-bundle.sh` ja descarrega PBS d'astral-sh
- **Relocatable by design**: PBS builds són explícitament relocatables (troben stdlib relatiu al binari)
- **Deps dinàmiques**: el venv és standard Python — es poden instal·lar deps addicionals post-install
- **uv és 10-100x més ràpid que pip**: venv creat en <1s, deps instal·lades en <2s
- **Cross-platform**: PBS disponible per macOS (ARM64, x64), Linux (x64, ARM64), Windows (x64, ARM64)
- **Transparent**: és un venv normal — debugging, profiling, i inspecció sense eines especials

## Decision matrix

| Criteri | PBS + uv | PyInstaller | Nuitka | PyOxidizer | Shiv |
|---|---|---|---|---|---|
| Deps post-install | ✅ venv modificable | ❌ congelat | ❌ compilat | ❌ embedded | ❌ zipapp |
| Native deps (numpy, cryptography) | ✅ pip wheels | ⚠️ hooks | ⚠️ C compilation | ❌ pobre suport | ✅ si Python sistema |
| mlx-lm / llama-cpp-python | ✅ pip install post | ❌ no dynamic | ❌ no dynamic | ❌ no dynamic | ❌ requereix Python |
| Build time (POC) | **<3s** | ~30s-2min | ~5-30min | ~2-5min | ~10s |
| Bundle size (FastAPI POC) | **20MB** | ~40-60MB | ~30-50MB | ~50-80MB | ~15MB |
| Startup time | **<1s** (direct) | 2-5s (unpack) | <1s | 1-2s | 1-3s (extract) |
| Debugging | ✅ standard Python | ❌ frozen | ❌ compiled | ❌ embedded | ⚠️ |
| Cross-platform | ✅ PBS matrix | ✅ | ⚠️ CI C compiler | ⚠️ stalled project | ❌ req Python |
| Tauri integration | script/Command | externalBin native | externalBin native | externalBin native | requereix Python |
| Maduresa | ✅ PBS: astral-sh actiu | ✅ molt madura | ✅ madura | ❌ stalled | ⚠️ nínxol |
| Infraestructura existent | ✅ reutilitza scripts | nova | nova | nova | nova |

### Descart d'alternatives

| Opció | Motiu descart |
|---|---|
| **PyInstaller** | server-nexe instal·la motors dinàmicament → congelar en build time és incompatible. ADR-0002 ja ho va descartar per startup lent i problemes amb C extensions. `--onedir` millora startup però no resol el problema fonamental |
| **Nuitka** | Compilar 750 .py + deps natives (mlx, llama-cpp) a C seria hores de build + matriu de C compilers per plataforma. No afegeix valor vs PBS |
| **PyOxidizer** | Projecte amb activitat reduïda (stalled). Suport pobre per extensions natives (numpy, cryptography). Descartable |
| **Shiv** | Requereix Python instal·lat al sistema target. Contradiu l'objectiu d'app autocontinguda |

## POC validat (2026-04-23)

```
Script:  scripts/build-sidecar.sh
App:     scripts/poc-sidecar/app.py (FastAPI health endpoint)
Result:  PASS

Mètriques (macOS ARM64, Apple M4 Max):
  Venv creation:  0s (PBS cached)
  Deps install:   0s (wheels cached) / 2s (first run)
  Bundle size:    20MB (FastAPI + uvicorn only)
  Health check:   PASS (boot + curl + shutdown)
  Isolation:      PASS (funciona sense Python del sistema al PATH)
```

## Integració Tauri (Fase 2)

```
nexe-app.app/
└── Contents/
    └── Resources/
        └── sidecar/
            ├── venv/           ← PBS Python 3.12 + site-packages
            ├── app/            ← server-nexe code
            └── nexe-sidecar    ← launcher (Tauri Command target)
```

- Tauri invoca `nexe-sidecar` via `Command::new()` o `externalBin`
- Token auth via env var `NEXE_AUTH_TOKEN` (S10 implementat)
- Supervisor (S12a/S12b) gestiona lifecycle + health check

## Evolució futura

1. **Fase 2**: Integrar `build-sidecar.sh` al workflow de `pnpm tauri build`
2. **CI matrix**: Build per-platform (macOS-arm64, Linux-x64, Linux-arm64, Windows-x64)
3. **Trimming avançat**: Eliminar mòduls stdlib no usats per reduir mida
4. **Lock file**: `uv lock` per deps reproduïbles
5. **Si algun dia PBS no és suficient**: PyInstaller `--onedir` com a fallback (però cal resoldre deps dinàmiques)

## Conseqüències

**Positives:**
- Reutilitza infraestructura existent (PBS, uv, scripts server-nexe)
- Venv modificable post-install (motors d'inferència, plugins)
- Debugging transparent (és Python estàndard)
- Build ràpid (<3s POC, estimat <30s amb tots els deps)
- Cross-platform validat (PBS matrix cobreix totes les targets)

**Negatives / riscos:**
- Bundle size major que binari compilat (~250-350MB amb tots els deps + models embedding)
- Depèn d'astral-sh/python-build-standalone (risc: projecte ben mantingut, amb Ruff/uv darrere)
- Wrapper script vs executable natiu (mitigació: Rust shim si cal)

## Referències

- [python-build-standalone](https://github.com/astral-sh/python-build-standalone) — astral-sh
- [uv](https://github.com/astral-sh/uv) — package manager
- server-nexe `installer/build-python-bundle.sh` — implementació existent
- ADR-0002 (superseded) — decisió original venv relocatable
- Finding F016 — venv relocatable insostenible cross-platform
