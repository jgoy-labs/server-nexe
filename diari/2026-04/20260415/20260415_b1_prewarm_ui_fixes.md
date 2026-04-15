---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "1.0"
data: 2026-04-15
id: 20260415-b1-prewarm-ui-fixes
abstract: "B.1 pre-warm fastembed al lifespan (startup ràpid) + 4 fixes UI: mida RAM dropdown, imatge inline chat, preview bar alineada. DMG v0.9.8 sincronitzat a gitoss."
tags: [server-nexe, b1, fastembed, prewarm, lifespan, ui, vlm, dmg, gitoss]
chunk_size: 800
priority: P1
project: server-nexe
area: dev
type: diari
estat: published
lang: ca
author: "Jordi Goy"
---

# 2026-04-15 — B.1 pre-warm fastembed + fixes UI

## Què s'ha fet

### B.1 — Pre-warm fastembed al lifespan startup
- Cablejat `_prewarm_fastembed()` com a background task non-blocking a `core/lifespan.py`
- Crida `asyncio.create_task(_prewarm_fastembed())` just després de les fases d'inicialització, guardada a `server_state._prewarm_task`
- Cancel·lació al shutdown (afegida al loop de cleanup existent)
- La funció obté el singleton `MemoryAPI` via `get_memory_api()`, activa `pre_warm=True` a la instància (no al default global) i crida `warmup()`
- Log `MemoryAPI: fastembed pre-warm complete (Xms)` visible al startup

### UI fixes (4 commits)
1. **Dropdown models — mida RAM** (`app.js`): recuperat `size_gb` del backend, mostrat com `(~XGB)` al costat del nom i la icona 👁️
2. **Imatge inline al chat** (`app.js`, `style.css`): quan l'usuari puja una foto, apareix un bubble de l'usuari amb la imatge (màx 320×240px) just abans de la resposta del Nexe. `URL.createObjectURL` per preview local, CSS `.message-image-preview`
3. **Preview bar alineada** (`index.html`): la barra negra d'adjunt ara té `max-width: 900px; margin: auto; border-radius` — alineada amb el camp d'input
4. **Commit UI anterior**: dropdown VLM eye icon + `image_describe` i18n key (ca/en/es) + upload routing per imatges vs documents

### Sync + DMG
- `ship-nexe.sh --go`: 3 fitxers sincronitzats, tag `gitoss-sync-20260415a`, commit gitoss `8c00ca6`
- DMG 27MB signat, copiat a Desktop
- Push a GitHub: pendent (fer `/push`)

## Canvis

| Fitxer | Canvi |
|---|---|
| `core/lifespan.py` | `_prewarm_fastembed()` + `create_task` + cancel shutdown |
| `tests/test_lifespan_prewarm.py` | 3 tests nous (happy path + 2 error cases) |
| `plugins/web_ui_module/ui/app.js` | mida RAM dropdown + imatge inline chat + `addMessageToChat` imageUrl param |
| `plugins/web_ui_module/ui/index.html` | preview bar alineada (max-width + margin + border-radius) |
| `plugins/web_ui_module/ui/style.css` | `.message-image-preview` CSS |

## Decisions

- **`MemoryAPI` ≠ `MemoryService`**: descobert durant la fase de pla. `MemoryAPI` (fastembed/ONNX) és completament diferent de `MemoryService` (SQLite+Qdrant pipeline). El singleton de `MemoryAPI` és `get_memory_api()` a `v1.py`.
- **`pre_warm` s'activa a la instància, no al default global**: evita regressions als tests que confien en `pre_warm=False` per defecte.
- **Opció B descartada**: passar `pre_warm=True` al constructor no era suficient perquè `warmup()` mai s'executa automàticament (only `ingest_knowledge.py:299` la crida, condicionalment). Calia la crida explícita al lifespan.
- **`.gitoss-sync` ja tenia `scripts/` i `bench/`**: afegits en una sessió anterior, no calia modificar.

## Tests

- `tests/test_lifespan_prewarm.py`: 3 tests verds
- Suite completa `memory/ + core/ + tests/`: 653 tests verds, 0 regressions

## Estat

- B.1 completat i a gitoss
- UI fixes completats, pendents de DMG final (proper `/sincro-nexe`)
- Install neta M4 Pro: pendent (Jordi farà drag-to-Applications quan tingui el DMG actualitzat)
- M1 8GB: pendent (bloquejat per install neta M4 Pro)

---

## Sessió 2 — UI polish post-DMG (matí)

### Què s'ha fet

- **Mida RAM al dropdown** (`273f77d`): recuperat `size_gb` del backend, format `(~XGB)` combinat amb icona 👁️
- **Imatge inline al chat — upload** (`78db461`): foto pujada via upload apareix en bubble usuari + preview bar alineada amb input (max-width 900px, border-radius, margin auto). CSS `.message-image-preview`
- **Fix regressió streaming** (`9afc2e5`): el refactor de `addMessageToChat` no creava `textDiv` quan `content=''` → `assistantMessageDiv` era `null` → crash. Fix: assistant sempre crea el div; user només si hi ha text
- **Imatge inline VLM** (`9b22079`): quan l'usuari envia missatge amb foto adjunta (botó càmera), el bubble mostra text + imatge. Captura `pendingImage` *abans* de `_clearSelectedImage()` i passa `data:image/...;base64,...` com `imageUrl` a `addMessageToChat`
- Còpia manual a `/Applications/server-nexe/` per testing en directe (sense DMG)

### Bug causat i resolt

El `if (content) contentDiv.appendChild(textDiv)` ometia el `textDiv` per missatges assistant buits inicials (el streaming els omple). El querySelector del streaming obtenia `null` → `TypeError`. Resolt separant la condició: assistant sempre crea textDiv, user només si té text.

### Canvis per gitoss

- `plugins/web_ui_module/ui/app.js` — modificat (sync)
- `plugins/web_ui_module/ui/index.html` — modificat (sync)
- `plugins/web_ui_module/ui/style.css` — modificat (sync)

### Estat final

Tots els canvis commitejats a dev. Pendent: `/sincro-nexe` per DMG actualitzat + push GitHub.

## Wikilinks

- [[nat/dev/server-nexe/diari/prompts/20260415-b1-prewarm-sync-dmg]] — prompt original
- [[nat/dev/server-nexe/diari/INDEX_DIARI]]
