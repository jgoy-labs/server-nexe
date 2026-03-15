# Pla per arribar al 100% de tests passats
> **Estat actual:** 1533 ✅ | 30 ❌ | 24 💥 | 23 ⏭️
> **Objectiu:** 0 ❌ | 0 💥 en el run per defecte (`pytest`)

---

## Diagnosi per grups

### Grup A — Contaminació d'estat entre tests (2 FAILED)
**Fitxers afectats:**
- `plugins/security/tests/test_api_key_rotation.py::test_require_api_key_with_expired_key`
- `plugins/security/tests/test_optional_api_key.py::test_optional_api_key_accepts_secondary`

**Causa:** Quan s'executen en la suite completa, les variables d'entorn d'un test anterior contaminen l'estat. La fixture `cleanup_api_key_env` fa cleanup, però `auth_dependencies.py` pot tenir caches de les claus carregades. Quan s'executen sols, passen.

**Solució:** Verificar si `auth_dependencies.py` o `load_api_keys()` fa cache (lru_cache, variable global, etc.) i invalidar-la entre tests, o forçar recàrrega a cada crida.

---

### Grup B — TestClient sense lifespan (20 FAILED)
**Fitxer afectat:**
- `plugins/web_ui_module/tests/integration/test_web_ui_endpoints.py` (totes les classes)

**Causa:** La fixture `client` crea el `TestClient` sense context manager:
```python
# ACTUAL (incorrecte) — lifespan no s'executa:
return TestClient(app, base_url="http://localhost")

# CORRECTE — lifespan s'executa, routers muntats:
with TestClient(app, base_url="http://localhost") as client:
    yield client
```
Sense `with`, el lifespan de FastAPI no s'activa, els mòduls (web_ui, routers) no es munten, i `/ui/health` retorna 404.

**Evidència:** Quan s'executa amb lifespan correcte, retorna `{"status": "healthy", "initialized": True}`.

**Solució:** Canviar la fixture `client` per usar `yield` amb context manager.

---

### Grup C — Tests d'integració sense serveis externs (7 FAILED + 24 ERRORS)
**Fitxers afectats:**
- `core/ingest/tests/test_ingest_pipeline.py` (7 FAILED) — requereix **Qdrant**
- `memory/memory/tests/test_api.py` (1 FAILED + 15 ERRORS) — requereix **Qdrant**
- `memory/embeddings/tests/integration/test_module.py` (9 ERRORS) — requereix **model d'embeddings**

**Causa:** Aquests tests necessiten serveis externs (Qdrant en localhost, model sentence-transformers carregat). No fallen per un bug, sinó perquè el servei no està actiu durant el run per defecte.

**Solució (2 opcions):**
- **Opció 1 (recomanada):** Afegir `-m "not integration and not gpu"` a `pytest.ini` `addopts` per excloure'ls del run per defecte.
- **Opció 2:** Afegir `pytest.importorskip` o `skipif` per saltar automàticament quan Qdrant no respon.

---

## Tasques ordenades

### TASCA 1 — Excloure integration del run per defecte
**Fitxer:** `pytest.ini`
**Canvi:**
```ini
# Canviar de:
addopts = -v --tb=short --cov --cov-report=term-missing

# A:
addopts = -v --tb=short --cov --cov-report=term-missing -m "not integration and not gpu"
```
**Resultat:** Elimina els 7 FAILED + 24 ERRORS del Grup C del run normal.
**Verificació:** `pytest --co -q` no ha de mostrar tests de `test_ingest_pipeline`, `test_api.py` (memory), ni `test_module.py` (embeddings).

---

### TASCA 2 — Arreglar fixture `client` al web_ui
**Fitxer:** `plugins/web_ui_module/tests/integration/test_web_ui_endpoints.py`
**Canvi:**
```python
# Canviar de:
@pytest.fixture(scope="module")
def client(api_key):
    os.environ.setdefault("NEXE_PRIMARY_API_KEY", api_key)
    os.environ.setdefault("NEXE_ENV", "testing")
    os.environ.setdefault("NEXE_DEV_MODE", "true")
    return TestClient(app, base_url="http://localhost")

# A:
@pytest.fixture(scope="module")
def client(api_key):
    os.environ.setdefault("NEXE_PRIMARY_API_KEY", api_key)
    os.environ.setdefault("NEXE_ENV", "testing")
    os.environ.setdefault("NEXE_DEV_MODE", "true")
    with TestClient(app, base_url="http://localhost") as c:
        yield c
```
**Resultat:** Elimina els 20 FAILED del Grup B.

> **Nota:** Aquests tests estan marcats `@pytest.mark.integration` però NO es filtraran amb el canvi de la TASCA 1 perquè la majoria no necessiten GPU ni Qdrant. Si es volen excloure del run ràpid, cal canviar el marker a `@pytest.mark.webui` o similar.

---

### TASCA 3 — Arreglar contaminació d'estat security tests
**Fitxers:** `plugins/security/tests/test_api_key_rotation.py`, `plugins/security/core/auth_dependencies.py`

**Pas 1:** Buscar cache a `auth_dependencies.py`:
```bash
grep -n "lru_cache\|_cache\|_loaded\|global " plugins/security/core/auth_dependencies.py
```

**Pas 2:** Si hi ha cache, afegir reset a la fixture `cleanup_api_key_env`:
```python
# Afegir al cleanup (after yield):
# Invalidar cache de load_api_keys si n'hi ha
try:
    load_api_keys.cache_clear()
except AttributeError:
    pass
```

**Resultat:** Elimina els 2 FAILED del Grup A.

---

## Ordre d'execució recomanat

```
TASCA 1  →  TASCA 2  →  TASCA 3
(~5 min)    (~5 min)    (~10 min)
```

## Verificació final

```bash
# Run complet sense serveis externs → ha de donar 0 fallats
pytest

# Run integració (amb Qdrant actiu)
pytest -m integration

# Run GPU (amb Ollama/MLX actiu)
pytest -m gpu
```

**Objectiu final:**
```
X passed, 0 failed, 0 errors, Y skipped
```

---

*Creat: 2026-03-13*
