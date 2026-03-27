# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-testing-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estrategia de testing y cobertura de server-nexe 0.8.2. 3901 tests pasados, 0 fallos, 35 omitidos. Tests colocalizados con sus modulos. Cubre estructura de tests, ejecucion de tests, cobertura, correcciones de tests de la auditoria de consultoria (229→0 fallos) e impacto en tests de la refactorizacion del monolito."
tags: [testing, pytest, cobertura, tests, calidad, ci, consultoria, refactorizacion]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Testing — server-nexe 0.8.2

## Resultados de tests

| Metrica | Valor |
|---------|-------|
| Tests totales | 3901 |
| Pasados | 3901 |
| Fallidos | 0 |
| Omitidos | 35 |
| XFailed | 1 |

## Estructura de tests

Los tests estan colocalizados con sus modulos (no en un directorio `tests/` raiz separado):

```
core/endpoints/tests/       # Tests de endpoints
core/server/tests/          # Tests de factory
plugins/security/tests/     # Tests del plugin de seguridad
plugins/web_ui_module/tests/ # Tests de Web UI
plugins/ollama_module/tests/ # Tests de Ollama
memory/memory/tests/        # Tests del modulo de memoria
memory/rag/tests/           # Tests de RAG
memory/embeddings/tests/    # Tests de embeddings
personality/module_manager/tests/ # Tests del gestor de modulos
tests/                      # Tests de integracion raiz
```

## Ejecutar tests

```bash
# Todos los tests
pytest

# Con cobertura
pytest --cov

# Modulo especifico
pytest plugins/security/tests/

# Suite completa (incluye tests lentos)
pytest -c pytest-full.ini

# Verbose
pytest -v
```

El `conftest.py` raiz proporciona fixtures compartidos. Cada modulo puede tener su propio `conftest.py`.

## Decisiones clave de testing

### Closures → Funciones (refactorizacion de marzo 2026)

Durante la division del monolito (chat.py, routes.py, tray.py, lifespan.py), las closures se refactorizaron a funciones independientes con inyeccion de dependencias. Esto fue critico para la testabilidad — las closures no se pueden parchear con `unittest.mock.patch`, pero las funciones a nivel de modulo si.

**Antes:** 30 ficheros de test rotos tras la refactorizacion por cambios en rutas de import y objetivos de patch.
**Despues:** Todos los tests actualizados con los objetivos de patch correctos. 229 fallos → 0.

### Impacto de la auditoria de consultoria

- Consultoria v1: 73 hallazgos → 40 correcciones → suite de tests actualizada
- Consultoria v2: 12 hallazgos → todos resueltos → 229 tests fallidos corregidos (8 causas raiz, 54 tests afectados)
- Causas raiz: refactorizacion de CLI, cambios de manifest, rutas, versiones, event loops, cambios de import

### Filosofia de testing

- Tests dentro de los modulos (colocalizados, no centralizados)
- Mocks para servicios externos (Qdrant, Ollama)
- Rutas de codigo reales para logica interna
- Listo para CI: todos los tests se ejecutan en GitHub Actions
- Objetivo: >90% de cobertura por modulo

## CI/CD

Workflow de GitHub Actions (`.github/workflows/ci.yml`):
- Python 3.12
- Instalar dependencias (solo requirements.txt, sin especificas de macOS)
- Ejecutar suite completa de tests
- Generacion de badge de cobertura

El CI en Linux funciona porque `rumps` (bandeja de macOS) esta en `requirements-macos.txt` (no se instala en Linux) y todos los imports de bandeja son condicionales (flag `_HAS_RUMPS`).
