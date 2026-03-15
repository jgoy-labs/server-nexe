# Pla de Coverage 100% — Server Nexe 0.8
> **Data:** 2026-03-13 | **Coverage actual:** 57% (5.647 línies sense cobrir) | **Objectiu:** 100%
> **Prerequisit:** Qdrant actiu (localhost:6333), Ollama actiu (localhost:11434), serveis locals encesos

---

## Resum executiu

**146 fitxers** sota el 100%. L'estratègia és:
1. Activar els tests d'integració ja escrits (Qdrant + embeddings) → +8-10%
2. Escriure tests unitaris per mòduls amb cobertura baixa → +25-30%
3. Escriure tests d'integració per endpoints i workflows → +5-8%

---

## FASE 0 — Preparació (prerequisits)

### 0.1 Verificar serveis actius
```bash
curl -s http://localhost:6333/healthz && echo "Qdrant OK"
curl -s http://localhost:11434/api/tags && echo "Ollama OK"
python3 -c "from sentence_transformers import SentenceTransformer; print('Embeddings OK')"
```

### 0.2 Activar run complet per coverage
Modificar `pytest.ini` per tenir dos modes:
- `pytest` → run ràpid (unit tests, sense serveis)
- `pytest --all` → run complet (tots els tests, serveis requerits)

Crear `pytest-full.ini`:
```ini
[pytest]
asyncio_mode = auto
addopts = -v --tb=short --cov --cov-report=term-missing
testpaths = core memory personality plugins
```

---

## FASE 1 — Tests d'integració existents (Qdrant requerit)
> **Impacte estimat:** +8-10% cobertura
> **Fitxers afectats:** memory/memory/api/, memory/embeddings/, core/ingest/

### 1.1 Arreglar `memory/memory/tests/test_api.py`
- **Problema:** 15 ERRORS + 1 FAILED quan Qdrant no actiu
- **Acció:** Afegir marker `@pytest.mark.integration` i fixture `require_qdrant` a tots els tests
- **Cobreix:** `memory/memory/api/__init__.py` (87 línies), `memory/memory/api/collections.py` (36 línies), `memory/memory/api/documents.py` (123 línies)

### 1.2 Arreglar `memory/embeddings/tests/integration/test_module.py`
- **Problema:** 9 ERRORS (model embeddings no carregat)
- **Acció:** Afegir fixture `require_embeddings` que comprovi sentence-transformers
- **Cobreix:** `memory/embeddings/module.py` (27 línies), `memory/embeddings/health.py` (34 línies)

### 1.3 Activar `core/ingest/tests/test_ingest_pipeline.py`
- **Problema:** 7 FAILED sense Qdrant
- **Acció:** Afegir fixture `require_qdrant`
- **Cobreix:** `core/ingest/ingest_knowledge.py` (115 línies), `core/ingest/ingest_docs.py` (62 línies)

---

## FASE 2 — Tests unitaris nous per mòduls core
> **Impacte estimat:** +15-20%

### 2.1 `core/endpoints/chat.py` — 358 línies (24%)
**Fitxer de tests:** `core/endpoints/tests/test_chat_unit.py` (existeix, ampliar)

Paths a cobrir:
- Streaming SSE (línies 209-395)
- Gestió d'errors de connexió backend (línies 399-436)
- Pipeline RAG integrat al chat (línies 447-543)
- Timeouts i circuit breaker (línies 550-595)
- Backends alternatius (MLX, llama.cpp) (línies 613-809)
- Validació d'entrada avançada (línies 820-909)
- Cancel·lació de requests (línies 933-1017)

**Estratègia:** Mocks per a tots els backends + TestClient

### 2.2 `core/endpoints/bootstrap.py` — 54 línies (61%)
**Fitxer de tests:** `core/endpoints/tests/test_bootstrap.py` (existeix, ampliar)

Paths a cobrir:
- Error paths (línies 38-39, 126-132)
- Regeneració de tokens (línies 140-194)
- Rotació de tokens (línies 213-254)

### 2.3 `core/container.py` — 52 línies (0%)
**Fitxer de tests:** `core/tests/test_container.py` (nou)

- Dependency injection container
- Tests unitaris purs (sense serveis)

### 2.4 `core/paths/` — 171 línies (0%)
**Fitxer de tests:** `core/paths/tests/test_paths_full.py` (nou)

Cobreix tots els fitxers:
- `core/paths.py`, `core/paths/__init__.py`
- `core/paths/detection.py` — detecció del directori arrel
- `core/paths/helpers.py` — helpers de paths
- `core/paths/validation.py` — validació de paths

### 2.5 `core/resources.py` — 59 línies (0%)
**Fitxer de tests:** `core/tests/test_resources.py` (nou)

### 2.6 `core/cli/utils/api_client.py` — 126 línies (0%)
**Fitxer de tests:** `core/cli/utils/tests/test_api_client.py` (nou)

- Client HTTP per CLI
- Mocks de responses HTTP

### 2.7 `core/dependencies.py` — 8 línies (47%)
**Fitxer de tests:** `core/tests/test_dependencies.py` (ampliar)

### 2.8 `core/request_size_limiter.py` — 26 línies (49%)
**Fitxer de tests:** `core/tests/test_request_size_limiter.py` (nou)

### 2.9 `core/middleware.py` — 27 línies (78%)
**Fitxer de tests:** `core/tests/test_middleware.py` (ampliar)

---

## FASE 3 — Tests unitaris nous per Memory
> **Impacte estimat:** +10-12%

### 3.1 `memory/memory/workflow/nodes/memory_recall_node.py` — 124 línies (0%)
**Fitxer de tests:** `memory/memory/tests/test_workflow_nodes.py` (nou)

- Mocks de MemoryAPI
- Tests de tots els paths del node

### 3.2 `memory/memory/workflow/nodes/memory_store_node.py` — 37 línies (0%)
Mateix fitxer que 3.1.

### 3.3 `memory/memory/metrics.py` — 83 línies (0%)
**Fitxer de tests:** `memory/memory/tests/test_metrics.py` (nou)

### 3.4 `memory/memory/cli.py` + `memory/memory/cli/rag_viewer.py` — 268 línies (0%)
**Fitxer de tests:** `memory/memory/tests/test_cli.py` (nou)
- Mocks de clic/typer
- Mocks de MemoryAPI

### 3.5 `memory/embeddings/simple_embedder.py` — 41 línies (0%)
**Fitxer de tests:** `memory/embeddings/tests/test_simple_embedder.py` (nou)

### 3.6 `memory/rag/workflow/` — ~92 línies (0%)
**Fitxer de tests:** `memory/rag/tests/test_workflow.py` (nou)

Cobreix:
- `memory/rag/workflow/__init__.py`
- `memory/rag/workflow/nodes/__init__.py`
- `memory/rag/workflow/nodes/rag_search_node.py`
- `memory/rag/workflow/registry.py`

### 3.7 `memory/rag/cli.py` — 92 línies (53%)
**Fitxer de tests:** `memory/rag/tests/test_cli.py` (nou)

### 3.8 `memory/memory/rag_logger.py` — 156 línies (50%)
**Fitxer de tests:** `memory/memory/tests/test_rag_logger.py` (existeix, ampliar)

### 3.9 `memory/memory/engines/flash_memory.py` — 19 línies (75%)
**Fitxer de tests:** `memory/memory/tests/test_flash_memory.py` (ampliar)

### 3.10 `memory/memory/pipeline/ingestion.py` — 40 línies (65%)
**Fitxer de tests:** `memory/memory/tests/test_pipeline.py` (ampliar)

### 3.11 `memory/rag/routers/endpoints.py` — 29 línies (69%)
**Fitxer de tests:** `memory/rag/tests/test_endpoints.py` (ampliar)

---

## FASE 4 — Tests unitaris nous per Personality
> **Impacte estimat:** +8-10%

### 4.1 `personality/loading/` — ~283 línies (~30%)
**Fitxers de tests:** `personality/loading/tests/` (directori nou)

- `test_loader.py` — cobreix `loader.py`
- `test_module_extractor.py` — cobreix `module_extractor.py`
- `test_module_finder.py` — cobreix `module_finder.py`
- `test_module_importer.py` — cobreix `module_importer.py`
- `test_module_lifecycle.py` — cobreix `module_lifecycle.py`
- `test_module_validator.py` — cobreix `module_validator.py`

### 4.2 `personality/module_manager/manifest.py` — 52 línies (0%)
**Fitxer de tests:** `personality/module_manager/tests/test_manifest.py` (nou)

### 4.3 `personality/module_manager/registry.py` — 83 línies (47%)
**Fitxer de tests:** `personality/module_manager/tests/test_registry.py` (ampliar)

### 4.4 `personality/module_manager/system_lifecycle.py` — 34 línies (33%)
**Fitxer de tests:** `personality/module_manager/tests/test_system_lifecycle.py` (nou)

### 4.5 `personality/module_manager/sync_wrapper.py` — 30 línies (44%)
**Fitxer de tests:** `personality/module_manager/tests/test_sync_wrapper.py` (nou)

### 4.6 `personality/i18n/` — ~90 línies (~63-79%)
**Fitxer de tests:** `personality/i18n/tests/test_i18n.py` (nou)

### 4.7 `personality/integration/` — ~54 línies (~72-85%)
**Fitxer de tests:** `personality/integration/tests/test_api_integrator.py` (existeix, ampliar)

---

## FASE 5 — Tests per Plugins
> **Impacte estimat:** +8-10%

### 5.1 `plugins/ollama_module/` — ~312 línies (~7-43%)
**Fitxers de tests:** `plugins/ollama_module/tests/`

- `test_module_full.py` — cobreix `module.py` (113 línies)
- `test_manifest_full.py` — cobreix `manifest.py` (71 línies)
- `test_health.py` — cobreix `health.py` (26 línies, 0%)
- `test_cli.py` — cobreix `cli.py` (101 línies, 0%)
- `test_ollama_node.py` — cobreix `workflow/nodes/ollama_node.py` (99 línies, 7%)

**Estratègia:** Mocks de httpx per simular respostes d'Ollama. Per tests d'integració: Ollama ha d'estar actiu.

### 5.2 `plugins/mlx_module/` — ~269 línies (~21-64%)
**Fitxers de tests:** `plugins/mlx_module/tests/`

- `test_chat_full.py` — cobreix `chat.py` (88 línies, 21%)
- `test_prompt_cache.py` — cobreix `prompt_cache_manager.py` (145 línies, 0%)
- `test_config_full.py` — cobreix `config.py` (36 línies, 64%)

**Estratègia:** MLX requereix Apple Silicon. Usar `pytest.importorskip("mlx")` i mocks.

### 5.3 `plugins/llama_cpp_module/` — ~103 línies (~24-70%)
**Fitxers de tests:** `plugins/llama_cpp_module/tests/`

- `test_chat_full.py` — cobreix `chat.py` (81 línies, 24%)
- `test_module_full.py` — cobreix `module.py` (22 línies, 70%)

**Estratègia:** Mock de `llama_cpp` per unit tests.

### 5.4 `plugins/security/` — ~215 línies (~31-89%)
**Fitxers de tests:** `plugins/security/tests/`

- `test_rate_limiting.py` (nou) — `rate_limiting.py` (58 línies, 36%)
- `test_manifest_full.py` (nou) — `manifest.py` (59 línies, 40%)
- `test_auth_dependencies_full.py` (ampliar) — `auth_dependencies.py` (39 línies, 61%)
- `test_security_logger.py` (nou) — `plugins/security/core/logger.py` (51 línies, 31%)
- `test_sanitizer_workflow.py` (nou) — `sanitizer/workflow/nodes/` (36 línies, 0%)

### 5.5 `plugins/web_ui_module/` — ~668 línies (~14-86%)
**Fitxers de tests:** `plugins/web_ui_module/tests/`

- `test_manifest_full.py` (nou) — `manifest.py` (375 línies, 14%)
- `test_memory_helper_full.py` (ampliar) — `memory_helper.py` (157 línies, 35%)
- `test_module_full.py` (nou) — `module.py` (118 línies, 40%)

---

## FASE 6 — Línies residuals (~95% → 100%)
> **Impacte estimat:** +2-3%

### 6.1 Línies individuals en fitxers >90%
Fitxers amb 1-10 línies manquants:
- `core/bootstrap_tokens.py` → 5 línies (97%)
- `core/config.py` → 2 línies (97%)
- `core/metrics/middleware.py` → 1 línia (98%)
- `memory/embeddings/workflow/nodes/chunking_node.py` → 1 línia (97%)
- `memory/memory/models/memory_entry.py` → 1 línia (97%)
- I ~20 fitxers més entre 91-99%

**Estratègia:** Llegir les línies exactes sense cobertura, afegir tests específics.

---

## Ordre d'execució recomanat per màxim impacte

```
FASE 0   Verificar serveis (10 min)
  ↓
FASE 1   Integració Qdrant (activar tests existents) → +8%   (30 min)
  ↓
FASE 2   Core endpoints + paths + container        → +15%   (2h)
  ↓
FASE 3   Memory workflow + CLI + RAG workflow       → +10%   (2h)
  ↓
FASE 4   Personality loading + module_manager       → +8%   (1.5h)
  ↓
FASE 5   Plugins (ollama, mlx, llama, security, ui) → +8%   (2h)
  ↓
FASE 6   Línies residuals                           → +2%   (1h)
  ↓
100% ✅
```

---

## Fitxers a afegir al `.coveragerc` (excloure legítimament)

Alguns fitxers **no s'han de mesurar** perquè:
- Són CLI interactius sense testabilitat pràctica
- Depenen 100% de hardware específic (MLX en Apple Silicon)
- Són codis de generació de codi (templates)

Candidats a afegir a `omit`:
```ini
plugins/mlx_module/generate_helpers.py   # ja exclòs
plugins/mlx_module/prompt_cache_manager.py  # MLX Apple Silicon
memory/memory/cli/rag_viewer.py          # CLI interactiu
plugins/ollama_module/cli.py             # CLI interactiu
```
**Nota:** Afegir-los NOMÉS si no és possible escriure tests raonables.

---

## Verificació final

```bash
# Run complet amb tots els serveis
pytest -c pytest-full.ini --tb=short

# Verificar coverage
pytest -c pytest-full.ini --cov-report=html
open htmlcov/index.html
```

**Objectiu:**
```
TOTAL    13155    0    100%
```

---

*Creat: 2026-03-13 | Serveis requerits: Qdrant (6333) + Ollama (11434) + Embeddings*
