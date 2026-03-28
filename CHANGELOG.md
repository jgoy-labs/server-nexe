# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.8.5] - 2026-03-28

### Added
- Encryption at-rest (opt-in): AES-256-GCM via CryptoProvider with HKDF-SHA256 key derivation
- Master key management: OS Keyring, environment variable, or file-based fallback chain
- SQLCipher support for encrypted SQLite databases with automatic migration from plaintext
- Encrypted session files (.json to .enc migration with AES-256-GCM)
- TextStore for RAG document text (text removed from Qdrant payloads, stored in SQLite/SQLCipher)
- CLI commands: `nexe encryption status`, `nexe encryption encrypt-all`, `nexe encryption export-key`
- Encryption status displayed in server startup banner
- `NEXE_ENCRYPTION_ENABLED` environment variable for Docker/CI configuration
- Docker support: Dockerfile (Python 3.12-slim + embedded Qdrant), docker-compose.yml, docker-entrypoint.sh
- Linux compatibility: conditional imports for macOS-only dependencies, platform-specific install guards
- `NEXE_DEFAULT_MAX_TOKENS` environment variable to configure LLM response length
- CLI `--verbose` flag for detailed per-source RAG weight information
- RAG relevance score bars in Web UI and CLI (aggregate + per-source detail)
- Model size (GB) displayed in model selector dropdown for all three backends
- Model loading indicator with real-time timer in Web UI
- Auto-scroll for thinking/reasoning output box in Web UI
- Ollama auto-start on server boot (macOS background launch, Linux `ollama serve`)
- Ollama VRAM cleanup on server shutdown (unloads all models)
- Backend auto-fallback: if configured backend is unavailable, selects first available backend
- Language selector in Web UI footer (Catalan, Spanish, English) with instant switching
- RAG info panel toggle explaining the relevance filter slider
- Automatic memory via LLM: MEM_SAVE extracts personal facts from conversation
- Memory delete intent: "Forget that..." / "Oblida que..." / "Olvida que..." in three languages
- Per-session document isolation: uploaded documents only visible in their session
- Upload overlay with spinner, filename, and real-time progress timer
- Knowledge base: 36 files (12 documents x 3 languages) with Mermaid architecture diagrams
- Cache-busting for static assets
- Modules loaded count in `/modules` endpoint response
- Trailing slash route for `/v1/` to prevent 307 redirects
- `COMMANDS.md` user-facing command reference documentation

### Fixed
- Streaming broken on second message due to render timer not being nullified
- `httpx.ReadTimeout` errors now logged with `repr()` instead of empty `str()`
- Safari HTTPS redirect: system tray uses `127.0.0.1` instead of `localhost`
- Streaming initialization delay for non-thinking models
- `asyncio.CancelledError` caught in MLX and llama.cpp stream generators
- Router prefix dead code in 4 plugins
- Thinking tokens from Ollama models using `message.thinking` field
- Module discovery: cache validation, correct plugin scan paths, TOML list format
- RAG now searches `nexe_documentation` collection
- RAG `nexe_web_ui` collection always searched
- MEM_SAVE counter shows only successful saves
- MEM_SAVE filters out hallucinated or negative facts before saving
- RAG relevance threshold lowered from 0.40 to 0.30 for better abstract query matching
- Ollama non-streaming response format converted to OpenAI-compatible structure
- MEM_SAVE tags stripped from non-streaming responses
- MEM_SAVE delete-then-re-save loop resolved
- `/v1/memory/search` searches all collections by default
- MLX `config.json` missing treated as error instead of silent warning
- `/ui/info` returns actual runtime backend instead of config default
- `i18n` labels no longer destroy child DOM elements
- CSP-safe language injection via `data-nexe-lang` HTML attribute
- Docker Qdrant health endpoint corrected to `/health`
- Dead code removed: 3 orphan modules, unused imports
- `chunk_text()` unified to single implementation
- `PROJECT_ROOT` resolution standardized via `get_repo_root()`
- 7 silent `except: pass` blocks replaced with proper logging
- Logger lazy formatting in 5 locations
- macOS installer: Python bundled binary signing, payload extraction, venv symlinks

### Security
- Encryption at-rest: Qdrant payloads no longer contain plaintext content (vectors + IDs only)
- Input validation on all Web UI endpoints using `validate_string_input()`
- Path traversal protection on session ID parameters
- Filename validation on file uploads
- Rate limiting on all Web UI endpoints (5-30 requests/minute per endpoint)
- Unicode normalization (NFKC) applied to all 6 injection detectors
- RAG context sanitization aligned between API and UI pipelines
- Docker container runs as non-root user
- Auth failure logging captures real client IP address
- Runtime `print()` calls migrated to `logger.info()`

### Changed
- `chat.py` refactored from 1187 to 230 lines (split into 8 submodules)
- `routes.py` refactored from 974 to 87 lines (split into route modules)
- `tray.py` refactored from 707 to 419 lines
- `lifespan.py` refactored from 681 to 416 lines
- `vector_size=768` centralized to single constant
- 19 HTTPException messages internationalized (ca/es/en)
- System prompt rewritten: general-purpose personal assistant with persistent memory
- Knowledge base rewritten for RAG-optimized chunking
- Request timeout increased from 30s to 600s
- Codebase consolidation: 52 quality findings applied
- `colorama` dependency removed; `pyyaml` bumped; `tomli` removed
- Requires new dependencies: `cryptography>=44.0.0`, `keyring>=25.0.0`, `sqlcipher3>=0.5.0`
- Test suite: 3987 passing tests with 0 regressions

## [0.8.2] - 2026-03-23

### Fixed
- RAG document deduplication on ingestion
- WebSocket control frame handling (ping/pong)
- Web UI sessionStorage race condition
- Memory `.count` endpoint consistency
- Llama.cpp conditional import (avoid crash when not installed)
- Circuit breaker resilience pattern hardened
- Chat endpoint streaming timeout for thinking models (300s configurable via NEXE_OLLAMA_STREAM_TIMEOUT)
- `num_predict` increased to 4096 for thinking models
- Security: injection detectors, input sanitizers, request validators improved
- Sanitizer pattern matching edge cases
- Module manager: discovery, lifecycle, registry, sync wrapper, path discovery refactored
- Plugin loading pipeline: extractor, finder, importer, lifecycle, validator hardened
- Memory persistence engine and text chunker edge cases
- OpenAPI merger and route manager stability
- Ollama health check reliability
- Llama.cpp config validation
- Event system and metrics collector robustness
- 35 test fixes across core, plugins, personality, and memory
- Web UI module tests (manifest, memory helper async, module)
- Security test coverage gaps and module allowlist tests

## [0.8.1] - 2026-03-21

### Added
- Headless installer for DMG wizard integration (install_headless.py)
- macOS menu bar tray app: start/stop server, RAM monitor, uptime, uninstaller (tray.py)
- Model catalog JSON export for Swift wizard (export_catalog_json.py)
- Tray icons with graceful fallback if missing
- Qwen3.5 models (2B, 4B, 9B, 27B) added to catalog (Ollama only — multimodal)

### Fixed
- Logger crash: "Attempt to overwrite 'module' in LogRecord" — reserved field renamed
- Web UI always showed English regardless of installation language — server now injects NEXE_LANG into HTML
- Qwen3.5 MLX removed from catalog (vision_tower incompatible with mlx_lm text-only)
- Uninstaller simplified: double confirmation dialog instead of text input
- export_catalog_json.py creates output directory if missing

## [0.8.0] - 2026-03-16

### Added
- Web UI with chat, file upload, and session management
- RAG (Retrieval-Augmented Generation) with Qdrant vector store
- Multi-engine support: MLX, Llama.cpp, Ollama
- Prefix caching for MLX (prompt cache manager)
- Session compaction with LLM summarization
- Security module with injection detection and sanitization
- Modular plugin architecture with personality system
- i18n support (Catalan, Spanish, English)
- CLI client for chat, memory, and status
- Guided installer with hardware detection

### Security
- API key authentication for all endpoints
- CSP headers (script-src 'self', no unsafe-inline)
- CSRF protection
- Rate limiting
- Input sanitization (jailbreak + injection detection)
- Trusted host middleware

### Fixed
- HuggingFace offline mode enforcement
- API key first-run UX message
- compactMatch scope variable declaration
- MAX_TAGS limit increased to 15
