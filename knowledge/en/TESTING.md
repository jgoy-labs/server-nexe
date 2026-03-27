# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-testing-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Testing strategy and coverage for server-nexe 0.8.2. 3901 tests passed, 0 failures, 35 skipped. Tests collocated with modules. Covers test structure, running tests, coverage, consultoria audit test fixes (229→0 failures), and monolith refactoring test impact."
tags: [testing, pytest, coverage, tests, quality, ci, consultoria, refactoring]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Testing — server-nexe 0.8.2

## Test Results

| Metric | Value |
|--------|-------|
| Total tests | 3901 |
| Passed | 3901 |
| Failed | 0 |
| Skipped | 35 |
| XFailed | 1 |

## Test Structure

Tests are collocated with their modules (not in a separate `tests/` root):

```
core/endpoints/tests/       # Endpoint tests
core/server/tests/          # Factory tests
plugins/security/tests/     # Security plugin tests
plugins/web_ui_module/tests/ # Web UI tests
plugins/ollama_module/tests/ # Ollama tests
memory/memory/tests/        # Memory module tests
memory/rag/tests/           # RAG tests
memory/embeddings/tests/    # Embeddings tests
personality/module_manager/tests/ # Module manager tests
tests/                      # Root integration tests
```

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov

# Specific module
pytest plugins/security/tests/

# Full suite (includes slow tests)
pytest -c pytest-full.ini

# Verbose
pytest -v
```

Root `conftest.py` provides shared fixtures. Each module can have its own `conftest.py`.

## Key Testing Decisions

### Closures → Functions (March 2026 refactoring)

During the monolith split (chat.py, routes.py, tray.py, lifespan.py), closures were refactored into standalone functions with dependency injection. This was critical for testability — closures cannot be patched with `unittest.mock.patch`, but module-level functions can.

**Before:** 30 test files broken after refactoring due to changed import paths and patch targets.
**After:** All tests updated with correct patch targets. 229 failures → 0.

### Consultoria audit impact

- Consultoria v1: 73 findings → 40 fixes → test suite updated
- Consultoria v2: 12 findings → all resolved → 229 failing tests fixed (8 root causes, 54 tests affected)
- Root causes: CLI refactor, manifest changes, paths, versions, event loops, import changes

### Test philosophy

- Tests inside modules (collocated, not centralized)
- Mocks for external services (Qdrant, Ollama)
- Real code paths for internal logic
- CI-ready: all tests run in GitHub Actions
- Target: >90% coverage per module

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`):
- Python 3.12
- Install dependencies (requirements.txt only, no macOS-specific)
- Run full test suite
- Coverage badge generation

Linux CI works because `rumps` (macOS tray) is in `requirements-macos.txt` (not installed on Linux) and all tray imports are conditional (`_HAS_RUMPS` flag).
