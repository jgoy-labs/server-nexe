# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-testing-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estrategia de testing i cobertura per a server-nexe 0.9.1. 4607 funcions de test, 3213 passats a l'ultima execucio completa, 0 errors. Tests col·locats amb els moduls. Cobreix estructura de tests, execucio, cobertura, correccions de tests de l'auditoria IA, tests de crypto (68 nous), resultats del mega-test v1/v2 i valoracio honesta de les limitacions del testing."
tags: [testing, pytest, coverage, tests, quality, ci, ai-audit, refactoring, crypto, mega-test]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy"
expires: null
---

# Testing — server-nexe 0.9.1

## Resultats dels tests

| Metrica | Valor |
|--------|-------|
| Total funcions de test | 4607 |
| Ultima execucio completa passats | 3213 |
| Fallats | 0 |
| Omesos | 6 |
| XFailed | 1 |

Nota: La diferencia entre el total de funcions de test (4607) i els passats (3213) es deu als tests deseleccionats (marcadors integration, e2e, slow) que s'exclouen de l'execucio estandard.

## Estructura dels tests

Els tests estan col·locats amb els seus moduls (no en un directori `tests/` separat a l'arrel):

```
core/endpoints/tests/       # Tests d'endpoints
core/server/tests/          # Tests de factory
core/tests/                 # Tests del core (crypto, lifespan)
plugins/security/tests/     # Tests del plugin de seguretat
plugins/web_ui_module/tests/ # Tests de la Web UI
plugins/ollama_module/tests/ # Tests d'Ollama
memory/memory/tests/        # Tests del modul de memoria
memory/rag/tests/           # Tests de RAG
memory/embeddings/tests/    # Tests d'embeddings
personality/module_manager/tests/ # Tests del module manager
tests/                      # Tests d'integracio a l'arrel
```

## Executar els tests

```bash
# Execucio estandard (exclou integration, e2e, slow)
pytest

# Amb cobertura
pytest --cov

# Suite completa (inclou tots els marcadors)
pytest -c pytest-full.ini

# Modul especific
pytest plugins/security/tests/

# Comanda equivalent a CI
pytest core memory personality plugins \
  -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --cov-report=xml:coverage.xml --tb=short -q
```

El `conftest.py` arrel proporciona fixtures compartides. Cada modul pot tenir el seu propi `conftest.py`.

## Tests de crypto (nous a la v0.9.0)

68 tests afegits per al sistema d'encriptacio at-rest:

| Fitxer de test | Tests | Cobreix |
|-----------|-------|--------|
| `core/tests/test_crypto.py` | 30 | CryptoProvider AES-256-GCM, gestio de claus, HKDF |
| `core/tests/test_crypto_cli.py` | 8 | Comandes CLI (encrypt-all, export-key, status) |
| `memory/memory/tests/test_persistence.py` (+9) | 9 | Migracio SQLCipher, persistencia encriptada |
| `plugins/web_ui_module/tests/test_session_manager.py` (+7) | 7 | Sessions encriptades (.json -> .enc) |
| Tests d'integracio del lifespan | 14 | Integracio end-to-end de CryptoProvider |

## Auditories de seguretat i impacte en els tests

Totes les auditories de seguretat les realitzen sessions autonomes d'IA (Claude), no auditors externs. El desenvolupador llanca sessions de revisio dedicades que analitzen codi, executen tests i generen informes.

### Auditoria IA v1
- 73 troballes -> 40 correccions -> suite de tests actualitzada

### Auditoria IA v2
- 12 troballes -> totes resoltes
- 229 tests fallant corregits (8 causes arrel, 54 tests afectats)
- Causes arrel: refactoritzacio CLI, canvis de manifest, rutes, versions, event loops, canvis d'imports

### Mega-Test v1 Pre-Release
- Auditoria autonoma de 4 fases: baseline, seguretat, funcional, GO/NO-GO
- Baseline: 298 tests, 97.4% cobertura
- Funcional: 158 tests contra servidor en viu, 91.1% taxa de pas
- 23 troballes (1 critica, 6 altes, 7 mitjanes, 7 baixes)
- Veredicte: GO WITH CONDITIONS

### Mega-Test v2 Post-Correccions
- Mateixa metodologia de 4 fases, re-executada despres d'aplicar les correccions de la v1
- 10 troballes (vs 23 a la v1, 57% de reduccio)
- 7 correccions aplicades (validacio de memoria, path traversal, validacio de noms de fitxer, rate limiting, normalitzacio Unicode, print->logger)
- Execucio final: **3213 passats, 0 fallats, 6 omesos, 1 xfailed**
- Veredicte: GO WITH CONDITIONS (millorat)

## Decisions clau de testing

### Closures -> Funcions (refactoritzacio marc 2026)

Durant la separacio del monolit (chat.py, routes.py, tray.py, lifespan.py), les closures es van refactoritzar en funcions independents amb injeccio de dependencies. Aixo va ser critic per a la testabilitat — les closures no es poden patchejar amb `unittest.mock.patch`, pero les funcions a nivell de modul si.

**Abans:** 30 fitxers de test trencats despres de la refactoritzacio per canvis en les rutes d'import i els targets de patch.
**Despres:** Tots els tests actualitzats amb els targets de patch correctes. 229 errors -> 0.

### Filosofia de testing

- Tests dins dels moduls (col·locats, no centralitzats)
- Mocks per a serveis externs (Ollama) i serveis embedded (Qdrant embedded)
- Codi real per a la logica interna
- Preparats per a CI: tots els tests s'executen a GitHub Actions
- Objectiu: >90% de cobertura per modul

## CI/CD

Workflow de GitHub Actions (`.github/workflows/ci.yml`):
- Python 3.12
- Instal·lacio de dependencies (nomes requirements.txt, sense les especifiques de macOS)
- Execucio de la suite completa de tests
- Generacio del badge de cobertura

El CI a Linux funciona perque `rumps` (tray de macOS) esta a `requirements-macos.txt` (no s'instal·la a Linux) i tots els imports del tray son condicionals (flag `_HAS_RUMPS`).

## Valoracio honesta

- **Testejat pel desenvolupador + sessions autonomes d'auditoria IA.** Encara no hi ha usuaris de tercers. No hi ha auditoria de seguretat externa.
- **Un sol usuari real** — server-nexe fins ara nomes l'ha usat el desenvolupador. No hi ha feedback d'usuaris de tercers ni proves de batalla en entorns de produccio multi-usuari.
- **Les auditories IA son exhaustives pero no completes** — troben molts problemes pero sens dubte en passen d'altres per alt. Els numeros de cobertura (97.4% baseline) semblen bons pero no garanteixen correccio.
- **Els tests d'encriptacio son nous** — 68 tests per al sistema de crypto, pero el sistema encara no ha passat per us real en produccio.
- **Els tests d'integracio requereixen serveis locals** — Ollama ha d'estar en execucio (Qdrant es embedded, no cal cap proces separat). Es testegen en desenvolupament pero no a CI.
