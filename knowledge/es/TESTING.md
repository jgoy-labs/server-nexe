# === METADATA RAG ===
versio: "2.0"
data: 2026-07-04
id: nexe-testing-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estrategia y cobertura de pruebas de server-nexe 1.0.7. 7694 funciones de test recopiladas, 7432 pasadas en la ultima ejecucion (2026-07-04). Tests centralizados en un unico directorio tests/ en la raiz que refleja la estructura de modulos. Cubre estructura de tests, ejecucion, cobertura real ~85% global, correcciones de tests de auditoria IA, tests de crypto (72), tests e2e MEM_DELETE (8), resultados de los tests masivos automatizados (ejecutados por IA) y valoracion honesta de las limitaciones de las pruebas."
tags: [testing, pytest, coverage, tests, quality, ci, ai-audit, refactoring, crypto, mass-tests]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Pruebas — server-nexe 1.0.7

## Resultados de las pruebas

| Metrica | Valor |
|---------|-------|
| Total de funciones de test recopiladas | **7694** |
| Ultima ejecucion completa pasados | **7432** |
| **Cobertura real global** | **~85%** (baseline honesta, sin inflar) |

Nota: cifras de la ejecucion del 2026-07-04 (v1.0.7). La diferencia entre recopilados (7694) y pasados (7432) corresponde a tests deseleccionados u omitidos por marcadores (integration/e2e/slow) en la ejecucion estandar.

> **Nota de honestidad sobre cobertura:** Badges historicos han reportado 97.4%, 91.1% o 93% en fases concretas de los tests masivos. Esos numeros correspondian a subconjuntos especificos (baseline de una fase, funcional contra servidor en vivo) y no al global del proyecto. La **cobertura real global del codigo**, medida con `pytest --cov` sobre todo el codebase, es **~85%**. Este es el valor que usamos como referencia.
>
> **Si las IAs nos estan enganando o no, lo direis vosotros.** Las auditorias que tenemos hasta ahora las han hecho modelos de IA (Claude, Gemini y otros), a menudo con **revisiones cruzadas** entre modelos y revision humana final por parte del desarrollador. Es un proceso util pero no infalible — un modelo puede defender una decision equivocada que otro no detecta. Por eso la comunidad (via [GitHub Issues](https://github.com/jgoy-labs/server-nexe/issues) o el foro en server-nexe.com) tiene un papel real: si veis tests que parecen teatro, cifras que no cuadran, o claims demasiado optimistas, **decidlo**. Esta doc es nuestra apuesta por la honestidad, no la prueba definitiva de que lo hemos acertado.

## Estructura de los tests

Todos los tests viven en un unico directorio centralizado `tests/` en la raiz que refleja la estructura de los modulos (no estan co-localizados dentro de `core/`, `plugins/`, `memory/` o `personality/`):

```
tests/core/endpoints/       # Tests de endpoints
tests/core/server/          # Tests de factory
tests/core/                 # Tests de core (crypto, lifespan)
tests/plugins/security/     # Tests del plugin de seguridad
tests/plugins/web_ui_module/ # Tests de la Web UI
tests/plugins/ollama_module/ # Tests de Ollama
tests/memory/memory/        # Tests del modulo de memoria
tests/memory/rag/           # Tests de RAG
tests/memory/embeddings/    # Tests de embeddings
tests/personality/module_manager/ # Tests del module manager
tests/integration/          # Tests de integracion
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
pytest tests/plugins/security/

# Comando equivalente a CI
pytest tests \
  -m "not integration and not e2e and not slow and not gpu and not test_live" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --cov-report=xml:coverage.xml --tb=short -q
```

El `conftest.py` raiz proporciona fixtures compartidas. Cada modulo puede tener su propio `conftest.py`.

## Tests de crypto (nuevos en v0.9.0)

72 tests anadidos para el sistema de encriptacion en reposo:

| Fichero de test | Tests | Cubre |
|----------------|-------|-------|
| `tests/core/test_crypto.py` | 34 | CryptoProvider AES-256-GCM, gestion de claves, HKDF |
| `tests/core/test_crypto_cli.py` | 8 | Comandos CLI (encrypt-all, export-key, status) |
| `tests/memory/memory/test_persistence.py` (+9) | 9 | Migracion SQLCipher, persistencia encriptada |
| `tests/plugins/web_ui_module/test_session_manager.py` (+7) | 7 | Sesiones encriptadas (.json -> .enc) |
| Tests de integracion lifespan | 14 | Integracion end-to-end de CryptoProvider |

## Tests e2e MEM_DELETE (v0.9.9)

En v0.9.9, la correccion de MEM_DELETE (DELETE_THRESHOLD 0.82 → 0.70 → 0.55 → 0.20, valor final 0.20) vino acompanado de una bateria de **8 tests end-to-end** en `tests/integration/test_mem_delete_e2e.py`:

- Qdrant embedded real (no mockeado)
- fastembed ONNX real (no mockeado)
- Ciclo completo: usuario guarda hecho → usuario pide olvidar → verificacion de que el hecho ya no se recupera
- Cubre patrones trilingues (ca: "oblida...", es: "olvida...", en: "forget...")
- Cubre edge cases: hechos similares pero no identicos, confirmacion clear_all 2-turnos, anti-re-save guard

Estos tests son la **fuente de verdad empirica** para el valor del DELETE_THRESHOLD y cualquier cambio en el pipeline de MEM_DELETE debe pasarlos.

## Auditorias de seguridad e impacto en los tests

Todas las auditorias de seguridad son realizadas por sesiones autonomas de IA (Claude), no por auditores externos. El desarrollador lanza sesiones de revision dedicadas que analizan el codigo, ejecutan tests y generan informes.

### Auditoria IA v1
- 73 hallazgos -> 40 correcciones -> suite de tests actualizada

### Auditoria IA v2
- 12 hallazgos -> todos resueltos
- 229 tests fallidos corregidos (8 causas raiz, 54 tests afectados)
- Causas raiz: refactorizacion CLI, cambios en manifests, rutas, versiones, event loops, cambios de imports

### Tests masivos automatizados, ronda 1: Pre-Release (ejecutados por IA)
- Revision por IA de 4 fases: baseline, seguridad, funcional, GO/NO-GO
- Baseline (muestra de una fase): 298 tests, 97.4% cobertura **de esa fase concreta** (no global)
- Funcional (muestra de una fase): 158 tests contra servidor en vivo, 91.1% tasa de exito
- 23 hallazgos (1 critico, 6 altos, 7 medios, 7 bajos)
- Veredicto: GO CON CONDICIONES

### Tests masivos automatizados, ronda 2: Post-Correcciones (ejecutados por IA)
- Misma metodologia de 4 fases, re-ejecutada tras aplicar las correcciones de la primera ronda
- 10 hallazgos (vs 23 en la primera ronda, 57% de reduccion)
- 7 correcciones aplicadas (validacion de memoria, path traversal, validacion de nombres de fichero, rate limiting, normalizacion Unicode, print->logger)
- Ejecucion final (v0.9.9): **4842 tests recopilados pasados, 0 fallidos** (4990 totales)
- Veredicto: GO CON CONDICIONES (mejorado)

## Decisiones clave en las pruebas

### Closures -> Funciones (refactorizacion marzo 2026)

Durante la division del monolito (chat.py, routes.py, tray.py, lifespan.py), las closures se refactorizaron en funciones independientes con inyeccion de dependencias. Esto fue critico para la testeabilidad — las closures no se pueden parchear con `unittest.mock.patch`, pero las funciones a nivel de modulo si.

**Antes:** 30 ficheros de test rotos tras la refactorizacion por cambios en rutas de import y targets de patch.
**Despues:** Todos los tests actualizados con los targets de patch correctos. 229 fallos -> 0.

### Filosofia de testing

- Tests centralizados en un directorio `tests/` en la raiz que refleja la estructura de modulos (no co-localizados)
- Mocks para servicios externos (Ollama) y servicios embebidos (Qdrant embebido)
- Codigo real para logica interna
- Preparado para CI: todos los tests se ejecutan en GitHub Actions
- Objetivo: >90% de cobertura por modulo

## CI/CD

Workflow de GitHub Actions (`.github/workflows/ci.yml`):
- Python 3.11
- Instalar dependencias (solo requirements.txt, sin las especificas de macOS)
- Ejecutar suite completa de tests
- Generacion de badge de cobertura

El CI en Linux funciona porque `rumps` (tray de macOS) esta en `requirements-macos.txt` (no se instala en Linux) y todos los imports del tray son condicionales (flag `_HAS_RUMPS`).

## Valoracion honesta

- **Probado por el desarrollador + sesiones autonomas de auditoria IA.** Ningun usuario externo aun. Sin auditoria de seguridad externa.
- **Un solo usuario real** — server-nexe solo ha sido usado por el desarrollador hasta ahora. No hay feedback de usuarios externos ni pruebas en entornos de produccion multi-usuario.
- **Las auditorias IA son exhaustivas pero no completas** — encuentran muchos problemas pero sin duda se escapan otros. La **cobertura real global es ~85%** (no 97%/91%/93% como aparece en badges antiguos: esos numeros correspondian a subconjuntos de fase).
- **Los tests de encriptacion son nuevos** — 72 tests para el sistema de crypto, pero el sistema aun no ha pasado por uso real en produccion.
- **Los tests de integracion requieren servicios locales** — Ollama debe estar ejecutandose (Qdrant es embebido, no requiere proceso separado). Se prueban en desarrollo pero no en CI.
- **Tests generados por IA 🎭 — leed la cobertura con esta advertencia.** Los tests tambien estan escritos por IA bajo direccion humana (multi-model). Se han hecho auditorias de muestra pero **no podemos garantizar al 100% que no haya "test theatre"** (tests que pasan sin probar nada significativo — comprobaciones triviales, mocks que siempre devuelven el valor esperado, aserciones tautologicas). Un 85% de cobertura con potencial test theatre vale menos que un 70% con tests robustos. Revisiones futuras (humanas o IA independiente) pueden identificarlos y reescribirlos. Mientras tanto: tratad los tests como **senal util pero no prueba definitiva** — un bug en produccion puede manifestarse aunque los tests pasen.
