---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "1.0"
data: 2026-04-15
id: server-nexe-vlm-gemma4-streaming-20260415
abstract: "Sessió maratoniana VLM: detector robust, mlx-vlm 0.1→0.4.4, port API _generate_vlm, Gemma-4 oficials baixats, install neta v0.9.8 real validada text+imatge+streaming, fix system prompt/MEM_SAVE, duplicació Nexe.app documentada. 12 commits dev + 4 syncs gitoss."
tags: [diari, server-nexe, vlm, mlx, gemma-4, streaming, v098, installer, dock]
chunk_size: 800
priority: P1
project: server-nexe
area: dev
type: sessio
estat: published
lang: ca
author: "Jordi Goy"
---

# 2026-04-15 — VLM Gemma-4 end-to-end + streaming + bump 0.9.8

#diari #server-nexe #vlm #mlx

↑ [[nat/dev/server-nexe/diari/INDEX_DIARI|Diari server-nexe]]

## Context

Jordi arrenca `/director server-nexe` amb la idea de proves finals pre-release v1.0. Descobrim `Received 333 parameters not in model` al carregar un MLX des de la UI (Qwen3.5 MoE). El que havia de ser un checklist de validació es torna una sessió sencera de debug VLM, upgrade de deps crític (numpy 1→2), 11 commits al dev, 3 syncs a gitoss, un DMG en calent que trenca l'install i un DMG definitiu que funciona.

## Què s'ha fet

### 1. Detector VLM robust (`fe2421d`)
- `_detect_vlm_capability` passa de "architecture al set" a **3 senyals any-of**:
  1. `architectures[]` — set ampliat a 16 entrades (Qwen2_5_VL, Qwen3VL, Qwen3_5Moe, LlavaOnevision, InternVL2, MiniCPMV, Idefics3, Mllama, Gemma4…)
  2. `vision_config` no buit al `config.json`
  3. Weight-map de `model.safetensors.index.json` amb `vision_tower` / `vision_model` / `visual.` / `mm_projector` / `image_newline` / `patch_embed`
- 8 tests nous (12 → 20 al `test_multimodal.py`). Cas Qwen3.5 MoE que avui venia silent-degraded → ara detectat.

### 2. Port API `_generate_vlm` a mlx-vlm ≥ 0.4 (`e0d2e11`)
- mlx-vlm 0.4 canvia `image=` (str path/List[str], no PIL) i retorna `GenerationResult` (dataclass), no str
- `NamedTemporaryFile` per bytes → path (cleanup al `finally`)
- Extracció real de `prompt_tokens`, `generation_tokens`, `prompt_tps`, `generation_tps`, `peak_memory` (abans tot eren zeros)
- `Gemma4ForConditionalGeneration` afegit explícitament al set

### 3. Upgrade mlx pins (`9c509d7`)
- `mlx-lm 0.30.7 → 0.31.2`
- `mlx-vlm 0.1.27 → 0.4.4` (0.1.27 no coneixia `qwen3_5_moe`, `gemma4`, `qwen3_vl`, `llava_onevision`, etc.)
- Side effect: **numpy 1.26 → 2.4** (ABI break confirmat pel trencament posterior de `llama-cpp-python` en calent)
- 4679 tests passats post-upgrade, 11 fallades pre-existents (readiness + i18n) inalterades

### 4. KB LIMITATIONS actualitzat (`19158e7`)
- Nova secció **"Models multimodal (VLM)"** a ca/es/en
- Llista arquitectures suportades + 3 senyals del detector
- Omni-video (Qwen3.5 MoE, Qwen3-Omni, Kimi-VL) requereixen torch → **no bundlets** al DMG (~2 GB extra, deal-breaker)
- Default recomanat: Gemma-4 e4b-it-4bit (imatge only, sense torch)
- Re-generats embeddings via `scripts/precompute_kb.py` (pre-commit hook activat)

### 5. Bump 0.9.8 (`eb18066`)
- SSOT `pyproject.toml` 0.9.7 → 0.9.8
- Propagat a `personality/server.toml`, 4 `plugins/*/module.py`, 3 `tests/test_*_module.py`, Info.plist dels bundles via `python -m installer.sync_plist_versions`
- CHANGELOG 0.9.8 consolidant Unreleased (llama_cpp VLM passthrough, versions SSOT, readiness degraded, wizard/dock/logo polish) + fixes VLM d'avui

### 6. UI fixes dropdown 👁️ (`ff6e93a`, `3127aee`)
- `_modelHasVision` reconeix `gemma-4` (amb guió) — abans només `gemma4` → Gemma-4 sense icona 👁️
- Excloure 👁️ dels Qwen3.5 MoE / Qwen3-Omni / Kimi-VL (requereixen torch, no volem enganyar l'usuari)

### 7. Gemma-4 trencats → oficials (manual)
- Els `gemma-4-e4b-4bit` i `gemma-4-31b-8bit` que tenia Jordi eren conversions pre-oficials trencades (weights `vision_tower.encoder.layers.*` estil Gemma-3, incompatibles amb `mlx_vlm.models.gemma4`)
- Esborrats del SSD + Wintermute (còpies locals)
- Baixats oficials via `hf download`:
  - `mlx-community/gemma-4-e4b-it-4bit` (4.9 GB, 6m 20s)
  - `mlx-community/gemma-4-31b-it-8bit` (31 GB, ~25 min en background)

### 8. DMG en calent que trenca (incident)
- Upgrade `pip install mlx-vlm==0.4.4` aplicat al venv `/Applications` amb servidor corrent
- numpy 1.26 → 2.4.4 trenca ABI de `llama-cpp-python` (compilat contra numpy 1.x)
- Primer chat amb un GGUF: `Fatal Python error: init_sys_streams` OSError Errno 9
- Install neta del DMG v0.9.8 (17:13) recupera estat funcional

### 9. Fix runtime VLM pipeline (`3584e72`) — la cadena
Quatre bugs compostos que calien tots per fer funcionar text + imatge sobre Gemma-4:
- **(a)** Bifurcació `if _is_vlm` feia servir el flag singleton, que és `False` fins que `_get_model()` ha acabat. Al primer request el flux queia al `_generate_blocking` → `tokenizer.encode()` sobre Gemma4Processor → error `'Gemma4Processor' object has no attribute 'encode'`. Fix: decidir amb `_detect_vlm_capability(path)` directament.
- **(b)** Text-only sobre VLM també ha de passar per `_generate_vlm` (empty images → `image=None` al `mlx_vlm.generate`). Abans intentava anar al blocking path i petava per (a).
- **(c)** `apply_chat_template` necessita `config` dict amb `model_type`. `Gemma4Processor` no té `.config`, `model.config` és `ModelConfig` dataclass → llegir `config.json` directament.
- **(d)** Imatges del web UI venen com a base64 str (amb o sense prefix `data:image/...;base64,`), no bytes. Normalitzar abans d'escriure al tempfile.

### 10. Streaming VLM (`5b7f1a8`)
- `mlx_vlm.stream_generate` existeix i yielda `GenerationResult` per cada token
- `_generate_vlm` ara usa `stream_generate` quan hi ha `stream_callback`, one-shot `generate` quan no
- Smoke: 13 deltas progressius, text acumulat coherent, 122 tok/s sobre Gemma-4 e4b
- KB LIMITATIONS actualitzat per treure "VLM streaming not supported yet" (`7ca7dd6`)

### 11.5. System prompt + historial al VLM (`57461b7`) — **bug detectat per Jordi post-diari**

Jordi proba el Gemma-4-31b-it-8bit i es pregunta: *"el VLM amb visió no guarda memòria??"*. Investigació: `_generate_vlm` cridava `apply_chat_template(prompt=messages[-1]["content"])` — **només l'últim missatge user**. Es perdien:
- **System prompt** complet → contracte `[MEM_SAVE: ...]` mai arribava al model → `routes_chat.py` mai podia extreure-ho
- **Instrucció d'idioma** al system → model derivava a anglès (per això Jordi veia anglès amb e4b)
- **Historial conversa** → sense multi-turn real
- **RAG context** quan s'injectava al system

Fix: construir la llista completa `system + messages` i passar-la a `apply_chat_template` (accepta `List[Dict]`). Smoke empíric al dev:
```
system="Respon sempre en català. Si detectes un fet personal, emet [MEM_SAVE: <fet>]"
user="Em dic Jordi i visc a Barcelona"
→ "[MEM_SAVE: El meu nom és Jordi i vis a Barcelona]"
```
Català correcte + MEM_SAVE emès ✅. El model sí "guardava memòria" conceptualment — només calia que rebés el contracte.

### 11. Nexe.app duplicada documentada (`2dc1bac`) — opció C
- Verificat: `/Applications/Nexe.app` i `/Applications/server-nexe/Nexe.app` són còpies físiques idèntiques (mateix timestamp, contingut, inodes diferents)
- És **design intencional** (`install_headless.py:528`): la còpia arrel dóna al usuari una icona "Nexe" visible sense entrar a subcarpeta; Dock / Login Items / Launch Services ancoren al path estable
- Descartat symlink (risc Gatekeeper + LaunchServices a macOS 26)
- Descartat single-location (refactor massa gran)
- Afegit `DESIGN NOTE` al callsite + secció "Post-install layout" a `docs/BUILDING.md`

## Canvis

### Commits dev (en ordre cronològic, +1 post-diari)
- `fe2421d` fix(mlx): robust VLM detection (architectures + vision_config + weight_map)
- `e0d2e11` fix(mlx): port _generate_vlm to mlx-vlm ≥ 0.4 API
- `9c509d7` chore(installer): bump mlx-lm 0.30.7→0.31.2 + mlx-vlm 0.1.27→0.4.4
- `19158e7` docs(kb): limitacions models multimodal (VLM) + Gemma-4 recomanat
- `eb18066` chore(release): bump to 0.9.8
- `ff6e93a` fix(ui): _modelHasVision recognises gemma-4 (with hyphen)
- `3127aee` fix(ui): omit 👁️ for omni-video VLMs that need torch
- `3584e72` fix(mlx): complete VLM pipeline for text + image (Gemma-4 real-world validation)
- `5b7f1a8` feat(mlx): VLM streaming via mlx_vlm.stream_generate
- `7ca7dd6` docs(kb): drop "VLM streaming not supported" from LIMITATIONS (resolved)
- `2dc1bac` docs(installer): document the intentional /Applications/Nexe.app duplication
- `57461b7` fix(mlx): VLM receives full message history + system prompt ← **post-diari inicial, caçat per Jordi**

### Syncs gitoss
- `gitoss-sync-20260415i` — 3 commits VLM
- `gitoss-sync-20260415j` — streaming + KB cleanup
- `gitoss-sync-20260415k` — doc Nexe.app duplication
- `gitoss-sync-20260415l` — fix system prompt VLM

### DMG
- `Install Nexe.dmg` v0.9.8 al Desktop, 27 MB, Apple Accepted stapled — 20:51
- Install neta validada: text + imatge + streaming amb `gemma-4-e4b-it-4bit`

## Decisions

- **Detector VLM**: 3 senyals any-of en lloc de whitelist d'arquitectures. Cobre casos futurs i mal-etiquetats.
- **VLM amb torch no al DMG**: omni-video (Qwen3.5 MoE, Qwen3-Omni, Kimi-VL) requereixen PyTorch ~2 GB. Deixem aquests models fora de l'abast actual. Documentat a LIMITATIONS.md.
- **Gemma-4 com a VLM recomanat**: imatge-only, sense torch, bundlable. e4b per hardware modest, 31b-8bit per qualitat.
- **Nexe.app duplicada**: opció C (deixar com està + documentar). Symlink massa risc a macOS 26; single-location massa refactor.
- **Prefix-matching cache**: deshabilitat per VLM (mlx-vlm no exposa KV cache). Text-only MLX el manté. Caveat documentat al codi.

## Problemes

- **Upgrade en calent + numpy 2.x**: ABI break `llama-cpp-python` trenca tot. Lliçó: canvis majors de deps → **sempre via install neta del DMG**, mai en calent sobre servidor corrent.
- **Checkpoints Gemma-4 de MLX community**: la primera tongada (abril 2026) tenia conversions trencades (PLE + SigLIP2 + naming inconsistent). Cal baixar les versions recents (`mlx-community/gemma-4-*-it-4bit`). Referit a `FakeRocket543/mlx-gemma4` com a tercer-part que va detectar el problema.
- **Bifurcació VLM basada en flag singleton**: arrossegàvem bug silent des del primer commit VLM (12/04). El fix d'avui és el correcte: `_detect_vlm_capability(path)` pre-load.
- **System prompt desaparegut al VLM**: `apply_chat_template(prompt=messages[-1]["content"])` dropeava system + historial. Bug present al commit original (12/04), no detectat abans perquè les proves VLM no usaven MEM_SAVE ni multi-turn. Jordi l'ha caçat preguntant *"no guarden memòria??"* — cas d'ús real destapa el fail silenciós. Fix `57461b7`.

## Canvis per gitoss

Tots ja sincronitzats (tag `gitoss-sync-20260415k`). Estat dev = gitoss.

- `plugins/mlx_module/core/chat.py` — modificat (sync): detector robust, port API 0.4, streaming, bifurcació pre-load
- `plugins/mlx_module/tests/test_multimodal.py` — modificat (sync): +8 tests detector + +2 tests API 0.4
- `plugins/web_ui_module/ui/app.js` — modificat (sync): gemma-4 + exclusió omni
- `plugins/*/module.py` (4) — modificat (sync): bump 0.9.8
- `plugins/*/tests/test_*_module.py` (3) — modificat (sync): bump 0.9.8
- `installer/installer_setup_env.py` — modificat (sync): pins mlx-lm/mlx-vlm
- `installer/install_headless.py` — modificat (sync): DESIGN NOTE Nexe.app duplication
- `installer/NexeTray.app/Contents/Info.plist` — modificat (sync): bump 0.9.8
- `pyproject.toml` + `personality/server.toml` — modificat (sync): bump 0.9.8
- `requirements.txt` — modificat (sync): comentaris pins nous
- `knowledge/{ca,es,en}/LIMITATIONS.md` — modificat (sync): secció VLM + streaming removed
- `knowledge/.embeddings/` (manifest + metadata + vectors × 3 llengües) — modificat (sync): re-precompute
- `CHANGELOG.md` — modificat (sync): secció 0.9.8
- `docs/BUILDING.md` — modificat (sync): secció "Post-install layout"

Cap fitxer nou fora d'inventari. Cap fitxer per classificar a `.gitoss-sync`.

## Estat i pròxims passos

- [x] Fix VLM pipeline complet (text + imatge + streaming) validat amb Gemma-4 e4b a install neta v0.9.8
- [x] Gemma-4 oficials (e4b-it-4bit + 31b-it-8bit) baixats i symlinkats
- [x] DMG v0.9.8 notaritzat al Desktop (però sense els darrers fixes streaming/doc; caldria rebuild per v1.0)
- [x] Dev ↔ gitoss sincronitzat (tag `k`)
- [ ] **Provar `gemma-4-31b-it-8bit`**: validar qualitat multilingüe (català/castellà) vs e4b (anglès dominant). Pendent Jordi.
- [ ] **DMG v0.9.9 amb streaming + doc Nexe.app**: el DMG al Desktop no té els últims 3 commits (`5b7f1a8`, `7ca7dd6`, `2dc1bac`). Per distribució neta cal rebuild. Funcionalment, `/Applications` actual ja té els fixes.
- [ ] **Push GitHub**: commits gitoss no pushed encara (`371ca4a` → `734c463`)
- [ ] **Bug #18 MEM_DELETE**: segueix pendent (last P0 pre-v1.0). Prompt ja existeix a `diari/prompts/bug18-mem-delete-20260415/`.
- [ ] **VLM prefix-matching cache**: quan mlx-vlm exposi KV cache públic, revisar integració. No urgent.
- [ ] **Install M1 8GB**: validació al hardware més restrictiu pendent.
