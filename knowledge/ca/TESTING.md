# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-testing-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estratègia i cobertura de tests per a server-nexe 0.8.2. 3901 tests passats, 0 fallades, 35 saltats. Tests col·locats amb els mòduls. Cobreix estructura de tests, execució de tests, cobertura, correccions de tests de l'auditoria consultoria (229→0 fallades) i impacte de la refactorització del monòlit en els tests."
tags: [testing, pytest, cobertura, tests, qualitat, ci, consultoria, refactorització]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Testing — server-nexe 0.8.2

## Resultats dels tests

| Mètrica | Valor |
|---------|-------|
| Tests totals | 3901 |
| Passats | 3901 |
| Fallats | 0 |
| Saltats | 35 |
| XFailed | 1 |

## Estructura de tests

Els tests estan col·locats amb els seus mòduls (no en un directori `tests/` a l'arrel separat):

```
core/endpoints/tests/       # Tests d'endpoints
core/server/tests/          # Tests de la factory
plugins/security/tests/     # Tests del plugin de seguretat
plugins/web_ui_module/tests/ # Tests de la Web UI
plugins/ollama_module/tests/ # Tests d'Ollama
memory/memory/tests/        # Tests del mòdul de memòria
memory/rag/tests/           # Tests de RAG
memory/embeddings/tests/    # Tests d'embeddings
personality/module_manager/tests/ # Tests del gestor de mòduls
tests/                      # Tests d'integració a l'arrel
```

## Executar tests

```bash
# Tots els tests
pytest

# Amb cobertura
pytest --cov

# Mòdul específic
pytest plugins/security/tests/

# Suite completa (inclou tests lents)
pytest -c pytest-full.ini

# Verbose
pytest -v
```

El `conftest.py` a l'arrel proporciona fixtures compartides. Cada mòdul pot tenir el seu propi `conftest.py`.

## Decisions clau de testing

### Closures a funcions (refactorització de març 2026)

Durant la divisió del monòlit (chat.py, routes.py, tray.py, lifespan.py), les closures es van refactoritzar en funcions independents amb injecció de dependències. Això va ser crític per a la testabilitat — les closures no es poden patchejar amb `unittest.mock.patch`, però les funcions a nivell de mòdul sí.

**Abans:** 30 fitxers de test trencats després de la refactorització per canvis en rutes d'importació i targets de patch.
**Després:** Tots els tests actualitzats amb targets de patch correctes. 229 fallades a 0.

### Impacte de l'auditoria consultoria

- Consultoria v1: 73 troballes a 40 correccions a suite de tests actualitzada
- Consultoria v2: 12 troballes a totes resoltes a 229 tests fallant corregits (8 causes arrel, 54 tests afectats)
- Causes arrel: refactorització CLI, canvis de manifest, rutes, versions, bucles d'events, canvis d'importació

### Filosofia de testing

- Tests dins dels mòduls (col·locats, no centralitzats)
- Mocks per a serveis externs (Qdrant, Ollama)
- Camins de codi real per a lògica interna
- Preparat per CI: tots els tests s'executen a GitHub Actions
- Objectiu: >90% de cobertura per mòdul

## CI/CD

Workflow de GitHub Actions (`.github/workflows/ci.yml`):
- Python 3.12
- Instal·lació de dependències (només requirements.txt, sense les específiques de macOS)
- Execució de la suite completa de tests
- Generació de badge de cobertura

El CI a Linux funciona perquè `rumps` (tray de macOS) està a `requirements-macos.txt` (no s'instal·la a Linux) i totes les importacions del tray són condicionals (flag `_HAS_RUMPS`).
