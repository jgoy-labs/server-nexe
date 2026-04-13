# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

8 bugs resolts en instal·lació neta DMG v0.9.7.

### Fixed

- **Readiness check (P0)**: `ollama_module`, `mlx_module`, `llama_cpp_module` now return
  `DEGRADED` (not `UNHEALTHY`) when the LLM backend is unavailable (Ollama not running,
  model not loaded). The Web UI was blocked at "Iniciant..." on fresh installs because
  `UNHEALTHY` caused the overall readiness to fail; `DEGRADED` unblocks the UI.
- **Wizard: default install folder** now `/Applications/server-nexe` (was `~/server-nexe`).
- **Wizard: models show RAM (ram_gb)** instead of disk size (disk_gb) in model cards.
- **Wizard: tier selector (RAM tabs)** now centered (removed `minWidth: 640` ScrollView).
- **Wizard: "Obrir Nexe" button** shows a 10-second countdown with tray explanation before
  launching. Eliminates the screen flash caused by `killall Dock` at click time.
- **Dock icon "?"**: `doAddToDock()` now uses the actual install path (`engine.installPath`)
  instead of hardcoded `/Applications/Nexe.app`. Fixes broken Dock entry on non-standard paths.
- **Login item path** (`doAddLoginItem`) also fixed to use `engine.installPath`.
- **Logo glitch** on "Iniciant..." overlay: switched from `logo.png` to `logo.svg` for
  crisp rendering at all resolutions without pixel artifacts.

## [0.9.7] - 2026-04-12

Multimodal VLM: suport d'imatges als 4 backends (Ollama, MLX, Llama.cpp, Web UI).

### Added

- **Multimodal images (Ollama)**: `OllamaChat._build_payload()` and `chat()` accept
  `images: Optional[List[str]]` (base64 strings). Passed through to Ollama `/api/chat`.
- **Multimodal images (MLX)**: `_detect_vlm_capability()` reads `config.json` to detect
  VLM architectures (Qwen2-VL, LLaVA, PaliGemma, Gemma3, InternVL). `MLXChatNode._get_model()`
  bifurcates between `mlx_lm.load` (text) and `mlx_vlm.load` (VLM). New `_generate_vlm()`
  method uses `mlx_vlm.generate()` with `PIL.Image`.
- **Multimodal images (Llama.cpp)**: `mmproj_path` config field (env `LLAMA_MMPROJ_PATH`).
  `ModelPool` passes `clip_model_path` to `Llama()` when set. Graceful fallback: images
  ignored with warning if `mmproj_path` not configured.
- **Multimodal images (Web UI backend)**: `/ui/chat` endpoint validates `image_b64` +
  `image_type` (JPEG/PNG/WebP, max 10 MB). Passes `_images_arg` to all 3 engine call paths.
- **Camera button UI**: `#imageBtn` (camera icon), `#imagePreviewBar` (thumbnail strip),
  `#imageInput` (file picker, JPEG/PNG/WebP). `_handleImageSelect()` + `_clearSelectedImage()`.
  `sendMessage()` includes `image_b64` / `image_type` when image pending.
- **Dependency**: `mlx-vlm==0.1.27` added to installer (Apple Silicon). Compatible with
  `mlx-lm==0.30.7` and `transformers>=4.57`.
- **Tests**: 34 new multimodal tests across the 4 plugins (`test_multimodal.py`).

## [0.9.3] - 2026-04-12

Dependency: replace `sentence-transformers` + PyTorch (~600 MB) with `fastembed` (ONNX, ~50 MB).

### Changed

- **Embeddings backend**: `sentence-transformers` replaced by `fastembed` (ONNX runtime). Same
  model (`paraphrase-multilingual-mpnet-base-v2`), same 768-dim vectors, same cosine similarity
  results. No change to Qdrant collections or stored vectors.
- **SSOT**: embedding model name centralised in `memory/embeddings/constants.py`
  (`DEFAULT_EMBEDDING_MODEL`). Change model in one place — `personality/server.toml` or
  `constants.py` — propagates everywhere.
- **Installer**: downloads fastembed model to `~/.cache/fastembed/` instead of HuggingFace cache.
- `requirements.txt`: `sentence-transformers>=4.0.0` → `fastembed>=0.3.6`

### Removed

- PyTorch (`torch`) transitive dependency — no longer pulled in by `sentence-transformers`.
  Saves ~600 MB from the install footprint.

## [0.9.2] - 2026-04-12

Security hardening: 4 P1 fixes from mega-consultoria 2026-04-11.

### Security fixes

- **P1-A** — Rate limit UI auth failures per IP. `make_require_ui_auth()` now
  tracks failed authentication attempts in a per-IP in-memory dict with a 60s
  sliding window. After 20 failures, returns `429 Too Many Requests`. Protects
  `/ui/*` endpoints against brute force. Dict-in-memory is intentional (no
  persistence needed between restarts; nexe 0.9.x is single-worker).
  Commit `6651848`.

- **P1-B** — Auth failures from the Web UI are now logged to the security log.
  Previously `make_require_ui_auth()` raised `401` without calling
  `security_logger.log_auth_failure()`, making brute force against `/ui/chat`
  invisible to SIEM/security monitoring. Now uses the same lazy-import pattern
  as `auth_dependencies.py:185-195`. Commit `293fd45`.

- **P1-C** — Symlink upload attack blocked. Attack vector: `ln -s /etc/passwd
  evil.pdf && curl -F "file=@evil.pdf"` ingested 17 chunks of `/etc/passwd`
  into `user_knowledge`. Fix: `_is_symlink_outside_uploads()` check via
  `os.path.realpath()` immediately after `save_file()`. If the saved path
  resolves outside the uploads directory, the file is deleted and a `400` is
  returned. Does NOT affect model symlinks (MLX/llama.cpp/Ollama never go
  through `/upload`). Commit `353e1f6`.

- **P1-D** — Encryption default changed from `false` to `auto`. Previously all
  sessions were stored in plain text by default, contradicting the
  "privacy-first" README. New behaviour: if `sqlcipher3` is available,
  encryption is auto-enabled at startup; if not, a `WARNING` is logged and the
  server continues in plain text. `NEXE_ENCRYPTION_ENABLED=false` suppresses
  the warning. Existing plain-text data can be migrated with
  `nexe encryption encrypt-all`. Commit `a9970d7`.

## [0.9.1] - 2026-04-11

Consolidated release: Cirurgia Bloc 2 (2026-04-08) + Mega-consultoria hardening (2026-04-11).

### Security fixes (Mega-consultoria 2026-04-11)

Derived from a full security audit (mega-consultoria) with plan v2.4.

- **P0-1** — httpx split timeout for Ollama (chat + models). Previously a
  single 600s default meant Ollama hangs took up to 10 minutes to detect.
  Now `connect=5s` fails fast on a dead server, `read=600s` for chat
  (preserves thinking models like DeepSeek-R1 and QwQ), `read=60s` for
  models list/info/delete (fast operations). Env vars:
  `NEXE_OLLAMA_{CONNECT,READ,MODELS_READ,WRITE,POOL}_TIMEOUT`.
  Commit `61a72a3`.

- **P0-2** — llama_cpp_module ghost detection fixed. `/status` now reports
  `engines_available.llama_cpp` accurately. Three combined changes:
  - **P0-2.b** `core/lifespan_modules.py`: loader removes modules from
    `app.state.modules` when `initialize()` returns `False`. Also uses
    `list(plugin_modules.items())` to iterate safely while popping (avoids
    `RuntimeError: dictionary changed size during iteration`). Commit `af32c2c`.
  - **P0-2.a** `plugins/llama_cpp_module/module.py`: `import llama_cpp`
    check at `initialize()` returns `False` immediately if the native lib
    is missing (no phantom routes). Commit `06d5000`.
  - **P0-2.c** `core/endpoints/root.py`: extracted `_check_llama_cpp_available(modules)`
    helper that verifies `_node is not None`, symmetric with the existing
    MLX check. Helper extraction enables unit testing without a real
    `starlette.Request` (slowapi's `@limiter.limit` rejects `MagicMock`).
    Commit `3cccd7f`.

- **P0-3** — Model switching concurrency: added short `asyncio.Lock()`
  around the `body.model` singleton mutation block in
  `routes_chat.py:_chat_inner`. Commit `7aa18cb`.

    **Design note**: server-nexe v0.9.x is architecturally single-user
    (uvicorn workers=1, class-level singletons `LlamaCppChatNode._pool`
    and `MLXChatNode._model`, in-process state, global
    `_chat_semaphore(2)`). The short lock is a **pragmatic mitigation**
    for the rare edge case of two concurrent requests racing to mutate
    the same singletons. For mono-user local usage the scenario is
    effectively never triggered. A full multi-user architecture refactor
    (multi-pool LRU cache + `config_override` per request + removal of
    class-level singletons + horizontal uvicorn workers) is **deferred**
    until multi-user becomes an actual use case. See the complete
    deferred-work scope documented in ISSUE-multiuser-refactor.md.

- **P1-1** — Jailbreak speed-bump: regex detector for common patterns
  (ca/en: "ignora instruccions", "you are now a/an WORD", "forget your
  rules", "DAN mode", "do anything now", etc.). Hooked after
  `validate_string_input` in `/ui/chat`. **Opció B**: injects a
  `[SECURITY NOTICE]` prefix instead of rejecting (400) to preserve UX on
  false positives. Pattern #3 (`you are now a|an \w+`) is deliberately
  tight to avoid false positives on conversational English ("you are now
  at home", "you are now free to go", etc.). Commit `f8b75b7`.

    **Note**: defense-in-depth only. Sophisticated attackers evade via
    Unicode lookalikes, base64/gzip encoding, chained prompts, language
    switching, etc. For real protection use content moderation at the
    model level.

- **P1-2** — Memory tag strip regex anchored to line start. Catches
  `[MEMORIA:]`, `[MEM:]`, `[SYSTEM:]`, `[USER:]`, `[ASSISTANT:]`,
  `[TOOL:]`, `[FUNCTION:]`, `[MEMORY:]` in addition to the original
  `[MEM_SAVE:]`. Newlines are preserved via capture group 1. Commit `4a91058`.

    **BREAKING** from v0.9.0 (documented inline in the updated tests):
    - Mid-line tags are NO longer stripped. Before: any occurrence of
      `[MEM_SAVE:...]` was stripped regardless of position. From 0.9.1:
      only tags at the start of a line (or after `\n`) are stripped.
      Rationale: reduce false positives on inline text like
      `"review this [USER: Jordi] part"`.
    - Empty tags like `[SYSTEM]` (no colon, no content) now match at
      line start. Closes a jailbreak vector where attackers use bare
      role tags.
    - Equals separator `[MEMORIA=value]` also matches (not only `:`).
    - Accepted tradeoff: `[memoria]` at the very start of a message
      IS stripped even when used as a normal word. Users can work
      around with any prefix.

- **P1-4** — Upload content denylist for sensitive patterns. Scans the
  first 8KB of each upload and rejects with HTTP 400 if a known pattern
  is found. Patterns are tuned to the real stack used by this project:
  - System: `root:x:0:0:` (most specific /etc/passwd signature)
  - PEM private keys: RSA, OpenSSH, PKCS8, EC, DSA, PGP
  - API tokens: `sk-ant-` (Anthropic / Claude Code), `sk-proj-` (OpenAI
    GPT / Codex CLI / Responses API), `ghp_` + `github_pat_` (GitHub
    PAT classic + fine-grained), `AIzaSy` (Google Gemini / AI Studio /
    Cloud / Firebase).

  Commit `145d742`.

    **Note**: speed-bump only, trivially bypassed by `gzip`, `base64`,
    `xor`, or any custom encoding. Protects against accidental drag&drop
    of sensitive files, not determined adversaries. Generic AWS patterns
    were explicitly NOT included — this project does not use AWS and a
    generic OWASP checklist would add noise without value.

### Cirurgia Bloc 2 — Security & Memory Pipeline (2026-04-08)

#### Fixed

- **Item 17 — MEM_SAVE bug**: `POST /v1/memory/store` was rejected by the Gate heuristic (`reason="model_generated"`) because `source="api"` mapped to `is_user_message=False` and `is_mem_save` was not passed. Fixed by passing `is_mem_save=True` — the store endpoint IS an explicit MEM_SAVE operation and should bypass the "model_generated" gate.
- **Item 21 — SQLCIPHER false sense of security**: `core/lifespan.py` declared "encryption ENABLED" without checking `SQLCIPHER_AVAILABLE`. If `sqlcipher3` was missing, sessions were encrypted but the `memories.db` database was not. Fixed with fail-closed behavior: server refuses to start with a clear `RuntimeError` if encryption is requested but `sqlcipher3` is not installed.

#### Security

- **Item 19 — Memory injection via direct API**: `POST /v1/chat/completions` did not apply `strip_memory_tags` to user messages, allowing `[MEM_SAVE: ...]` injection via the API while the Web UI was protected. Fixed.
- **Item 20 — Prompt injection via auto-ingest**: `core/ingest/ingest_knowledge.py` and `core/ingest/ingest_docs.py` did not apply `_filter_rag_injection` to document chunks before storing, while the upload UI path was protected. Fixed.

#### Changed

- **Item 22 — Workflows metadata honest**: `GET /v1/` metadata updated: `workflows.status` changed from `"implemented"` (false) to `"stub-v0.9.1"`. New `core/endpoints/workflows.py` router added that returns `501 Not Implemented` for any `/v1/workflows/*` path.
- **Item 24 — Pipeline unique enforced**: Removed 3 plugin chat endpoints that bypassed the canonical pipeline (`/mlx/chat`, `/llama-cpp/chat`, `/ollama/api/chat`). All chat must go through `/ui/chat` (canonical) or `/v1/chat/completions` (OpenAI-compat). Item 23 (auth bypass) resolved by this removal.

### Deferred to 0.9.2+

- **P1-3** — Auth rate limiting (`TTLCache` + `NEXE_TRUST_PROXY`
  opt-in for `X-Forwarded-For` parsing). Only relevant when exposing
  server-nexe to the internet via a reverse proxy (Caddy, Traefik,
  Tailscale Funnel). For the current mono-user local deployment it is
  unnecessary. Trigger: decision to expose beyond localhost.

- **P0-3 full refactor** — Multi-pool LRU cache at `LlamaCppChatNode` +
  `MLXChatNode`, `config_override` parameter through
  `chat() → execute() → _get_model()`, `dataclasses.replace()` for
  immutable per-request configs, removal of class-level singletons,
  horizontal uvicorn workers, session manager migration.
  Trigger: multi-user becomes an actual use case.

- **QI-37 — Version string consolidation**: Resolved in commit `67242c9`
  (34 files synced to 0.9.1). Future: adopt single-source-of-truth pattern
  (e.g. `importlib.metadata.version("server-nexe")`).

### Known issues

- None. All pre-existing test failures resolved (commit `3e3dad7`:
  test_routes_lang_i18n synced with current_language assignment).

## [0.9.0] - 2026-03-31

### Added
- **Memory v1** — Automatic fact extraction, semantic deduplication, dreaming (offline consolidation). 22 new files, ~4765 lines. Qdrant embedded, zero external processes.
- Qdrant singleton pool for thread-safe concurrent access
- MEM_SAVE input injection prevention (strip user-side tags)
- Security false positive tests (47 scenarios)

### Fixed
- **Tray keyboard lock**: moved RAM polling (`_get_process_ram`) to background daemon thread (`_RamMonitor`). The main event loop (NSApplication/rumps) never calls `subprocess.run` now, preventing keyboard freeze after long runtime
- Installer venv no longer depends on DMG mount path after ejection
- GPT-OSS thinking detection now works during streaming (not retroactively)
- SEC-002: MEM_SAVE tags stripped from user input before LLM processing

### Changed
- Version bump from 0.8.5 to 0.9.0

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
- Docker support: Dockerfile, docker-compose.yml, docker-entrypoint.sh (removed in 0.9.1 — untested, bare-metal only)
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
- Qdrant health endpoint corrected to `/health`
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
- Server process security hardened
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
- Test suite: 4143 passing tests at release time (4572 as of 0.9.1)

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
