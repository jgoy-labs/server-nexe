---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "1.0"
data: 2026-04-15
id: server-nexe-installer-3-backends-engine-switching-20260415
abstract: "Sessió installer: 6 commits atòmics per fer que els 3 backends (Ollama/MLX/llama.cpp) convisquin al mateix install + auto-discover models + fix readiness unhealthy"
tags: [diari, server-nexe, installer, mlx, llama-cpp, ollama, readiness, v1.0, auto-discover]
chunk_size: 800
priority: P0
project: server-nexe
area: dev
type: sessio
estat: published
lang: ca
author: "Jordi Goy"
---

# 2026-04-15 — Installer: els 3 backends conviuen + auto-discover models + readiness fix

#diari #server-nexe #installer #mlx #llama-cpp #v1.0

↑ [[nat/dev/server-nexe/diari/INDEX_DIARI|Diari server-nexe]]

## Context

Sessió llarga de debug+fix a la tarda 2026-04-15, arran de voler testejar memòria amb els 3 engines d'inferència al mateix install (feature core del projecte: canviar engine des de la UI). Seqüència d'entrebancs reals cadascun dels quals ha destapat un bug diferent del bundle DMG.

## Què s'ha fet

Cadena de 6 bugs descoberts i corregits, install neta rere install neta:

1. **Backends no instal·lats** — `llama-cpp-python` només s'instal·lava si l'usuari triava llama.cpp al wizard. Tota l'altra gent que obria el dropdown Motor veia opcions que no responien.
2. **Backends no aprovats** — `NEXE_APPROVED_MODULES` només aprovava el mòdul de l'engine triat. Els altres quedaven discovered però skipped.
3. **TOML parser buggy** — `mlx_module/core/config.py` feia servir `toml==0.10.2` (PyPI) que peta amb triple-strings amb cometes + accents (línia 137 de `server.toml`). MLX se'n anava a terra silenciosament.
4. **Saltar model deixava l'install brossa** — Swift wizard té botó "Saltar model" que passa `None` al Python → `.env` sense `NEXE_DEFAULT_MODEL` → servidor arrenca unhealthy. A més la lògica inicial proposta forçava descarregar Qwen3.5 2B quan el cas real era: l'usuari salta *perquè ja té models Ollama*, no cal descarregar res.
5. **Models a `storage/models/` no detectats** — si caiguessis un model (o symlink) post-install, cap engine el veia fins editar `.env` a mà.
6. **Readiness unhealthy bloquejant** — amb els 3 backends aprovats, si un engine no té model `initialize()` retorna False → readiness declara `missing` → UI queda a "Iniciant..." negre per sempre.

Cada bug resolt amb commit atòmic.

## Canvis

### Commits (6)
- `5d72a92` — `installer/installer_setup_env.py` + `installer_setup_config.py`: `llama-cpp-python` sempre a Apple Silicon; `NEXE_APPROVED_MODULES` sempre amb els 3 mòduls.
- `3ec79ea` — `installer/install.py`: fallback Qwen3.5 2B quan `select_model` retorna None (superat pel 7cfc7dc, es manté com a safety net).
- `02bd8ba` — `plugins/mlx_module/core/config.py`: canvi de `import toml` + `toml.load` a `import tomllib` + `tomllib.load(f, "rb")`.
- `7cfc7dc` — `installer/install.py`: en saltar, query a `http://localhost:11434/api/tags`, primer model detectat és el default. Només cau a descarregar Qwen3.5 2B si Ollama és down o sense models.
- `46eae5a` — `plugins/mlx_module/core/config.py` + `plugins/llama_cpp_module/core/config.py`: auto-discover de `storage/models/` — MLX busca subdirectoris amb `config.json`, llama.cpp busca `*.gguf`, primer alphabetic wins, `resolve()` a absolut perquè `__post_init__` no el re-resolgui.
- `e1dc628` — `core/endpoints/root.py`: `_required_modules_from_config` marca `ollama_module/mlx_module/llama_cpp_module` com **opcionals** a readiness; només es manté requerit el `preferred_engine` actiu. Així un engine sense model no tomba la UI.

### Fitxer no-codi actualitzat
- `diari/TODO-installer-prerelease.md` — afegida secció "🔥 BLOQUEJADOR v1.0 — Install neta 2026-04-15 tarda" amb pla de test aparcat (6 passos × 3 engines = 18 validacions). No commitat (diari és privat, no viatge a gitoss).

## Decisions

- **Els 3 backends s'instal·len sempre a Apple Silicon**, no només el triat. Size cost: ~30 MB (Metal wheel de `llama-cpp-python`). Trade-off acceptable per UX.
- **Engines són opcionals al readiness**, només `preferred_engine` és obligatori. Racional: l'usuari pot tenir els 3 aprovats al dropdown però només un model configurat. Que un engine "dorm" no ha de fer caure tota la UI.
- **"Saltar model" respecta l'usuari power**: no descarrega res si ja té Ollama local. Fallback Qwen3.5 2B només si l'usuari no té res.
- **Auto-discover `storage/models/` al runtime**, no només al wizard: drop + restart funciona. Important perquè l'install neta esborra `storage/models/` cada cop.
- **Prioritat de resolució de model** (cada engine): env var explícita > `server.toml plugins.models.primary` (legacy MLX) > scan `storage/models/`. Cap canvi trencador.

## Problemes

- **`storage/models/` s'esborra cada install neta** — Jordi ha hagut de tornar a posar els 6 symlinks a Wintermute 3 cops. TODO: prep script `~/AI/bin/nexe-relink-models.sh` per restaurar-los d'un cop (pendent, parlem-ne post-validació).
- **Finder congelat** — Jordi ha hagut de reiniciar el Finder durant la sessió (nota del prompt "haig de reiniciar el finder a hamort"). No relacionat amb server-nexe, problema de macOS colateral pel volum de operacions amb el DMG.
- **`core/cli/cli.py:318,446`** encara usen `import toml` (vell). No toquen `server.toml`, no bloca v1.0, pendent cleanup post-release.
- **Bug `mlx_module` quan `initialize` torna False** — ara que el mòdul ja no bloqueja readiness, convindria que no es retirés de `modules` sinó que quedés en estat "degraded". Així el dropdown podria mostrar-lo com "MLX (sense model)" en lloc de desaparèixer. Post-v1.0.

## Canvis per gitoss

Dirs tocats pels 6 commits (tots dins `[sync].dirs` de `.gitoss-sync`):

- `core/endpoints/root.py` — modificat (sync) — fix readiness engines optional
- `installer/install.py` — modificat (sync) — fallback + skip→detect Ollama
- `installer/installer_setup_config.py` — modificat (sync) — aprovar 3 backends sempre
- `installer/installer_setup_env.py` — modificat (sync) — instal·lar `llama-cpp-python` sempre
- `plugins/llama_cpp_module/core/config.py` — modificat (sync) — auto-discover `storage/models/*.gguf`
- `plugins/mlx_module/core/config.py` — modificat (sync) — `tomllib` + auto-discover

Cap fitxer nou fora d'inventari. `/sincro-nexe` sincronitza tot directament.

## Estat i pròxims passos

### Just fet
- 6 commits atòmics al dev (HEAD: `e1dc628`).
- Fix readiness aplicat també en calent a `/Applications/server-nexe/core/endpoints/root.py` perquè la install actual pugui arrencar mentrestant.
- 6 symlinks a `storage/models/` restaurats des de Wintermute (3 MLX + 3 GGUF).

### Immediat (Jordi)
- Reiniciar Nexe amb symlinks ja presents → verificar `auto-discovered MLX model` i `auto-discovered GGUF model` al log, readiness `healthy`, UI carregada, dropdown amb 3 engines actius.
- `/sincro-nexe` (amb `/effort max`) → nou DMG amb els 6 commits.
- Install neta amb el DMG nou → provar escenaris skip + tria de model MLX + tria de model llama.cpp.

### Pla de test pre-v1.0 (aparcat fins UI arrenqui)
Per cada engine (Ollama / MLX / llama.cpp):
1. Memòria: afegir → reiniciar → recordar → esborrar → reiniciar → comprovar (**#18 MEM_DELETE**).
2. Pujar imatge (VLM).
3. Pujar doc (PDF / MD).
4. Preguntes obrint documentació (RAG).
5. Canviar pes / temperatura.
6. Activar/desactivar checks de col·leccions.

18 validacions totals. Un cop OK, GO v1.0.

### Post-v1.0 (apuntat al TODO)
- `core/cli/cli.py` també migrar a `tomllib`.
- `mlx_module` quan `initialize` torna False, quedar "degraded" en lloc de desaparèixer.
- Script `nexe-relink-models.sh` per restaurar symlinks post-install neta.
