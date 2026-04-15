---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "1.0"
data: 2026-04-15
id: server-nexe-director-session-bug18-20260415
abstract: "Sessió director Opus 4.6 (vespre) — cirurgia bug #18 MEM_DELETE completa: auditoria + 8 commits + 2 fixes UX (markers visibles + prompts atòmics) + sync gitoss. Últim P0 pre-v1.0 tancat."
tags: [diari, server-nexe, director, bug18, mem-delete, cirurgia, v099, v1, release]
chunk_size: 800
priority: P2
project: server-nexe
area: dev
type: sessio
estat: published
lang: ca
author: "Jordi Goy"
---

# 2026-04-15 — Director sessió: Bug #18 MEM_DELETE cirurgia completa

#diari #server-nexe #director #bug18

↑ [[nat/dev/server-nexe/diari/INDEX_DIARI|Diari server-nexe]]

## Què s'ha fet

Sessió director (Opus 4.6 1M context) al vespre, iniciada amb `/director server-nexe`. Panorama + decisió d'atacar #18 (últim P0 pre-v1.0) des de la instal·lació activa M4 Pro. Canvi a Opus 4.6 a petició Jordi per treballar la cirurgia in-process.

Cadena:

1. **Auditoria Fase 1 formal** — revisió codi exhaustiva, identificat 3 gaps P0 (G1/G2/G3) + matriu entregada a `20260415_bug18_auditoria.md`
2. **Mode pla aprovat** (4 tasques commits atòmics + smoke + tancament)
3. **Cirurgia Fase 2 — 4 commits #18 inicials** (security injection, clear_all, threshold empíric, e2e tests)
4. **Bump versió 0.9.9** — però amb error `pyproject.toml` no persistit + commit erroni a gitoss
5. **Correcció** — `git reset --hard` a gitoss (autoritzat Jordi), pyproject fix al dev
6. **Smoke empíric a install 0.9.8** — cicle save/list/delete/clear_all real — funciona ✅
7. **2 fixes UX descoberts empíricament** — tags visibles (Bug 1) + fets combinats (Bug 2)
8. **Commits finals** — strip markers + prompts atòmics + bump fix + diari tancament
9. **Sync gitoss** — via `ship-nexe.sh --go --no-dmg` → tag `gitoss-sync-20260415n`

## Canvis

### Codi
- `core/endpoints/chat_sanitization.py` — 4 patrons injection MEM_DELETE/MEM_SAVE/aliases (G3 P0 security)
- `plugins/web_ui_module/core/memory_helper.py` — `CLEAR_ALL_TRIGGERS`, intent `clear_all`, `matches_clear_all_confirm`, DELETE_THRESHOLD 0.70→0.20 (descoberta empírica)
- `plugins/web_ui_module/api/routes_chat.py` — branca `clear_all` amb confirmació 2-torns (session._pending_clear_all)
- `plugins/web_ui_module/ui/app.js` — strip centralitzat `[MODEL:…] / [DEL:N:…] / [MEM:…]` dins `renderMarkdown` + neteja render duplicat a L2304
- `personality/server.toml` — 6 prompts reforçats (ca/es/en × small/full) amb "REGLA ATÒMICA" un MEM_SAVE per fet
- `pyproject.toml` + `personality/server.toml` + 4 plugin `module.py` + 3 test manifests — bump 0.9.9
- `CHANGELOG.md` — entrada [0.9.9] detallada
- `tests/integration/test_mem_delete_e2e.py` — **NOU** 8 tests Qdrant real + fastembed real
- `core/endpoints/tests/test_rag_sanitization.py` — 4 tests nous cobreix tags MEM

### Diari
- `diari/2026-04/20260415/20260415_bug18_auditoria.md` — **NOU** informe Fase 1
- `diari/2026-04/20260415/20260415_bug18_tancament.md` — **NOU** tancament tècnic
- `diari/director/2026-04-15.md` — sessió director (creat al director panorama)
- `diari/TODO-server-nexe.md` — #18 marcat ✅ al top
- `diari/TODO-postrelease.md` — **§2.bis nou** split+rewrite granular delete (post-v1.0)
- `diari/INDEX_DIARI.md` + `diari/director/INDEX_DIRECTOR.md` — noves entrades al top

### Commits dev (8 + 1 diari)

```
958b993 docs(diari): close bug #18 MEM_DELETE + update indices
4ca26c0 chore(release): complete 0.9.9 version bump in pyproject.toml
98dbb29 fix(ui,prompt): strip leaked system markers + enforce atomic MEM_SAVE
683c0fa chore(release): 0.9.9 — bug #18 MEM_DELETE cirurgia
3a0f93b test(memory): e2e integration tests for MEM_DELETE with real Qdrant
a73a34d fix(memory): lower DELETE_THRESHOLD 0.70→0.20 (e2e finding)
088907f feat(memory): clear_all intent with 2-turn confirmation
759eb87 fix(security): neutralize MEM_DELETE/MEM_SAVE tags in RAG content
```

### Commit gitoss
```
36efe53 sync: bug #18 MEM_DELETE cirurgia + bump 0.9.9 (via ship-nexe)
```

## Decisions

- **DELETE_THRESHOLD 0.70 → 0.20** (crida Jordi post-e2e finding) — errar per excés a l'hora d'oblidar és millor UX que deixar fets orfes
- **Opció C install neta v0.9.9** (Jordi) en comptes d'iterar amb dev server — més net, versionat clar sense DMGs homònims
- **`git reset --hard HEAD~1` a gitoss** (autoritzat) per eliminar commit `f516940` erroni fet per cwd confós
- **Arxivar Bug 2 (fets combinats) com a P2 post-v1.0** — mitigació via prompt reforçat ara, split+rewrite de debò després (TODO-postrelease §2.bis)
- **Sync només (sense DMG)** — Jordi ho farà més endavant quan llenci

## Problemes

- **Edit tool no persistí canvis al `pyproject.toml`** al Commit bump 683c0fa — retornava "updated successfully" però al disc seguia 0.9.8. Resolt amb `sed` + commit fix `4ca26c0`. Origen desconegut (possible cache/hook). Com a lliçó: `diff -q` després del bump general per validar coherència abans de commitejar.
- **Commit accidental a gitoss** (`f516940`) per fer `cd` a gitoss i no tornar al dev. Resolt amb reset. Lliçó: mai deixar el cwd en gitoss després de verificacions; recuperar sempre amb `cd /Users/jgoy/AI/nat/dev/server-nexe` abans d'operacions git destructives.
- **`.gitignore` bloca `diari/` al gitoss** — `ship-nexe.sh` ha fet `git add` sense `-f` i ha fallat. Completat manualment amb `git add -f`. **Millora suggerida a ship-nexe.sh**: afegir `-f` pels paths de `diari/` quan formin part de `.gitoss-sync`.

## Canvis per gitoss

Ja sincronitzat via `ship-nexe.sh --go --no-dmg`:
- `core/endpoints/chat_sanitization.py` — modificat (sync)
- `plugins/web_ui_module/core/memory_helper.py` — modificat (sync)
- `plugins/web_ui_module/api/routes_chat.py` — modificat (sync)
- `plugins/web_ui_module/ui/app.js` — modificat (sync)
- `personality/server.toml` — modificat (sync)
- `pyproject.toml` — modificat (sync)
- `plugins/mlx_module/module.py` + 3 plugins — bump 0.9.9 (sync)
- `CHANGELOG.md` — modificat (sync)
- `tests/integration/test_mem_delete_e2e.py` — **NOU** (pendent classificar a `.gitoss-sync` si no hi és ja a `[sync] tests/` glob)
- `diari/**` — sync forçat manual (ship-nexe `git add` sense `-f` falla pel `.gitignore` de gitoss)

**Cap fitxer fora d'inventari** detectat pel dry-run. Cobertura OK.

## Estat i pròxims passos

### ✅ Tancat avui
- Bug #18 MEM_DELETE (últim P0 pre-v1.0)
- Sync dev ≡ gitoss (tag `gitoss-sync-20260415n`)
- Versions coherents 0.9.9 a tot arreu
- 4706 tests passed (+12), 11 pre-existing fails (test_root readiness/i18n, no tocat), 0 regressions

### ⬜ Pendent fins v1.0
- Build DMG v0.9.9 notaritzat (`ship-nexe.sh --go` sense `--no-dmg`)
- Install neta M4 Pro amb 0.9.9 per validar empíricament els 2 fixes UX (markers invisibles + MEM_SAVE atòmic)
- Coherència KB↔web (`/coherencia-nexe`)
- CDmon credentials + `/api/messages`
- Posts EN (HN, Discord ×4, HuggingFace)
- 🚀 Release v1.0

### ⬜ Diferit post-v1.0
- Install neta M1 8GB (problemes dependències)
- MEM_DELETE granular split+rewrite (TODO-postrelease §2.bis)
- Endpoints REST `/memory/list` + `/memory/delete/{id}` (G4 P1 auditoria)
- Panel UI "Memòries" amb botó esborrar explícit (G7 P2)
- Audit trail persistent col·lecció separada (G6 P2)

## Referències

- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_bug18_auditoria|Auditoria Fase 1]]
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_bug18_tancament|Tancament tècnic]]
- [[nat/dev/server-nexe/diari/director/2026-04-15|Director 2026-04-15]]
- [[nat/dev/server-nexe/diari/prompts/bug18-mem-delete-20260415/README-bug18-mem-delete|Prompt 3 fases]]
- [[nat/dev/server-nexe/diari/TODO-postrelease|TODO-postrelease §2.bis granular delete]]
