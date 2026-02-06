# Production Checklist (target 2026-02-23)

Updated: 2026-02-06

## Checklist
- [ ] Hardcoded strings / i18n
- [x] Git cleanup (remove uploads history, update .gitignore)
- [ ] Versioned files inventory (tree)
- [ ] Tests (unit/integration/e2e)
- [ ] Security config for production (NEXE_ENV=production, allowlist, API keys)
- [ ] Build/install verification
- [ ] Deployment runbook

## Hardcoded Strings / i18n
- [x] Core CLI i18n
- [x] Ollama plugin CLI i18n
- [ ] Server endpoints and API error payloads (bootstrap/chat/system/root/modules done; remaining v1/other endpoints)
- [ ] Memory/RAG logs and API messages (header parser + RAG upload/add responses done; remaining others)
- [ ] Plugin workflow/schema descriptions

## Tests
- [ ] Unit tests (non-integration)
- [ ] Integration tests (requires Ollama/Qdrant)
- [ ] E2E tests (if applicable)

## Test Notes
- 2026-02-06: `pytest -m "not integration and not e2e and not slow"` failed with 2 tests due to Ollama connection errors and Qdrant embedded lock. Re-run when services are up.
