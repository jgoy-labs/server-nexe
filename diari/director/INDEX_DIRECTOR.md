---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "v1.0"
data: 2026-03-29
id: director-server-nexe-index
abstract: "Index de sessions del director per server-nexe"
tags: [director, server-nexe, index]
chunk_size: 800
priority: P2
project: server-nexe
area: dev
type: index
estat: published
lang: ca
author: "Jordi Goy"
---

# Director server-nexe — Index

## Sessions

- [[nat/dev/server-nexe/diari/director/2026-04-15|2026-04-15]] — **B.1 pre-warm + UI fixes + VLM Gemma-4 + DMG v0.9.8 + install M4 validada + #18 MEM_DELETE TANCAT (Opus 4.6 1M, 7 commits, descoberta empírica threshold 0.70→0.20).** M1 diferit (deps). Pendent sync+DMG v0.9.9 + install neta final → v1.0.
- [[nat/dev/server-nexe/diari/director/2026-04-14|2026-04-14]] — **Dia maratonià: 21/22 bugs tancats**. 40 commits installer/RAG matí + verificació manual + 11 commits nit pel bug #16 (tancat per arquitectura: pre-compute KB al build, 14.55s → 1.36s en M4 Pro, 10.7× speedup, RSS 3.6→2.8 GiB, 1643 tests, 0 regressions). Només queda #18 MEM_DELETE (diferit). Demà: gitoss + DMG + install neta M4/M1 → atacar #18.
- [[nat/dev/server-nexe/diari/director/2026-04-13|2026-04-13]] — **22 bugs instal·lació neta v0.9.7**: testing manual complet, 4 àrees (installer/memòria/UI/core), 6 commits, 22/22 verificats. Pendent: DMG rebuild + reprovar un per un.
- [[nat/dev/server-nexe/diari/director/2026-04-12|2026-04-12]] — **Dia complet (7 sessions)**: v0.9.1 release + v0.9.2 P1 security + fastembed + 4 fixes + merge multimodal VLM (4 backends, 34 tests). Pendent: commit merge + tests live + push.
- [[nat/dev/server-nexe/diari/director/2026-04-11|2026-04-11]] — **Pla v2.4 + Release v0.9.1**: mega-consultoria Opus executada (NO-GO, 3 P0), pla v2.4 aprovat per Jordi (B1 lock pragmàtic, P1-3/P1-5 diferits), 10 fixes aplicats, release commit ccae217. Gitoss/DMG/push pendents.
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_director_mega_consultoria_real|2026-04-11 matí]] — **Mega-consultoria real v0.9.0**: prompt Opus creat, 9 fases normals + annex red-team 10 proves
- [[nat/dev/server-nexe/diari/informes/consultoria-2026-04/resultat_cirurgia_2026-04-07|2026-04-07]] — **Cirurgia post-BUS Fix-All** (sessió `🧠 server-nexe cirugia`): 5 fases Q1-Q5 + Q3.1, 14 findings Codex+Gemini tancats, 17 commits dev + 1 commit gitoss squashed (`fbedc07`), 4434 tests passed, 0 regressions reals, sync gitoss exhaustiu, NO push (espera revisió manual).
- [[nat/dev/server-nexe/diari/director/2026-04-06|2026-04-06]] — Preparació test DMG v0.9.0 post-HOMAD 27 bugs. Prompt 4 fases: build no-notarize → test portàtil → notarització → push.
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_director_sync_mem_delete|2026-04-01 (vespre)]] — Sync 3 còpies divergents + HOMAD MEM_DELETE + BUS prompt creat
- [[nat/dev/server-nexe/diari/director/2026-04-01|2026-04-01]] — Release v0.9.0 FINAL: 5 UX features + 3 memory fixes + audit + push. Prompt multi-fase creat.
- [[nat/dev/server-nexe/diari/director/2026-03-31|2026-03-31]] — BUS fixes + v0.9.0: 3 bugs (installer venv, GPT-OSS thinking, SEC-002) + tests false positives + version bump
- [[nat/dev/server-nexe/diari/director/2026-03-29|2026-03-29]] — Planificacio sessio nocturna: Qdrant embedded + arquitectura memoria (8 fases, ~10h)

## Referències (mapes de context per àrea)

- [[nat/dev/server-nexe/diari/director/REF-memoria-qdrant-v1|REF-memoria-qdrant-v1]] — Memòria persistent + Qdrant embedded: font de veritat, decisions v1, 8 fases, documents clau
