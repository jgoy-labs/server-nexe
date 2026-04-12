# Contributing

Thanks for considering a contribution to Server Nexe. This guide covers the development setup, testing, plugin development, and project conventions.

## Local development setup

**Requirements:** Python 3.11+ (3.12 recommended), macOS or Linux.

```bash
git clone https://github.com/jgoy-labs/server-nexe.git
cd server-nexe
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the example environment file and set your API key:

```bash
cp .env.example .env
# Edit .env — set NEXE_PRIMARY_API_KEY
```

Start the server:

```bash
python -m core.cli go
```

## Running tests

The test suite has 4572 passing tests with 90% code coverage.

```bash
# Fast unit tests (no external services needed)
pytest core memory personality plugins \
  -m "not integration and not e2e and not slow" \
  --tb=short -q

# Integration tests (requires Ollama running locally)
NEXE_AUTOSTART_OLLAMA=true pytest -m "integration" -q

# With coverage report
pytest core memory personality plugins \
  -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term -q
```

## Plugin development

Server Nexe uses auto-discovered plugins. Each plugin is a directory under `plugins/` with:

```
plugins/my_module/
├── manifest.toml    # Required: module metadata, dependencies, endpoints
├── module.py        # Required: module class implementing ModuleInterface
├── __init__.py
├── tests/           # Tests for the plugin
└── ...              # Additional files as needed
```

### manifest.toml

```toml
[module]
name = "my_module"
version = "0.9.1"
description = "What this module does"
author = "Your Name"

[module.dependencies]
required = []
optional = []

[module.endpoints]
prefix = "/my-module"
```

### module.py

```python
from core.loader.protocol import ModuleMetadata

class Module:
    """Module implementing ModuleInterface."""

    def __init__(self):
        self.metadata = ModuleMetadata(
            name="my_module",
            version="0.9.1",
            description="What this module does",
        )

    def get_router(self):
        """Return a FastAPI APIRouter with module endpoints."""
        from fastapi import APIRouter
        router = APIRouter()
        # Add routes here
        return router
```

The module manager discovers plugins automatically on startup via `manifest.toml` files. No registration needed.

## Knowledge base (AI-ready docs)

The `knowledge/` directory contains documentation structured for RAG ingestion. Each document has a metadata header:

```
# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: document-id
abstract: "One-line description for search ranking"
tags: [tag1, tag2, tag3]
chunk_size: 800
priority: P1
lang: en
type: docs
collection: user_knowledge
author: "Your Name"
---
```

Documents exist in three languages (`knowledge/en/`, `knowledge/ca/`, `knowledge/es/`). If you add or update documentation, keep all three language versions in sync.

**Constraints:** Maximum 15 tags per document. Abstract should be under 500 characters.

## Code conventions

- **Language:** Code and comments in English. Documentation available in Catalan, Spanish, and English.
- **Testing:** Include tests for behavior changes. Tests live in `tests/` subdirectories within each module.
- **No cloud assumptions:** This is a local-first project. Do not add features that require external services to function.
- **Security:** Validate all user input at system boundaries. Use `validate_string_input()` for string parameters. Never log sensitive data.
- **Logging:** Use structured logging (`logger.info(...)`) — no `print()` calls in production code. Use lazy formatting (`logger.info("msg %s", var)` not f-strings).
- **i18n:** User-facing error messages should be internationalized (ca/es/en). See `core/endpoints/` for the pattern.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep changes focused — one feature or fix per PR.
3. Include tests when behavior changes.
4. Run the full test suite before submitting.
5. Describe what the PR does and why.

## Code of conduct

Be respectful and constructive. This is a personal project maintained in spare time. Contributions are welcome regardless of experience level. If you are unsure about an approach, open an issue to discuss before writing code.

---

*v0.9.1 · Apache 2.0 · Jordi Goy*
