# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-testing-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estrategia y cobertura de pruebas de server-nexe 0.8.5 pre-release. 4143 funciones de test, 3213 pasados en la ultima ejecucion completa, 0 fallos. Tests colocados junto a los modulos. Cubre estructura de tests, ejecucion, cobertura, correcciones de tests de auditoria IA, tests de crypto (68 nuevos), resultados de mega-test v1/v2, y valoracion honesta de las limitaciones de las pruebas."
tags: [testing, pytest, coverage, tests, quality, ci, ai-audit, refactoring, crypto, mega-test]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Pruebas — server-nexe 0.8.5 pre-release

## Resultados de las pruebas

| Metrica | Valor |
|---------|-------|
| Total de funciones de test | 4143 |
| Pasados en ultima ejecucion | 3213 |
| Fallidos | 0 |
| Saltados | 6 |
| XFailed | 1 |

Nota: La diferencia entre el total de funciones de test (4143) y los pasados (3213) se debe a tests deseleccionados (marcadores integration, e2e, slow) que se excluyen de la ejecucion estandar.

## Estructura de los tests

Los tests estan colocados junto a sus modulos (no en un directorio `tests/` raiz separado):

```
core/endpoints/tests/       # Tests de endpoints
core/server/tests/          # Tests de factory
core/tests/                 # Tests de core (crypto, lifespan)
plugins/security/tests/     # Tests del plugin de seguridad
plugins/web_ui_module/tests/ # Tests de la Web UI
plugins/ollama_module/tests/ # Tests de Ollama
memory/memory/tests/        # Tests del modulo de memoria
memory/rag/tests/           # Tests de RAG
memory/embeddings/tests/    # Tests de embeddings
personality/module_manager/tests/ # Tests del module manager
tests/                      # Tests de integracion raiz
```

## Ejecutar los tests

```bash
# Ejecucion estandar (excluye integration, e2e, slow)
pytest

# Con cobertura
pytest --cov

# Suite completa (incluye todos los marcadores)
pytest -c pytest-full.ini

# Modulo especifico
pytest plugins/security/tests/

# Comando equivalente a CI
pytest core memory personality plugins \
  -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --cov-report=xml:coverage.xml --tb=short -q
```

El `conftest.py` raiz proporciona fixtures compartidas. Cada modulo puede tener su propio `conftest.py`.

## Tests de crypto (nuevos en v0.8.5)

68 tests anadidos para el sistema de encriptacion en reposo:

| Fichero de test | Tests | Cubre |
|----------------|-------|-------|
| `core/tests/test_crypto.py` | 30 | CryptoProvider AES-256-GCM, gestion de claves, HKDF |
| `core/tests/test_crypto_cli.py` | 8 | Comandos CLI (encrypt-all, export-key, status) |
| `memory/memory/tests/test_persistence.py` (+9) | 9 | Migracion SQLCipher, persistencia encriptada |
| `plugins/web_ui_module/tests/test_session_manager.py` (+7) | 7 | Sesiones encriptadas (.json -> .enc) |
| Tests de integracion lifespan | 14 | Integracion end-to-end de CryptoProvider |

## Auditorias de seguridad e impacto en los tests

Todas las auditorias de seguridad son realizadas por sesiones autonomas de IA (Claude), no por auditores externos. El desarrollador lanza sesiones de revision dedicadas que analizan el codigo, ejecutan tests y generan informes.

### Auditoria IA v1
- 73 hallazgos -> 40 correcciones -> suite de tests actualizada

### Auditoria IA v2
- 12 hallazgos -> todos resueltos
- 229 tests fallidos corregidos (8 causas raiz, 54 tests afectados)
- Causas raiz: refactorizacion CLI, cambios en manifests, rutas, versiones, event loops, cambios de imports

### Mega-Test v1 Pre-Release
- Auditoria autonoma de 4 fases: baseline, seguridad, funcional, GO/NO-GO
- Baseline: 298 tests, 97.4% cobertura
- Funcional: 158 tests contra servidor en vivo, 91.1% tasa de exito
- 23 hallazgos (1 critico, 6 altos, 7 medios, 7 bajos)
- Veredicto: GO CON CONDICIONES

### Mega-Test v2 Post-Correcciones
- Misma metodologia de 4 fases, re-ejecutada tras aplicar las correcciones de v1
- 10 hallazgos (vs 23 en v1, 57% de reduccion)
- 7 correcciones aplicadas (validacion de memoria, path traversal, validacion de nombres de fichero, rate limiting, normalizacion Unicode, print->logger)
- Resultado final: **3213 pasados, 0 fallidos, 6 saltados, 1 xfailed**
- Veredicto: GO CON CONDICIONES (mejorado)

## Decisiones clave en las pruebas

### Closures -> Funciones (refactorizacion marzo 2026)

Durante la division del monolito (chat.py, routes.py, tray.py, lifespan.py), las closures se refactorizaron en funciones independientes con inyeccion de dependencias. Esto fue critico para la testeabilidad — las closures no se pueden parchear con `unittest.mock.patch`, pero las funciones a nivel de modulo si.

**Antes:** 30 ficheros de test rotos tras la refactorizacion por cambios en rutas de import y targets de patch.
**Despues:** Todos los tests actualizados con los targets de patch correctos. 229 fallos -> 0.

### Filosofia de testing

- Tests dentro de los modulos (colocados, no centralizados)
- Mocks para servicios externos (Qdrant, Ollama)
- Codigo real para logica interna
- Preparado para CI: todos los tests se ejecutan en GitHub Actions
- Objetivo: >90% de cobertura por modulo

## CI/CD

Workflow de GitHub Actions (`.github/workflows/ci.yml`):
- Python 3.12
- Instalar dependencias (solo requirements.txt, sin las especificas de macOS)
- Ejecutar suite completa de tests
- Generacion de badge de cobertura

El CI en Linux funciona porque `rumps` (tray de macOS) esta en `requirements-macos.txt` (no se instala en Linux) y todos los imports del tray son condicionales (flag `_HAS_RUMPS`).

## Valoracion honesta

- **Probado por el desarrollador + sesiones autonomas de auditoria IA.** Ningun usuario externo aun. Sin auditoria de seguridad externa.
- **Un solo usuario real** — server-nexe solo ha sido usado por el desarrollador hasta ahora. No hay feedback de usuarios externos ni pruebas en entornos de produccion multi-usuario.
- **Las auditorias IA son exhaustivas pero no completas** — encuentran muchos problemas pero sin duda se escapan otros. Los numeros de cobertura (97.4% baseline) parecen buenos pero no garantizan la correccion.
- **Los tests de encriptacion son nuevos** — 68 tests para el sistema de crypto, pero el sistema aun no ha pasado por uso real en produccion.
- **Los tests de integracion requieren servicios locales** — Qdrant y Ollama deben estar ejecutandose. Se prueban en desarrollo pero no en CI.
