# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
