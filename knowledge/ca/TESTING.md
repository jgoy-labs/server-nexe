# === METADATA RAG ===
versio: "1.0"
data: 2026-03-15
id: nexe-testing

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Estratègia i cobertura de tests de NEXE 0.8. Cobertura unitària del 95%, +1.483 tests nous generats per Claude (Anthropic). Tests dins de cada mòdul seguint l'estructura modular del projecte."
tags: [testing, pytest, cobertura, qualitat, ci, tests-unitaris, tests-integració]
chunk_size: 1500
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Claude (Anthropic) · Jordi Goy"
expires: null
---

# Testing - NEXE 0.8

> **📝 Document creat:** 2026-03-15
> **🤖 Autoria:** Tests generats per **Claude** (Anthropic) amb supervisió de Jordi Goy.

## Resum

El projecte NEXE 0.8 disposa d'una suite de tests completa amb una **cobertura unitària del 95%**. Els tests han estat generats per Claude (model d'IA d'Anthropic) com a part del procés de qualitat previ a la publicació del projecte.

## Xifres clau

| Mètrica | Valor |
|---|---|
| Cobertura unitària | 95% |
| Tests nous afegits | +1.483 |
| Fitxers de test totals | ~180 |
| Branca de treball | `tests/unit-coverage-95` |

## Estructura dels tests

Els tests segueixen una **estructura modular**: cada mòdul conté els seus propis tests dins d'una carpeta `tests/` al costat del codi que testegen.

```
core/
├── endpoints/tests/        # Tests dels endpoints REST
├── ingest/tests/           # Tests del pipeline d'ingestió
├── metrics/tests/          # Tests de mètriques Prometheus
├── paths/tests/            # Tests de resolució de rutes
├── resilience/tests/       # Tests del circuit breaker
├── server/tests/           # Tests del servidor FastAPI
└── tests/                  # Tests generals del core

memory/
├── embeddings/tests/       # Tests d'embeddings i chunking
├── memory/tests/           # Tests del sistema de memòria
├── rag/tests/              # Tests del motor RAG
└── shared/tests/           # Tests de cache compartit

personality/
├── events/tests/           # Tests del sistema d'events
├── i18n/tests/             # Tests d'internacionalització
├── loading/tests/          # Tests del carregador de mòduls
├── models/tests/           # Tests de perfils de personalitat
└── module_manager/tests/   # Tests del gestor de mòduls

plugins/
├── llama_cpp_module/tests/ # Tests de Llama.cpp
├── mlx_module/tests/       # Tests de MLX
├── ollama_module/tests/    # Tests d'Ollama
├── security/tests/         # Tests de seguretat
├── security_logger/tests/  # Tests del logger de seguretat
└── web_ui_module/tests/    # Tests de la interfície web

tests/                      # Tests d'integració globals
```

## Com executar els tests

```bash
# Tots els tests unitaris
pytest

# Un mòdul específic
pytest plugins/ollama_module/tests/

# Amb cobertura
pytest --cov=. --cov-report=html

# Tests complets (inclou integració)
pytest -c pytest-full.ini
```

## Tipus de tests

### Tests unitaris
- Cobreixen funcions i classes individuals
- Utilitzen mocks per aïllar dependències externes (Qdrant, Ollama, MLX)
- S'executen ràpidament sense serveis externs

### Tests d'integració
- Verifiquen la interacció entre mòduls
- Alguns requereixen serveis actius (Qdrant, Ollama)
- Ubicats a `tests/integration/`

## Filosofia

- **Tests dins de cada mòdul**: si mous un plugin a un altre repositori, els tests van amb ell
- **Mocks per defecte**: els tests unitaris no depenen de serveis externs
- **Cobertura > 90%**: objectiu mínim per a tots els mòduls
- **CI-ready**: tots els tests es poden executar en un entorn d'integració contínua
