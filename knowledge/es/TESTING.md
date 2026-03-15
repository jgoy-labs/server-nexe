# === METADATA RAG ===
versio: "1.0"
data: 2026-03-15
id: nexe-testing

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estrategia y cobertura de tests de NEXE 0.8. Cobertura unitaria del 95%, +1.483 tests nuevos generados por Claude (Anthropic). Tests dentro de cada módulo siguiendo la estructura modular del proyecto."
tags: [testing, pytest, cobertura, calidad, ci, tests-unitarios, tests-integración]
chunk_size: 1500
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Claude (Anthropic) · Jordi Goy"
expires: null
---

# Testing - NEXE 0.8

> **📝 Documento creado:** 2026-03-15
> **🤖 Autoría:** Tests generados por **Claude** (Anthropic) bajo la supervisión de Jordi Goy.

## Resumen

NEXE 0.8 dispone de una suite de tests completa con una **cobertura unitaria del 95%**. Los tests fueron generados por Claude (modelo de IA de Anthropic) como parte del proceso de calidad previo a la publicación del proyecto.

## Cifras clave

| Métrica | Valor |
|---|---|
| Cobertura unitaria | 95% |
| Tests nuevos añadidos | +1.483 |
| Ficheros de test totales | ~180 |
| Rama de trabajo | `tests/unit-coverage-95` |

## Estructura de los tests

Los tests siguen una **estructura modular**: cada módulo contiene sus propios tests dentro de una carpeta `tests/` junto al código que testean.

```
core/
├── endpoints/tests/        # Tests de endpoints REST
├── ingest/tests/           # Tests del pipeline de ingestión
├── metrics/tests/          # Tests de métricas Prometheus
├── paths/tests/            # Tests de resolución de rutas
├── resilience/tests/       # Tests del circuit breaker
├── server/tests/           # Tests del servidor FastAPI
└── tests/                  # Tests generales del core

memory/
├── embeddings/tests/       # Tests de embeddings y chunking
├── memory/tests/           # Tests del sistema de memoria
├── rag/tests/              # Tests del motor RAG
└── shared/tests/           # Tests de cache compartido

personality/
├── events/tests/           # Tests del sistema de eventos
├── i18n/tests/             # Tests de internacionalización
├── loading/tests/          # Tests del cargador de módulos
├── models/tests/           # Tests de perfiles de personalidad
└── module_manager/tests/   # Tests del gestor de módulos

plugins/
├── llama_cpp_module/tests/ # Tests de Llama.cpp
├── mlx_module/tests/       # Tests de MLX
├── ollama_module/tests/    # Tests de Ollama
├── security/tests/         # Tests de seguridad
├── security_logger/tests/  # Tests del logger de seguridad
└── web_ui_module/tests/    # Tests de la interfaz web

tests/                      # Tests de integración globales
```

## Cómo ejecutar los tests

```bash
# Todos los tests unitarios
pytest

# Un módulo específico
pytest plugins/ollama_module/tests/

# Con cobertura
pytest --cov=. --cov-report=html

# Tests completos (incluye integración)
pytest -c pytest-full.ini
```

## Tipos de tests

### Tests unitarios
- Cubren funciones y clases individuales
- Utilizan mocks para aislar dependencias externas (Qdrant, Ollama, MLX)
- Se ejecutan rápidamente sin servicios externos

### Tests de integración
- Verifican la interacción entre módulos
- Algunos requieren servicios activos (Qdrant, Ollama)
- Ubicados en `tests/integration/`

## Filosofía

- **Tests dentro de cada módulo**: si mueves un plugin a otro repositorio, los tests van con él
- **Mocks por defecto**: los tests unitarios no dependen de servicios externos
- **Cobertura > 90%**: objetivo mínimo para todos los módulos
- **CI-ready**: todos los tests se pueden ejecutar en un entorno de integración continua
