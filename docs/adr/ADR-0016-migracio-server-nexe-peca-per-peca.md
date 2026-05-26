# ADR-0016: Migració server-nexe → Tauri peça per peça amb millores

**Data:** 2026-04-20
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

Fase 0 congelada (`v0.1.0-fase0`, 2026-04-19). Comença el pensament sobre Fase 1 (UI integration) i sobretot Fase 2 (sidecar server-nexe). server-nexe és el backend Python FastAPI/Qdrant/LLM actual amb UI web pròpia (~220K línies).

Hi ha dues estratègies possibles per portar server-nexe al shell Tauri:

**A) Migració 1:1 (lift-and-shift):**
- Copiar UI web existent tal com està (HTML/CSS/JS).
- Spawn del sidecar Python sense canvis.
- Mínim risc, màxima fidelitat al que ja funciona.
- Deute tècnic heretat (codi no revisat en anys).

**B) Migració peça per peça amb millores:**
- Cada component migrat des de server-nexe al shell Tauri passa per una revisió crítica.
- Aprofitem la migració per refactoritzar, netejar, modernitzar i millorar l'UX.
- Cada peça té la seva pròpia "petita migració" amb criteri d'acceptació individual.
- Més temps, però arribem a una versió net sense heretar deute.

## Decisió

**Migració peça per peça amb millores (opció B).**

Cada peça de server-nexe que es porti a la shell Tauri (UI components, endpoints, mòduls d'agent, plugins, etc.) passa per aquest procés:

1. **Inventari** — documentar què fa la peça actual, què entén, què usa
2. **Revisió crítica** — què funciona bé? què es pot millorar? hi ha redundància?
3. **Reescriure/adaptar** amb millores (UX, API, tests, docs)
4. **Test al nou shell Tauri** (Mac + Windows via SSH)
5. **Diari de la migració** — entrada específica amb abans/després
6. **ADR si hi ha decisió arquitectònica significativa**

## Principis rectors

1. **No copiar sense revisar** — tot el que arriba al shell Tauri ha de ser conscient i volgut
2. **Millores acompanyen la migració** — no "tornarem a això més endavant"; el moment de millorar ÉS ara
3. **Ritmar peça per peça** — evitar big-bang migration. Cada peça individual amb test + documentació.
4. **Mantenir compatibilitat backwards** durant la migració — server-nexe actual segueix funcionant en paral·lel fins que la peça nova sigui validada
5. **Retroportar millores a server-nexe** si és viable i té sentit (no sempre)

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **A — Lift-and-shift 1:1** | Hereda deute tècnic acumulat. L'ocasió de Tauri és perfecta per netejar; no aprofitar-la seria un error estratègic. |
| **C — Full rewrite** | Risc molt alt. server-nexe funciona i té usuaris (Uatu, etc.). Big-bang migration = llarga finestra sense producte funcional. |
| **D — Paral·lel indefinit** | Mantenir dues bases de codi per sempre és insostenible. La migració peça per peça té un **final clar**: server-nexe depreciat. |

## Conseqüències

**Positives:**
- Codi final al shell Tauri és net, modern, revisat
- Oportunitat de modernitzar UX component per component
- Tests individuals per a cada peça migrada
- Documentació generada naturalment durant la migració
- **Resultat final de qualitat superior** al server-nexe actual

**Negatives / riscos:**
- **Temps de migració més llarg** que un lift-and-shift (potser 2x-3x)
- Durant la migració, dues bases de codi coexisteixen (server-nexe + shell Tauri)
- Cal disciplina per no caure al "ho migrarem sense millores per anar ràpid"
- Decisions de millora requereixen pensament, no copy-paste automàtic

**Mitigacions:**
- Ritmar peces petites (evitar migracions monolítiques)
- Criteri d'acceptació clar per peça (no "ho farem igual")
- Diari específic de la migració per mantenir traçabilitat
- Consultoria HOMAD per peces arquitectòniques grans

## Primer peça candidata (suggerida)

**Dashboard / Home screen** — és el que l'usuari veu primer.
- Inventari actual: grid de tiles, estat del sistema, últim chat
- Millores proposables: tema fosc per defecte, keyboard nav, accessibility
- Scope acotat: 1 setmana max

## Estat

- Principis registrats aquí (aquest ADR)
- Aplicació des de Fase 1 (UI integration 2026-04-20+)
- Revisar mensualment si el principi segueix ben seguit

## Referències

- Implementation plan §Fase 1 i §Fase 2 — [internal dev diary, not exposed in OSS repo]
- Fase 0 validation report — [internal dev diary, not exposed in OSS repo]
- server-nexe backend — referenciat com a peça externa (separate private project, not part of this OSS repository)
