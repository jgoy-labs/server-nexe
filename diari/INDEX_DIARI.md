---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "v1.0"
data: 2026-03-23
id: server-nexe-index-diari
abstract: "Index del diari de server-nexe dev"
tags: [nexe, diari, index]
chunk_size: 800
priority: P2
project: server-nexe
area: dev
type: index
estat: published
lang: ca
author: "Jordi Goy"
---

# Diari server-nexe (dev) - Index

#index #diari #nexe

Amunt: [[nat/dev/server-nexe/index_server-nexe|Index server-nexe]]

---

## Tasques pendents

[[nat/dev/server-nexe/diari/TODO-server-nexe|TODO-server-nexe]]

---

## Sessions
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_director_session_bug18|🎬 Director sessió Opus 4.6 (vespre) — cirurgia #18 completa: auditoria + 8 commits + 2 fixes UX + sync gitoss. Resum executiu consolidat.]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_bug18_tancament|🎯 Bug #18 MEM_DELETE tancat — últim P0 pre-v1.0. 7 commits atòmics: security RAG injection, clear_all 2-torns, threshold 0.70→0.20 (e2e finding), tests e2e Qdrant real (8/8), bump 0.9.9, client strip markers, prompt atòmic. 4706 tests, 0 regressions.]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_bug18_auditoria|🔬 Bug #18 Auditoria Fase 1 — inventari, matriu gaps P0/P1/P2, GO Fase 2]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_vlm_gemma4_streaming|🎯 VLM Gemma-4 end-to-end: detector robust + mlx-vlm 0.4.4 + streaming + bump 0.9.8 + Gemma-4 oficials + fix system prompt/MEM_SAVE + Nexe.app duplicació documentada. 12 commits, 4 syncs gitoss, install neta validada text+imatge+streaming+memòria.]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_installer_3_backends_engine_switching|🔧 Installer: 3 backends conviuen al mateix install (llama-cpp-python sempre, APPROVED_MODULES amb els 3, tomllib, skip→detecta Ollama, auto-discover storage/models/, readiness engines opcionals). 6 commits atòmics.]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_b2_sync_dmg_notaritzat|🔄 B.2 Sync massiu 6 tags (b→f) + notarització desbloqueada (403 acord caducat) + fix installer backends + fix readiness. Finder crash investigar.]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260415/20260415_b1_prewarm_ui_fixes|⚡ B.1 pre-warm fastembed al lifespan (startup ràpid) + 4 UI fixes: mida RAM dropdown, imatge inline chat, preview bar alineada. DMG v0.9.8 sincronitzat.]] (2026-04-15)
- [[nat/dev/server-nexe/diari/2026-04/20260414/20260414_gitoss_bug16_dmg_rebuild|🔄 Sync bug #16 a gitoss (26 fitxers, embeddings 2.8MB) + fix fals positiu NexeTray entitlements (macOS 26 `:-` deprecation) + re-fix pipefail + DMG rebuild net 27MB notaritzat. Tags o/p/q.]] (2026-04-14/15)
- [[nat/dev/server-nexe/diari/2026-04/20260414/20260414_bug16_tancament|🚀 Bug #16 tancat per pre-computació: ingest KB 14.55s → 1.36s (10.7×) — 11 commits, SSOT IngestConfig, harness bench, precompute_kb + CI + pre-commit hook — darrer P2 pre-v1.0]] (2026-04-14/15)
- [[nat/dev/server-nexe/diari/2026-04/20260414/20260414_dock_login_installer_fixes|🎯 Sessió installer complet — 40 commits: Dock, triangle, signing, catàleg unificat, RAG ingest — pre-release ready]] (2026-04-14)
- [[nat/dev/server-nexe/diari/2026-04/20260414/20260414_dmg_release_gitoss_sync|📦 DMG release v0.9.7 notaritzat (25MB, Accepted) + verificació sync gitoss (ja sincronitzat, cap canvi des 13 abril)]] (2026-04-14)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_gitoss_sync_fixes_bcd|🔄 Gitoss sync fixes B/C/D — 24 fitxers (memòria, RAG, i18n, VLM, versions). Tag gitoss-sync-20260413e. Push pendent.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_director_bugs_installacio_neta|🎬 Director: 22 bugs instal·lació neta v0.9.7 — testing manual complet, 4 àrees, 6 commits, tots verificats contra codi. 22/22 arreglats.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_fix_area_d_core_backend|🔧 Fix Àrea D Core & Backend — 2 bugs: VLM passthrough llama_cpp (bifurcació estil MLX) + versions hardcoded centralitzades (core/version.py). 884/0 tests.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_fix_area_c_ui_i18n|🌐 Fix Àrea C UI/i18n — 8 bugs: 5 hardcodes i18n, mida model ollama ps, upload/summarize i18n, strip [MODEL:] tags. 510/0 tests.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_fix_area_b_memoria_rag|🧠 Fix Àrea B memòria+RAG — 5 bugs: MEM_DELETE intent P0, knowledge re-ingest, RAG logging, source attribution, batch embedding. 4648/0 tests.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_fix_8bugs_installacio_neta|🐛 Fix 8 bugs instal·lació neta v0.9.7 — readiness UNHEALTHY→DEGRADED (P0), countdown wizard, Dock path, /Applications default, ram_gb, tier centrat, logo SVG. 4635/0 tests.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_knowledge_docs_millores|📝 Knowledge docs millores — MEM_SAVE diagrama, custom models, master key migració, design intent honest 😵‍💫]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_coherencia_knowledge|🔬 Coherència knowledge v0.9.7 — 2 passades, 39 fitxers corregits (versió, multimodal, fastembed, encryption default). PASS ✅]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_vlm_fixes_multimodal|🎥 VLM fixes multimodal — 4 bugs resolts (upload routing, drag&drop, bytes→b64, payload Ollama). Tray versió, prompts idioma. 7 commits.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_gitoss_sync_v097|🔄 Gitoss sync v0.9.7 — 25 fitxers, 4 test_multimodal.py nous, 34/34 tests OK. Tag gitoss-sync-20260413a. Push pendent.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260413/20260413_gitoss_sync_v097|🔄 Gitoss sync v0.9.7 — 25 fitxers, 4 test_multimodal.py nous, 34/34 tests OK. Tag gitoss-sync-20260413a. Push pendent.]] (2026-04-13)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_merge_multimodal_vlm_v097|🎥 Merge multimodal VLM + v0.9.7 — Merge quirúrgic 4 backends, botó càmera UI, mlx-vlm instal·lat, bump 0.9.7, fix 5 tests memory/ SQLite. 4630/0 tests.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_merge_multimodal_vlm|🎥 Merge multimodal VLM — Merge quirúrgic plugins-nexe→server-nexe: imatges 4 backends, botó càmera UI, 34 tests nous, 1485/0 tests. P1+fastembed+think:true intactes.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_verificacio_fastembed|🔍 Verificació fastembed — cleanup stale refs (7f), health check device (torch→onnxruntime), test UI MEM_SAVE re-prompt OK. 3 commits, 1022/0 tests.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_fix_fastembed_model_name|🎬 Director vespre: 4 fixes — fastembed model name, install log, think:true Ollama, re-prompt MEM_SAVE buit. 8 fitxers, 4603/0 tests.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_gitoss_sync_v093|🔄 Gitoss sync v0.9.3 — fix test fastembed, COMMANDS.md publicat, .gitignore corregit, InstallNexe.app exclòs. Tag gitoss-sync-20260412c.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_fastembed_migration|⚡ fastembed migration — sentence-transformers → fastembed (ONNX), SSOT centralitzat, PyTorch eliminat (~600MB), 30 fitxers, 4581/0 tests, 5 commits.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_p1_security_fixes_v092|🔒 P1 Security Fixes v0.9.2 — 4 P1 mega-consultoria tancats (rate limit, symlink, encryption auto, auth logging), 24 tests nous, 4581/0, push + release v0.9.2 GitHub]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260412/20260412_director_release_v091|🚀 Release v0.9.1 completa — Director: gitoss sync, 4572/0 tests, smoke 5/5, DMG 24MB notaritzat, knowledge coherence 36 fitxers, Docker eliminat, README-ca.md, historial git netejat, release GitHub publicada. Skill /coherencia-nexe creat.]] (2026-04-12)
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_director_coherencia_postbusdevacances|🔧 Director coherència post-BUS vacances — path gitoss corregit, 5 backups arxivats, 11 ítems TODO-prerelease marcats RESOLT, INDEX_DIARI 13 entrades, 319 fitxers diari commitats.]] (2026-04-11)
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_gitoss_sync_v091|🔄 Gitoss sync v0.9.1 — 19 fitxers copiats, 11 artefactes test eliminats del repo públic, tag gitoss-sync-20260411c. Push pendent.]] (2026-04-11)
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_mega_consultoria_fixes_v091|🚀 Release v0.9.1 — Cicle complet: mega-consultoria Opus (NO-GO, 3 P0) → pla v2.4 (Jordi aprova) → 10 fixes (P0-1/2/3 + P1-1/2/4) → release commit ccae217. Gitoss/DMG/push pendents.]] (2026-04-11)
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_nexeapp_v1_pla|📐 NexeApp v1 — Pla detallat: SwiftUI app nativa (WKWebView + NSStatusItem) que substituirà NexeTray Python. installer/NexeApp/. DESBLOCAT post-cirurgia v0.9.1.]] (2026-04-11)
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_director_mega_consultoria_real|🎬 Director — Mega-consultoria real: prompt Opus creat (9 fases normals + annex red-team 10 proves) + pla v2.4 aprovat (B1 lock, P1-3/P1-5 diferits). Servidor test ~/server-nexe/.]] (2026-04-11)
- [[nat/dev/server-nexe/diari/2026-04/20260411/20260411_nexeapp_sessio_homad|📐 NexeApp HOMAD — Decisió: SwiftUI WKWebView nativa, centralitzada. Cap codi creat. Tot pendent activació post-cirurgia v0.9.1. ⚠️ CONSULTAR Jordi: fastembed swap + mecanisme descàrrega models.]] (2026-04-11)
- [[nat/dev/server-nexe/diari/2026-04/20260410/20260410_installer_go_primera_instalacio_neta|✅ Installer GO — Primera instal·lació neta completa: venv, deps, config, Qdrant, embeddings, knowledge, memòria. 9 bugs resolts. DMG funcional.]] (2026-04-10)
- [[nat/dev/server-nexe/diari/2026-04/20260410/20260410_sessio_dmg_installer_bugs|🔧 Sessió debug DMG+installer: 8 bugs resolts en cadena (models.json format, sense model hang, background Sequoia, NexeTray payload, knowledge wipe, tar --overwrite). DMG 24MB notaritzat. Quasi.]] (2026-04-10)
- [[nat/dev/server-nexe/diari/2026-04/20260410/20260410_fix_reinstall_false_positive|Fix P0 reinstall fals positiu: _is_project_root_running_bundle usava __file__ via PYTHONPATH. Wizard 0% bloquejat en reinstal·lació. 282e470.]] (2026-04-10)
- [[nat/dev/server-nexe/diari/2026-04/20260410/20260410_fix_installer_hang_continuar_sense_model|Fix P0 SwiftUI hang 0%: guard silencies InstallerEngine + _update_env_model_config TypeError. 4485 tests +6.]] (2026-04-10)

- [[nat/dev/server-nexe/diari/2026-04/20260410/20260410_models_storage_cont|📦 Models storage cont. — maverick 244GB esborrat, snapshots TM purgats, SSD 130GB lliure (93%). MLX download pendent.]] (2026-04-10)
- [[nat/dev/server-nexe/diari/2026-04/20260410/20260410_fix_dmg_models_installer_sense_model|🔧 Fix P0 DMG: models.json sobreescrit format antic (export_catalog_json) + crash install_headless sense model (model_config=None). 3 fitxers, 2 commits, DMG notaritzat OK.]] (2026-04-10)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_fix_installer_models_json|🔧 Fix P0 Installer: ModelCatalog.swift alineat amb models.json (mlx Bool, role, iberic). Botó continuar sense model. Build OK, 4479 tests intactes.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_models_gestio_storage|📦 Models & Storage — models.json corregit (tags inexistents eliminats, backends afegit), symlink → Wintermute, Ollama 681GB verificat, mlx-download.sh creat, pla alliberació ~58GB SSD.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_cirurgia_run2_F1_F7|⚕️ Cirurgia Run 2 F1-F7 — memory_action inline, NEXE_SERVER_PORT env, rate limit doc, CLI stop PID file, get_i18n unificació, headless tray doc, MLX doc. 4479 tests (+19), 0 regressions.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_mega_test_area19_stress_gpu|🧪 Mega-Test Àrea 19 — Stress GPU execució real. 13 blocs A-M ✅. Tier 128GB, port 9120. MLX incompatible (gemma4/VLM). 3 forats prompt. Sec offensive OK. Report complet.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_cirurgia_dmg_rebuild|✅ Dev 6/6 — DMG Rebuild: B11-B14 tancats. installer_setup_qdrant ABSENT. 19MB signat Apr 9 al Desktop. Cirurgia completa. 4460 tests.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_cirurgia_p1s|✅ Cirurgia P1s — XSS app.js (I57/I62), CLI alias knowledge (I26), models.json tier (I24). I23 ja fix. 4460 tests, commit 2c79b90.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_cirurgia_bloc_f_n01_n02_sc04_sc08|✅ Cirurgia Bloc F — N02 atribució IA, SC04 NexeTray bundle, SC08 i18n.set_language. 4460 tests (+25), commit 00624e5.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_cirurgia_bloc_b_lifespan|✅ Cirurgia Bloc B — Core Lifespan + PID: B06 B07 B09 B10 B15 N03 N04 N05. 4448 tests, 0 regressions.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_mega_test_run_complet_no_go|❌ Mega-Test Run 20260408-1 COMPLET — NO-GO v0.9.0. 20/22 àrees, 48 sessions agents, 17 BLOCKERs P0, 10 findings cross-àrea. Cirurgia 7 blocs pendent. Briefing complet proper Director.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260409/20260409_mega_test_fase3_run_20260408-1|🧪 Mega-Test Fase 3 RUN 20260408-1 — D1+D2+D3 completats (11 àrees + auditors). 10 BLOCKERs P0 documentats. Àrea 22 apartada. Decisió D4 vs cirurgia pendent demà.]] (2026-04-09)
- [[nat/dev/server-nexe/diari/2026-04/20260408/post-merge-revisio-creuada|✅ Revisió creuada final v2 — tots blockers NO-GO anteriors resolts. ~/server-nexe/ arxivat. GO per Fase 3 Mega-Test.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/dev-fixes-post-merge-informe|🔧 4 fixes post-merge (c926555): NexeSettings Item 15, tray template=True, knowledge drift Q5.5, 71 failures venv. Tests verds.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/post-merge-bloc1-auditor|🔍 Post-Merge Auditor Bloc 1 — AMB RESERVES: 100 fitxers sense commitarlar + 71 tests fallen. Funcionalitat OK.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/merge-repos-informe|🔀 Merge Bloc 1+3 (~/server-nexe/) al canònic (nat/dev/server-nexe/). 560 tests verds. ~/server-nexe/ arxivat.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc3-auditor-dictamen|🔍 Dictamen Auditor Bloc 3 — Installer, Models & Arquitectura]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc3-dev-pla|📋 Pla Cirurgia Bloc 3]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc2-auditor-dictamen|🔍 Dictamen Auditor Bloc 2 — Security & Memory Pipeline]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc2-dev-pla|📋 Pla Cirurgia Bloc 2]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc1-dev-informe|⚕️ Cirurgia Bloc 1 Dev — Tray & Lifecycle: 8 items resolts, 310 tests green, 0 failed, 5 passades netes.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc1-auditor-dictamen|🔍 Dictamen Auditor Bloc 1 — Tray & Lifecycle: 8/8 items ✅ CONFIRMAT (+ 2 alertes resoltes post-dictamen).]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc1-dev-pla|📋 Pla Cirurgia Bloc 1]] (2026-04-08)
- [[nat/dev/server-nexe/diari/informes/consultoria-2026-04/proves_intensives_2026-04-10|🧪 Proves intensives reals 2026-04-10 — instal·lació DMG v0.9.0 end-to-end: chat, memòria, RAG, documents, esborrat. STOPPER superat.]] (2026-04-10)
- [[nat/dev/server-nexe/diari/2026-04/20260408/post-merge-bloc3-auditor|🔍 Auditoria post-merge Bloc 3 — ❌ NO CONFORME: Item 15 (NexeSettings) absent del codi (informe dev incorrecte), Bloc 3 sense commit al git. 2 crítics, 2 alertes, 9 checks OK.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/post-merge-bloc2-auditor|🔍 Auditoria post-merge Bloc 2 — 10/10 checks OK (is_mem_save, strip_memory_tags, _filter_rag_injection, SQLCIPHER fail-closed, workflows stub 501, pipeline únic). 458 passed, 1 falla pre-existent aïllació logging. CONFORME.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc3-dev-informe|⚕️ Cirurgia Bloc 3 — Installer, Models & Arquitectura: 7 items resolts (knowledge drift 18 hits, 7 tiers RAM 27 models, QdrantAdapter 9/10 imports eliminats, pydantic-settings registry, items 3/4/6 ja implementats). 412 tests verds.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/cirurgia-bloc2-dev-informe|⚕️ Cirurgia Bloc 2 — Security & Memory Pipeline: 6 items resolts (MEM_SAVE funcional, pipeline únic, fail-closed SQLCIPHER, strip_memory_tags API, _filter_rag_injection ingest, workflows stub 501). 458 tests verds.]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_repas_mega_test_complet_22_22_vigilant|🎯 Repàs mega-test COMPLET 22/22 (vigilant) — 25 BLOCKERs P0 descoberts pre-execució (24 vius al TODO-installer-prerelease, item 23 RESOLT per item 24), 4 decisions Jordi totes resoltes (18 substituïble Qdrant pre-release, 21 SQLCIPHER fail-closed, 24 pipeline únic eliminar plugin endpoints, §3.5 IDENTITY excepció), REGLES-ABSOLUTES v1.6 (REGLA 12 PERMANENT skill /hacker), pipeline únic CLI↔UI confirmat triplement empíricament, HANDOFF-CONTINUACIO doc creat. Llest per compactar i cirurgia post-mega-test]] (2026-04-08 nit tancament)
- [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_director_repas_continuacio_mega_test|🏁 Director Repàs Continuació — mega-test àrees 15-21 escrites (100% repàs principal). Pipeline únic CLI/UI confirmat, workflow engine futur PENDENT, sec offensive sota stress, Bloc H "aspectes no clars". Tancament.]] (2026-04-08 nit)
- [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_pre_megaauditoria_estat_post_refactor|🎯 Pre-mega-auditoria — síntesi del director-pont: refactor B.0-B.8 100% complet, 22 àrees del mega-test pendents d'execució per validar el sistema viu, push/notarització Apple post-auditoria]] (2026-04-08 vespre)
- [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_tancament_refactor_b4_b8|🏁 Tancament refactor B.4-B.8 — neteja storage + reset + smoke runtime PASSED + sync gitoss massiu (a30225c) + DMG signat 19MB al Desktop. Refactor 100% complet. Push i notarització pendents]] (2026-04-08 tarda)
- [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_refactor_b3bc_tests_docs|🧠 Refactor B.3.b+B.3.c — 18 fitxers tests + docs knowledge multilingüe (commit 8439326) + neteja frontmatter knowledge 27 fitxers (commit 0c9e9c4). pytest 4433 passed]] (2026-04-08 tarda)
- [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_investigacio_memoria_pre_refactor_personal_memory|📐 Investigació memòria pre-refactor personal_memory — MAPA_MEMORIA 1200L + 3 revisions creuades + commit a8120ac + tag baseline-pre-personal-memory-20260408 + fix col·lateral .gitignore path uploads]] (2026-04-08)
- [[nat/dev/server-nexe/diari/informes/MAPA_MEMORIA_2026-04-08|🗺️ MAPA MEMÒRIA 2026-04-08 — document de referència: 12 seccions, metàfora biblioteca-passadissos, 4 subsistemes paral·lels, bugs N1 DreamingCycle + N2 GCDaemon, 28 fitxers refactor + 82 matches]] (2026-04-08)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_cirurgia_tancament_sessio|🛌 Tancament sessió cirurgia post-BUS — codi estable, sync gitoss net, esperant tests contra servidor real]] (2026-04-07 nit)
- [[nat/dev/server-nexe/diari/informes/consultoria-2026-04/resultat_cirurgia_2026-04-07|📋 INFORME CIRURGIA POST-BUS — 14 findings Codex+Gemini tancats, 17 commits dev, 1 commit gitoss squashed (fbedc07), 4434 passed, NO push]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_cirurgia_Q5_higiene|⚕️ Cirurgia Q5 — Higiene ruff 102→40 (-61%) + DELETE module_loader/container + 3 tests obsolets]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_cirurgia_Q4_xarxa|⚕️ Cirurgia Q4 — Centralització xarxa (19 hardcodes 9119/127.0.0.1 → core.config + NEXE_SERVER_HOST/PORT env)]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_cirurgia_Q3_i18n|⚕️ Cirurgia Q3 — i18n bypass cleanup (17 calls a 6 fitxers, get_i18n Dependency)]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_cirurgia_Q2_hardening|⚕️ Cirurgia Q2 — Hardening seguretat (auth bypass FAIL CLOSED, producció, /status auth, IP whitelist)]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_cirurgia_Q1_trivials|⚕️ Cirurgia Q1 — Trivials risc 0 (F821 logging, mlx Path.cwd)]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260407/20260407_bus_fix_all|🛠️ BUS Fix-All: 11 bugs + 7 findings tancats en 7 commits (Track A/B/C). F8 era VIU (root cause Bug #4: 2 QdrantClients reals). Bug #6 era 2 bugs encadenats. Tests 4424/0/35 (+28 nous), 0 regressions]] (2026-04-07 matinada)
- [[nat/dev/server-nexe/diari/plans/PLA-BUS-FIX-ALL-2026-04-07|📋 PLA BUS Fix-All — disseny 3 tracks paral·lels, auditors 3 passades, sense HOMAD Gemini/Codex]] (2026-04-07)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_test_postbus_qa_session|🧪 QA test manual post-BUS + investigació autònoma 30min: 10 bugs (3 P0), 6 findings F-x memory/RAG, BUS sense regressions, CLI↔UI pipeline confirmat]] (2026-04-06 nit)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_bus_normalitzacio_sync_gitoss|🔌 BUS Normalització pre-release plugins + sync dev→gitoss (segon del dia, post-HOMAD): 5 plugins normalitzats, ollama 510→192L, tests 4396/0/35, commit gitoss 5a9282f]] (2026-04-06 tarda/nit)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_bus_normalitzacio_prerelease|🔌 BUS Normalització pre-release (cronologia exhaustiva: Fases 0-6, peloteo HOMAD Gemini/Codex)]] (2026-04-06 tarda/nit)
- [[nat/dev/server-nexe/diari/2026-04/20260406/INFORME-ESTAT-server-nexe-v090-20260406|📋 INFORME ESTAT v0.9.0 — traspàs per nova sessió test DMG local (còpia també a ~/Desktop/)]] (2026-04-06 nit)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_sync_dev_gitoss_v090|🔄 Sync dev→gitoss v0.9.0 (v1.1): 4 commits dev + 5 commits gitoss (1+4 correctius), lliçó apresa diff -rq exhaustiu]] (2026-04-06)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_homad_sessio_completa_27_bugs|🏆 HOMAD sessió completa v0.9.0: 27 bugs tancats (3 blocs), 201 tests, 4389 passed, GO]] (2026-04-06)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_fix_bloc3_v090|Bloc 3 v0.9.0: 11 bugs baixa (log noise, coherence, infra) — GO passada 3]] (2026-04-06)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_fix_4_bugs_release_v090|Bloc 1 v0.9.0: 4 crítics (reinstall 3 modes, TOCTOU, DreamingCycle leak, Phi-3.5) — GO passada 3]] (2026-04-06)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_fix_bloc2_v090|Bloc 2 v0.9.0: 12 mitjana (seguretat, concurrència, infra, UX) — GO passada 3]] (2026-04-06)
- [[nat/dev/server-nexe/diari/2026-04/20260406/20260406_homad_triage_bugs_v090_sessio1|HOMAD triage 30 bugs v0.9.0 (sessió inicial)]] (2026-04-06)
- [[nat/dev/server-nexe/diari/2026-04/20260402/20260402_test_instalacio_neta_bugs|Test instal·lació neta: 16 bugs/millores (MEM_DELETE, RAG, i18n, UX, knowledge)]] (2026-04-02)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_director_tray_mlx_fixes|Director: fix symlink models, .env MLX, tray zombie Guard 6 SIGKILL, tray Quit atura servidor]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_bus_mem_delete_sprint1|BUS MEM_DELETE Sprint 1: oblidar amb control, feedback visual, llistat memories — 8 fixes, 29 tests, 32/32 auditoria PASS]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_director_sync_mem_delete|Director: Sync 3 copies divergents + HOMAD MEM_DELETE + BUS prompt creat]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_fix_tray_bloqueig_teclat|Fix crític: tray bloquejava teclat macOS — _RamMonitor background thread, 7 tests, 5 passades]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_dev_ux_polish_hora_caixa_copy|Dev UX Polish: hora system prompt, caixa IA vermell, copy al footer, stats persistents entre reinicis]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_dev_release_v090_ux_bump|Dev: 5 UX features (copy, sidebar, rename, donate, fix X) + version bump 8 fitxers + 3 passades auditoria (12 bugs fixats)]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_director_release_v090_final|Director: Release v0.9.0 final — 5 UX + 3 memory fixes + bump. Prompt creat per /dev a /Users/jgoy/server-nexe/]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_debug_verificacio_mlx_memoria|Debug pre-viatge: fix Qdrant pool zombie, symlink MLX, normalització thinking gpt-oss, MEM_SAVE dins thinking pendent]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-04/20260401/20260401_ui_cleanup_strip_tags_qdrant|UI Cleanup: strip tags model, badge guardado, neteja Qdrant, nexe-system marker, neteja residus MEM_SAVE]] (2026-04-01)
- [[nat/dev/server-nexe/diari/2026-03/20260330/20260330_director_fixes_test_manual|Director: 4 fixes test manual DMG — UI readiness, GPT-OSS tokens, catàleg MLX (QwQ-32B afegit). 4149 tests, 0 regressions]] (2026-03-30)
- [[nat/dev/server-nexe/diari/2026-03/20260330/20260330_bus_fixes_v090|BUS Fixes + v0.9.0: 3 bugs fixats (installer venv, GPT-OSS thinking, SEC-002) + 47 tests nous + version bump. 4077→4149 tests, 129 fitxers]] (2026-03-30)
- [[nat/dev/server-nexe/diari/2026-03/20260330/20260330_bus_memoria_v1_validacio_go|BUS Memoria v1: 3 BUS encadenats — implementacio (4765L) + validacio total (5 Devs, 3 bugs) + fix critical (singleton Qdrant) → GO DEFINITIU]] (2026-03-30)
- [[nat/dev/server-nexe/diari/2026-03/20260329/20260329_arquitectura_memoria_v1|Arquitectura memòria v1: diagnòstic + redisseny complet (6 rondes, 34 consultes, 1258 línies)]] (2026-03-29 tarda)
- [[nat/dev/server-nexe/diari/2026-03/20260329/20260329_fixes_seguretat_ux_qdrant|Fixes: 3 HIGH seguretat, Qdrant zombie cross-install, UI overflow, system prompt multiidioma]] (2026-03-29)
- [[nat/dev/server-nexe/diari/2026-03/20260329/20260329_sessio_nocturna_megatest_fixes|Sessió nocturna: MEGA-TEST v1→fixes→v2 GO. 3 HIGH fixats, 0 failed, 14 fitxers sync]] (2026-03-29 nit)
- [[nat/dev/server-nexe/diari/informes/mega-test-final-2026-03-29-v2/00-INFORME-GO-NOGO-v2|MEGA-TEST v2 post-fixes: GO — 0 failed, 3 HIGH fixats, 7 fixes verificats en viu]] (2026-03-29 nit v2)
- [[nat/dev/server-nexe/diari/2026-03/20260329/20260329_mega_test_final_nit|MEGA-TEST-FINAL nit: 5 fases + servidor viu + 4 passades auditoria. GO AMB CONDICIONS. 3 HIGH seguretat, 227 català, upload bug]] (2026-03-29 nit)
- [[nat/dev/server-nexe/diari/informes/mega-test-final-2026-03-29/00-INFORME-GO-NOGO|Informe GO/NO-GO complet (10 informes detallats)]] (2026-03-29 nit)
- [[nat/dev/server-nexe/diari/2026-03/20260329/20260329_homad_fixes_arrencada_ollama|HOMAD: fixes arrencada, Ollama thinking/ctx, neteja Qdrant, model default phi3:mini]] (2026-03-29)
- [[nat/dev/server-nexe/diari/prompts/INDEX_PROMPTS|Biblioteca de prompts — index comparatiu]] (2026-03-29)
- [[nat/dev/server-nexe/diari/prompts/mega-test-final/MEGA-TEST-FINAL|MEGA-TEST-FINAL v4: 5 fases pre-push (pytest+sync+security+uploads+coherència+GO/NO-GO)]] (2026-03-29)
- [[nat/dev/server-nexe/diari/2026-03/20260328/20260328_auditoria_coherencia|Auditoria coherència: 6 passades, 22 findings (2 CRITIC, 12 ALT), 350+ claims]] (2026-03-28)
- [[nat/dev/server-nexe/diari/2026-03/20260328/20260328_neteja_fix_tray_attach|Neteja processos + fix tray auto-launch (--attach): 2 fitxers, 6 guards, 3969 tests OK, 0 regressions]] (2026-03-28)
- [[nat/dev/server-nexe/diari/2026-03/20260328/20260328_verificacio_pytest_sync_gitoss|Verificació pytest (3969 passed, 0 failed) + sync gitoss→dev 430 fitxers (Cas B), 3 passades OK, tag gitoss-sync-20260328]] (2026-03-28)
- [[nat/dev/server-nexe/diari/20260328_refer_knowledge_base_v085|Refer knowledge base v0.8.5: 36 fitxers (12×3 idiomes) reescrits, "consultoria"→"AI audit", encriptació at-rest, mega-test, rate limiting, diagrames Mermaid, AI-Ready docs, COMMANDS.md]] (2026-03-28)
- [[nat/dev/server-nexe/diari/20260328_fixes_seguretat_mega_test_v2|Fixes seguretat MEGA-TEST v2: 7 findings resolts (NF-001 CRITIC, NF-002 ALT, NF-003/004 MIG, NF-005/006 BAIX, SEC-005) + fix Ollama — 3213 tests, 0 failed]] (2026-03-28)
- Mega-test v2 post-fixes: 10 findings (vs 23 v1, -57%), GO AMB CONDICIONS millorat (2026-03-28)
- Mega-test v1 pre-release: 4 fases, 23 findings (1 CRITIC), 158 tests funcionals, GO AMB CONDICIONS (2026-03-28)
- Fixes pre-release v1 (MEGA-FIX): UI validation, RAG sanitization, rate limiting, log truncation, pipeline consistency (2026-03-28)
- Tray auto-launch des de terminal: mode --attach + _maybe_launch_tray(), 6 guards (2026-03-28)
- [[nat/dev/server-nexe/diari/2026-03/20260328/20260328_verificacio_integracio_crypto|Verificació integració CryptoProvider: 10 punts verificats, tot correcte, TODO actualitzat]] (2026-03-28)
- [[nat/dev/server-nexe/diari/2026-03/20260328/20260328_homad_integracio_encriptacio_lifespan|Integrar encriptacio at-rest al lifespan — CryptoProvider end-to-end, 14 tests nous, 3987 total, 0 regressions]] (2026-03-28)
- [[nat/dev/server-nexe/diari/2026-03/20260328/20260328_fixes_post_megatest_seguretat_ui|Fixes post-MEGA-TEST: seguretat UI — input validation + RAG sanitization, 3973 tests OK, 0 regressions]] (2026-03-28)
- [[nat/dev/server-nexe/diari/20260328_encriptacio_at_rest_opcio_b|Encriptacio at-rest Opcio B: CryptoProvider + SQLCipher + sessions .enc + TextStore RAG — 6 fases, 54 tests nous, 0 regressions]] (2026-03-28)
- [[nat/dev/server-nexe/diari/2026-03/20260327/20260327_consolidacio_passades2_3|Passades 2-3: health helpers, manifest base, deps, traduccio massiva ca→en ~150 fitxers, 80/88 findings]] (2026-03-27 nit 4)
- [[nat/dev/server-nexe/diari/2026-03/20260327/20260327_consolidacio_qualitat_3passades|Consolidacio qualitat: 52 findings en 3 passades — traduccio, dead code, duplicats, error handling]] (2026-03-27 nit 3)
- [[nat/dev/server-nexe/diari/2026-03/20260327/20260327_new001_new002_p1_consolidacio_prep|NEW-001/002 fixes + 4 P1 blocants + Prompts consolidacio auditoria+exec]] (2026-03-27 nit 2)
- [[nat/dev/server-nexe/diari/2026-03/20260327/20260327_test_integracio_fixes_v4|10 bugs arreglats + Test integració v4: 93.5% funcional, 15 models, 0 regressions]] (2026-03-27 nit)
- [[nat/dev/server-nexe/diari/2026-03/20260327/20260327_knowledge_systemprompt_update|Knowledge base completa (36 fitxers) + System prompt reescrit + Fix RAG labels i18n]] (2026-03-27)
- Sync dev→gitoss: MEM_SAVE + documents per-sessió + upload overlay + IDENTITY knowledge — 11 fitxers, sense push (2026-03-26 nit 3)
- [[nat/dev/server-nexe/diari/2026-03/20260326/20260326_test_memsave_bugfixes|Test MEM_SAVE live + 4 bugfixes + Documents per-chat]] (2026-03-26 nit 2)
- [[nat/dev/server-nexe/diari/2026-03/20260326/20260326_memoria_automatica|Memoria Automatica via LLM (MEM_SAVE) + fixes memoria/RAG]] (2026-03-26 nit)
- [[nat/dev/server-nexe/diari/2026-03/20260326/20260326_rag_i18n_ollama_backend|RAG + i18n + Ollama auto-start + Backend fallback]] (2026-03-26 tarda)
- [[nat/dev/server-nexe/diari/20260326_ux_fixes_model_loading|UX fixes post-instalacio + indicador carrega model (Ollama/MLX/llama.cpp)]] (2026-03-26)
- [[nat/dev/server-nexe/diari/20260325_tech_debt_refactoring_7_blocs|Tech Debt Refactoring: 4 monolits dividits, vector_size centralitzat, i18n — 3901 tests OK]] (2026-03-25)
- [[nat/dev/server-nexe/diari/20260325_resolucio_findings_consultoria_v2|Resolucio findings Auditoria IA v2: 229 tests → 0, 12 findings resolts]] (2026-03-25)
- [[nat/dev/server-nexe/diari/20260325_sync_gitoss_installer|Sync dev→gitoss: installer fixes + 5 fitxers nous]] (2026-03-25)
- Secció Acknowledgments al README gitoss + secció Support/Donate a servernexe.com + GitHub Discussions activat (2026-03-24)
- [[nat/dev/server-nexe/diari/20260324_pre_llancament_neteja|Sprint pre-llancament: CI fix, Linux, Docker, CLI/UI, RAG weights]] (2026-03-24)
- [[nat/dev/server-nexe/diari/20260323_sync_gitoss_release_v082|Sync dev→gitoss + Release v0.8.2]] (2026-03-23)
- [[nat/dev/server-nexe/diari/20260323_fase2_fase3_produccio|Fase 2 + Fase 3: Sprint Tasks crítics + 35 tests arreglats + test en viu amb servidor]] (2026-03-23)
- [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/00-INDEX-RESUM|Auditoria IA v1 completa — 3 passos + implementacio 40 fixes]] (2026-03-22)
- [[nat/dev/server-nexe/diari/20260321_fixes_i_uninstaller|Fixes logger, uninstaller i cataleg models]] (2026-03-21)
- [[nat/dev/server-nexe/diari/20260320_uninstaller_i_millores|Uninstaller complet + anys models + Cancel]] (2026-03-20)
- [[nat/dev/server-nexe/diari/20260320_millores_installer_dmg|Millores installer DMG]] (2026-03-20)
- [[nat/dev/server-nexe/diari/20260319_installer_swiftui_wizard|Installer SwiftUI wizard]] (2026-03-19)
- [[nat/dev/server-nexe/diari/20260319_apple_developer_account|Apple Developer account]] (2026-03-19)
- [[nat/dev/server-nexe/diari/20260318_installer_gui_canvis|Installer GUI canvis]] (2026-03-18)
- [[nat/dev/server-nexe/diari/20260318_git_neteja|Git neteja]] (2026-03-18)

---

## Seccions

| Carpeta | Contingut |
|---------|-----------|
| [[nat/dev/server-nexe/diari/plans/INDEX|plans/]] | Roadmap, plans d'execucio (10 arees + verificacio) |
| [[nat/dev/server-nexe/diari/plans/PLA-QDRANT-EMBEDDED|PLA-QDRANT-EMBEDDED]] | Migrar Qdrant extern→embedded. -65MB, -150 línies, zero zombies. PENDENT. |
| [[nat/dev/server-nexe/diari/informes|informes/]] | Revisions tecniques, audits, estats |
| [[nat/dev/server-nexe/diari/arxiu-historic/INDEX_ARXIU|arxiu-historic/]] | Documentacio historica recuperada de arxiu/ (22 docs: arquitectura, revisions, guies, presentacio, plugins) |

### Informes

- [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/00-INDEX-RESUM|Auditoria IA v1 server-nexe v0.8]] (2026-03-22) — auditoria completa (73 findings, 11 arees) + implementacio (40 fixes, 84 tests arreglats, nota A-)
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/01-seguretat|01 Seguretat]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/02-nucli-fastapi|02 Nucli FastAPI]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/03-chat-streaming|03 Chat i Streaming]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/04-rag-chunking|04 RAG i Chunking]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/05-sessions-context|05 Sessions i Context]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/06-plugins-module-manager|06 Plugins i Module Manager]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/07-instalador|07 Instalador]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/08-desinstalador|08 Desinstalador]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/09-sistema-tray|09 Sistema Tray]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/10-perspectiva-oss|10 Perspectiva OSS]]
  - [[nat/dev/server-nexe/diari/informes/consultoria-2026-03/11-treure-greix|11 Treure Greix]]
- [[nat/dev/server-nexe/diari/informes/20260320_estat_installer|Estat actual installer]] (2026-03-20) — informe complet: wizard, models, DMG, pendents
- [[nat/dev/server-nexe/diari/informes/revisio-tecnica-server-nexe-2026-03-16|Revisio tecnica]] (2026-03-16)

---

## Arxiu Historic

Documentacio historica recuperada de `arxiu/` el 2026-03-23. Material anterior a la fase de correccio de marc 2026.

[[nat/dev/server-nexe/diari/arxiu-historic/INDEX_ARXIU|INDEX_ARXIU]] — Index complet (22 documents: arquitectura, revisions, guies, presentacio, plugins)
