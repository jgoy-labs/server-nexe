---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "1.0"
data: 2026-04-15
id: bug18-tancament-20260415
abstract: "Bug #18 MEM_DELETE tancat — últim P0 pre-v1.0. Cirurgia en 7 commits atòmics: security RAG injection, clear_all 2-torns, threshold 0.70→0.20, tests e2e Qdrant real, bump 0.9.9, client strip markers, prompt atòmic. Validat empíricament a install activa M4 Pro."
tags: [server-nexe, bug18, mem-delete, v099, release, tancament]
chunk_size: 800
priority: P0
project: server-nexe
area: dev
type: sessio
estat: published
lang: ca
author: "Jordi Goy"
---

# Bug #18 tancament — 2026-04-15 vespre

## Context

Últim P0 bloquejador pre-v1.0. Els fixes parcials del 2026-04-13 (intent detection amb 30+ patrons + pipeline processing streaming/non-streaming) havien establert l'esquelet, però no s'havia validat empíricament i quedaven gaps estructurals. El director d'avui (Opus 4.6 1M context) va fer una revisió completa del codi, detectar 3 gaps P0 + 1 UX P1, i executar la cirurgia.

Referència auditoria: `diari/2026-04/20260415/20260415_bug18_auditoria.md`.

---

## Gaps identificats

| # | Gap | Severitat | Resolució |
|---|-----|-----------|-----------|
| G1 | `"Oblida tot"` triggereja `delete_from_memory("tot")` semàntic → esborra fets aleatoris en comptes de tota la memòria | **P0** | Intent nou `clear_all` amb confirmació 2-torns + `clear_memory(confirm=True)` (que era òrfana) |
| G2 | 100% tests són mocks — feedback BUS v0.9.0 avisa que enganyen | **P0** | 8 tests e2e amb Qdrant embedded + fastembed real |
| G3 | `_filter_rag_injection` NO cobreix `[MEM_DELETE:…]` ni `[MEM_SAVE:…]` — document maliciós pot fer que l'LLM copiï un tag i el pipeline l'executi | **P0 seguretat** | 4 patrons injection nous (MEM_DELETE, MEM_SAVE, OLVIDA/OBLIT/FORGET, MEMORIA) |
| UX-1 | Tags `[MODEL:nexe-system]` i `[DEL:N:…]` visibles al chat quan la resposta és no-streamed | P1 | Strip centralitzat a `renderMarkdown` (single source of truth) |
| UX-2 | Model combina 2 fets en un sol MEM_SAVE → delete parcial esborra tots dos | P1 (mitigat) / P2 (real) | 6 prompts `server.toml` reforçats amb "REGLA ATÒMICA" + exemples correctes. Split+rewrite post-v1.0 a TODO-postrelease §2.bis |

---

## Descobriment empíric crític: DELETE_THRESHOLD massa alt

Primer run de tests e2e (threshold 0.70 per defecte): 1/8 fails.

```
AssertionError: nothing deleted: {'success': True, 'deleted': 0, ...}
```

Text guardat: `"L'usuari es diu Jordi i viu a Barcelona"`
Query: `"es diu Jordi"` → score < 0.70 → **0 matches**

Amb threshold 0.55 tampoc — fins i tot el verbatim delete no arribava. Jordi decisió: **0.20** per garantir que forget realment oblida. Tradeoff acceptat: delete pot agafar fets loosely related, però és millor UX per a un primitiu "forget" errar per excés que deixar fets orfes.

**Sense aquest test e2e real, aquest bug hauria arribat a producció**. Confirmat exactament el feedback BUS v0.9.0 ("mocks enganyen").

---

## Cadena de commits

```
4ca26c0 chore(release): complete 0.9.9 version bump in pyproject.toml
98dbb29 fix(ui,prompt): strip leaked system markers + enforce atomic MEM_SAVE (#18 follow-ups)
683c0fa chore(release): 0.9.9 — bug #18 MEM_DELETE cirurgia
3a0f93b test(memory): e2e integration tests for MEM_DELETE with real Qdrant (#18 P0)
a73a34d fix(memory): lower DELETE_THRESHOLD 0.70→0.20 (#18 P0 e2e finding)
088907f feat(memory): clear_all intent with 2-turn confirmation (#18 P0)
759eb87 fix(security): neutralize MEM_DELETE/MEM_SAVE tags in RAG content (#18 P0)
```

---

## Tests

- Baseline complet: **4706 passed** (+12 vs abans), 11 pre-existing fails (test_root readiness, i18n init — no tocat)
- E2E integració (`-m integration`): **8/8 passed** en ~5s amb Qdrant real
- Test unit específics del #18: **71/71 passed** a `test_memory_delete.py`

---

## Validació empírica (install activa v0.9.8 — smoke abans dels commits 98dbb29/4ca26c0)

Jordi va provar amb la install activa M4 Pro el cicle:
1. Save `"Em dic Aran i tinc 8 anys"` → guardat (model combinat — veure UX-2)
2. List `"Què recordes de mi?"` → mostrat
3. Delete `"Oblida que tinc 8 anys"` → **esborrat amb score=0.56** ← amb threshold 0.70 original això hauria fallat silenciosament
4. List confirmació → buida

**Log servidor:**
```
Deleted memory entry 11d8582442a76103 from personal_memory (score=0.56): L'usuari es diu Aran i té 8 anys.
```

La troballa del threshold 0.70→0.20 és la que ha fet funcionar aquest cas. Sense ella, "Oblida que tinc 8 anys" hauria retornat `deleted=0` i l'usuari s'hauria quedat amb el fet intacte.

---

## Pendent per la següent install

- `/sincro-nexe` → sync dev→gitoss + DMG v0.9.9 notaritzat
- Install neta M4 Pro (la que hi ha ara és v0.9.8, no té els commits 759eb87+)
- Validar 9 escenaris (save/list/delete/clear_all-pending/clear_all-confirm/injection) amb la UI neta
- Verificar tags `[MODEL:…]` ja NO visibles (fix 98dbb29)
- Verificar model emet MEM_SAVE atòmic (prompt reforçat)

---

## Camí a v1.0

- ✅ 22/22 bugs del checklist 2026-04-13
- ✅ #18 MEM_DELETE tancat (7 commits)
- ⬜ Install neta v0.9.9 M4 Pro validada
- ⬜ Install neta M1 8GB (diferida — deps)
- ⬜ Coherència KB↔web (`/coherencia-nexe`)
- ⬜ CDmon creds + `/api/messages`
- ⬜ Posts EN (HN / Discord / HF)
- ⬜ **🚀 Llançar v1.0**

---

## Referències

- Auditoria formal: `diari/2026-04/20260415/20260415_bug18_auditoria.md`
- Prompt sessió: `diari/prompts/bug18-mem-delete-20260415/`
- Director sessió: `diari/director/2026-04-15.md`
- TODO post-release §2.bis (split+rewrite granular delete): `diari/TODO-postrelease.md:150`
