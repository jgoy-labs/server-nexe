# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-testing-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Testing strategy and coverage for server-nexe 1.0.2-beta. 4842 test functions collected (4990 total, 148 deselected), 0 failures in latest run. Tests collocated with modules. Covers test structure, running tests, honest actual coverage ~85% global, AI audit test fixes, crypto tests (68), MEM_DELETE e2e tests (8), mega-test v1/v2 results, and honest assessment of testing limitations."
tags: [testing, pytest, coverage, tests, quality, ci, ai-audit, refactoring, crypto, mega-test]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Testing — server-nexe 1.0.2-beta

## Test Results

| Metric | Value |
|--------|-------|
| Total test functions collected | **4842** |
| Total test functions (incl. deselected) | **4990** (148 deselected by markers) |
| Latest full run passed | 4842 |
| Failed | 0 |
| Skipped | 6 |
| XFailed | 1 |
| **Actual global coverage** | **~85%** (honest baseline, not inflated) |

Note: 4842 functions collected in the standard run (excluding integration/e2e/slow markers). The raw total including deselected tests is 4990.

> **Honesty note on coverage:** Historical badges have reported 97.4%, 91.1% or 93% in specific mega-test phases. Those numbers correspond to specific subsets (a phase baseline, functional against a live server) and not to the project global. The **actual global code coverage**, measured with `pytest --cov` over the whole codebase, is **~85%**. That is the value we use as reference.
>
> **Whether the AIs are fooling us or not, you'll be the judge.** The audits we have so far were run by AI models (Claude, Gemini, Codex, and others), often with **cross-reviews** between models and final human review by the developer. It's a useful process but not foolproof — one model can defend a wrong decision that another fails to catch. That's why the community (via [GitHub Issues](https://github.com/jgoy-labs/server-nexe/issues) or the forum at server-nexe.com) has a real role: if you see tests that look like theatre, numbers that don't add up, or claims that sound too optimistic, **say so**. This doc is our bet on honesty, not the definitive proof that we got it right.

## Test Structure

Tests are collocated with their modules (not in a separate `tests/` root):

```
core/endpoints/tests/       # Endpoint tests
core/server/tests/          # Factory tests
core/tests/                 # Core tests (crypto, lifespan)
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
# Standard run (excludes integration, e2e, slow)
pytest

# With coverage
pytest --cov

# Full suite (includes all markers)
pytest -c pytest-full.ini

# Specific module
pytest plugins/security/tests/

# CI-equivalent command
pytest core memory personality plugins \
  -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --cov-report=xml:coverage.xml --tb=short -q
```

Root `conftest.py` provides shared fixtures. Each module can have its own `conftest.py`.

## Crypto Tests (new in v0.9.0)

68 tests added for the encryption at-rest system:

| Test file | Tests | Covers |
|-----------|-------|--------|
| `core/tests/test_crypto.py` | 30 | CryptoProvider AES-256-GCM, key management, HKDF |
| `core/tests/test_crypto_cli.py` | 8 | CLI commands (encrypt-all, export-key, status) |
| `memory/memory/tests/test_persistence.py` (+9) | 9 | SQLCipher migration, encrypted persistence |
| `plugins/web_ui_module/tests/test_session_manager.py` (+7) | 7 | Encrypted sessions (.json → .enc) |
| Lifespan integration tests | 14 | CryptoProvider end-to-end integration |

## MEM_DELETE e2e tests (v0.9.9)

In v0.9.9, the Bug #18 fix (DELETE_THRESHOLD 0.70 → 0.20) brought an associated battery of **8 end-to-end tests** in `tests/integration/test_mem_delete_e2e.py`:

- Real embedded Qdrant (not mocked)
- Real fastembed ONNX (not mocked)
- Full cycle: user saves fact → user asks to forget → verification that the fact is no longer retrieved
- Covers trilingual patterns (ca: "oblida...", es: "olvida...", en: "forget...")
- Covers edge cases: similar but not identical facts, 2-turn clear_all confirmation, anti-re-save guard

These tests are the **empirical source of truth** for the DELETE_THRESHOLD value, and any change to the MEM_DELETE pipeline must pass them.

## Security Audits and Test Impact

All security audits are performed by autonomous AI sessions (Claude), not external auditors. The developer launches dedicated review sessions that analyze code, run tests, and generate reports.

### AI Audit v1
- 73 findings → 40 fixes → test suite updated

### AI Audit v2
- 12 findings → all resolved
- 229 failing tests fixed (8 root causes, 54 tests affected)
- Root causes: CLI refactor, manifest changes, paths, versions, event loops, import changes

### Mega-Test v1 Pre-Release
- 4-phase autonomous audit: baseline, security, functional, GO/NO-GO
- Baseline (phase sample): 298 tests, 97.4% coverage **of that specific phase** (not global)
- Functional (phase sample): 158 tests against live server, 91.1% pass rate
- 23 findings (1 critical, 6 high, 7 medium, 7 low)
- Verdict: GO WITH CONDITIONS

### Mega-Test v2 Post-Fixes
- Same 4-phase methodology, re-run after applying v1 fixes
- 10 findings (vs 23 in v1, 57% reduction)
- 7 fixes applied (memory validation, path traversal, filename validation, rate limiting, Unicode normalization, print→logger)
- Final run (v0.9.9): **4842 collected tests passed, 0 failed** (4990 total)
- Verdict: GO WITH CONDITIONS (improved)

## Key Testing Decisions

### Closures → Functions (March 2026 refactoring)

During the monolith split (chat.py, routes.py, tray.py, lifespan.py), closures were refactored into standalone functions with dependency injection. This was critical for testability — closures cannot be patched with `unittest.mock.patch`, but module-level functions can.

**Before:** 30 test files broken after refactoring due to changed import paths and patch targets.
**After:** All tests updated with correct patch targets. 229 failures → 0.

### Test philosophy

- Tests inside modules (collocated, not centralized)
- Mocks for external services (Ollama) and embedded services (Qdrant embedded)
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

## Honest Assessment

- **Tested by the developer + autonomous AI audit sessions.** No third-party users yet. No external security audit.
- **One real user** — server-nexe has only been used by the developer so far. There is no feedback from third-party users or battle-testing in production multi-user environments.
- **AI audits are thorough but not exhaustive** — they find many issues but certainly miss others. **Actual global coverage is ~85%** (not 97%/91%/93% as shown in old badges: those numbers corresponded to phase subsets).
- **Encryption tests are new** — 68 tests for the crypto system, but the system has not been through real production use yet.
- **Integration tests require local services** — Ollama must be running (Qdrant is embedded, no separate process needed). These are tested in development but not in CI.
- **AI-generated tests 🎭 — read coverage with this caveat.** Tests are also written by AI under human direction (multi-model). Sample audits have been performed but **we cannot guarantee 100% there is no "test theatre"** (tests that pass without proving anything meaningful — trivial checks, mocks that always return the expected value, tautological assertions). 85% coverage with potential test theatre is worth less than 70% with robust tests. Future reviews (human or independent AI) may identify and rewrite them. In the meantime: treat tests as a **useful signal, not definitive proof** — a production bug may manifest even if tests pass.
