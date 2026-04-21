# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-security-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "server-nexe 1.0.2-beta security: dual-key authentication, rate limiting (incl. PATCH thinking 10/min and NEXE_RATE_LIMIT_GLOBAL 100/min), 6 injection detectors, 47 jailbreak patterns, OWASP headers, RFC5424 logging, AES-256-GCM encryption at-rest (SQLCipher, .enc sessions), MEK fallback order (file->keyring->env->generate), RAG injection sanitization (_filter_rag_injection). Fully local, zero external calls."
tags: [security, authentication, api-key, dual-key, rate-limiting, headers, csp, injection, jailbreak, sanitizer, ai-audit, logging, rfc5424, encryption, crypto, sqlcipher, local, privacy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Security — server-nexe 1.0.2-beta

## Table of contents

- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
  - [API endpoints (configurable via `.env`)](#api-endpoints-configurable-via-env)
  - [Web UI endpoints (hardcoded per endpoint)](#web-ui-endpoints-hardcoded-per-endpoint)
- [Security Headers (OWASP)](#security-headers-owasp)
- [Input Validation](#input-validation)
  - [API pipeline (/v1/*)](#api-pipeline-v1)
  - [Web UI pipeline (/ui/*)](#web-ui-pipeline-ui)
  - [RAG context sanitization](#rag-context-sanitization)
- [Injection Detection](#injection-detection)
- [Audit Logging](#audit-logging)
- [Encryption at Rest (default `auto`)](#encryption-at-rest-default-auto)
  - [CryptoProvider](#cryptoprovider)
  - [What is encrypted](#what-is-encrypted)
  - [How to enable](#how-to-enable)
  - [Backwards compatibility](#backwards-compatibility)
- [Privacy](#privacy)
- [Security Audits](#security-audits)
  - [AI Audit v1 (March 2026)](#ai-audit-v1-march-2026)
  - [AI Audit v2 (March 2026)](#ai-audit-v2-march-2026)
  - [Mega-Test v1 Pre-Release (March 2026)](#mega-test-v1-pre-release-march-2026)
  - [Mega-Test v2 Post-Fixes (March 2026)](#mega-test-v2-post-fixes-march-2026)
  - [Key fixes from audits](#key-fixes-from-audits)
  - [Honesty note](#honesty-note)
- [Accepted Risks](#accepted-risks)
- [Security Checklist](#security-checklist)
- [Reporting Vulnerabilities](#reporting-vulnerabilities)

server-nexe 1.0.2-beta is designed for trusted local environments. All data stays on-device. No telemetry, no external calls.

## Authentication

**Dual-key system** with rotation support:
- `NEXE_PRIMARY_API_KEY` — always active, configured in `.env`
- `NEXE_SECONDARY_API_KEY` — grace period key for rotation
- Expiry tracking: `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`
- Validation: `secrets.compare_digest()` (timing-safe comparison)
- Header: `X-API-Key`

**Bootstrap token:** One-time setup token generated at startup. 256-bit entropy, SQLite-persistent, 30-minute TTL. Localhost-only regeneration.

## Rate Limiting

Rate limiting is applied to **all endpoints** — both the API (`/v1/*`) and the Web UI (`/ui/*`).

### API endpoints (configurable via `.env`)

| Variable | Default | Endpoints |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 20/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 5/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | All other endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Global cap |

**Note:** These variables are reserved for future implementation. Current limits are configured in source code.

### Web UI endpoints (hardcoded per endpoint)

| Endpoint | Rate limit |
|----------|-----------|
| POST /ui/chat | 20/minute |
| POST /ui/memory/save | 10/minute |
| POST /ui/memory/recall | 30/minute |
| POST /ui/upload | 5/minute |
| POST /ui/files/cleanup | 5/minute |
| GET /ui/session/{id} | 30/minute |
| GET /ui/session/{id}/history | 30/minute |
| DELETE /ui/session/{id} | 10/minute |
| PATCH /ui/session/{id}/thinking | 10/minute |

Implementation: `slowapi` with `@limiter.limit()` decorator on every endpoint. `RateLimitTracker` in `plugins/security/core/rate_limiting.py`.

## Security Headers (OWASP)

Applied via `core/security_headers.py` and middleware:

- `Content-Security-Policy`: script-src 'self' (no inline scripts — i18n uses `data-nexe-lang` attribute instead)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (deprecated, CSP used instead)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()

## Input Validation

### API pipeline (/v1/*)

The API endpoint `POST /v1/chat/completions` validates and sanitizes input through its own pipeline.

### Web UI pipeline (/ui/*)

**All Web UI endpoints** use `validate_string_input()` for input validation:

- `/ui/chat` — validates message content
- `/ui/memory/save` — validates content, session_id
- `/ui/memory/recall` — validates query, session_id
- `/ui/session/{id}` (GET/DELETE) — validates session_id (path traversal protection)
- `/ui/upload` — validates filename (path traversal protection)

`validate_string_input()` accepts a `context` parameter:
- `context="chat"` — disables command injection and LDAP detectors (too many false positives on normal conversation)
- `context="path"` — strict validation for path parameters (session_id, filename)

### RAG context sanitization

`_sanitize_rag_context()` is applied to RAG context before injection into the LLM prompt via the Web UI. This filters injection patterns from retrieved documents and memory entries, preventing stored content from being used as attack vectors.

**Pipeline consistency:** As of v0.9.0, the API and Web UI share the same security layers — input validation, RAG sanitization, and rate limiting are applied consistently across both interfaces.

## Injection Detection

**6 injection detectors** in `plugins/security/core/injection_detectors.py`:
1. XSS detector
2. SQL injection detector
3. NoSQL injection detector
4. Command injection detector
5. Path traversal detector
6. LDAP injection detector

**Unicode normalization:** All 6 detectors apply `unicodedata.normalize('NFKC', text)` before pattern matching. This prevents bypass via Unicode homoglyphs or encoding variations (e.g., fullwidth characters, composed vs decomposed forms).

**47 jailbreak patterns** in `plugins/security/sanitizer/`: Multilingual pattern matching for prompt injection attempts.

**RAG injection tag neutralisation** (`_filter_rag_injection`, v0.9.9): on ingest and retrieval, the system **neutralises control tags** that could manipulate memory via side-effect:

- `[MEM_SAVE:…]` — removed (prevents auto-save induced by a document)
- `[MEM_DELETE:…]` — removed
- `[OLVIDA:…]` / `[OBLIT:…]` / `[FORGET:…]` — removed (trilingual)
- `[MEMORIA:…]` — removed

This is part of the Bug #18 fix (see RAG.md). It applies both on ingest (when a document or memory is stored) and on retrieval (when content is fetched for injection into the prompt).

**Request size limit:** 100MB maximum request body (DoS protection).

**Log truncation:** User messages are truncated to 200 characters in log output to prevent log injection and reduce log volume.

## Audit Logging

**RFC5424-compliant** security event logging via `plugins/security/security_logger/`:
- Log path: `storage/system-logs/security/`
- Events: auth failures, rate limit triggers, injection attempts, admin actions
- Real IP logging: `request.client.host`
- Runtime logging uses `logger.info()` instead of `print()` (migrated in v0.9.0)

## Encryption at Rest (default `auto`)

**Added in v0.9.0, default `auto` since v0.9.2.** Encryption at rest activates automatically if `sqlcipher3` is available (mode `auto`). It has been tested (68 tests) but has not yet been through production use with real users outside development.

### CryptoProvider

- Algorithm: **AES-256-GCM** with **HKDF-SHA256** key derivation
- **MEK (Master Encryption Key) fallback chain** (corrected in v0.9.9 — Bug #19b): **file `~/.nexe/master.key` (permissions 600) → OS Keyring (macOS Keychain) → env var `NEXE_MASTER_KEY` → new generation**.
  - This allows `.enc` sessions to survive a Keychain reset provided the local file or env var remains intact.
  - Before v0.9.9 the order was keyring first, and a Keychain reset made the data unrecoverable.
- Derived keys per purpose: `"sqlite"`, `"sessions"`, `"text_store"`, `"backup"`
- Implementation: `core/crypto/provider.py`

**Migrating the master key to a new machine:**

If you change computers or reinstall the system, you must move the master key to keep access to `.enc` sessions and the encrypted database. The fallback chain since v0.9.9 is: `~/.nexe/master.key` file → OS Keyring → environment variable.

```bash
# 1. On the OLD machine — export the key
#    Option A: from the keychain (if stored there)
security find-generic-password -s "server-nexe" -w 2>/dev/null | xxd -r -p > master.key.backup

#    Option B: direct file copy
cp ~/.nexe/master.key master.key.backup

# 2. Transfer master.key.backup to the new machine (USB, SCP, AirDrop)

# 3. On the NEW machine — place the key
mkdir -p ~/.nexe
cp master.key.backup ~/.nexe/master.key
chmod 600 ~/.nexe/master.key

# 4. Delete the backup
shred -u master.key.backup
```

Without the original key, `.enc` sessions and the SQLCipher database **cannot be decrypted**. There is no recovery possible.

### What is encrypted

| Component | Method | Details |
|-----------|--------|---------|
| SQLite database (memories.db) | SQLCipher | Automatic migration from plaintext to encrypted |
| Chat sessions | .json → .enc | AES-256-GCM, nonce(12) + ciphertext + tag(16) |
| RAG text (documents) | TextStore | Text stored in SQLite (optionally SQLCipher), not in Qdrant |
| Qdrant payloads | Vectors only | Payloads contain only `entry_type` and `original_id` — no text |

### How to enable

```bash
# Enable encryption
export NEXE_ENCRYPTION_ENABLED=true

# Check status
./nexe encryption status

# Migrate existing data
./nexe encryption encrypt-all

# Export master key (for backup)
./nexe encryption export-key
```

### Backwards compatibility

Everything is backwards compatible. If encryption is not enabled, behavior is identical to previous versions. Zero changes for users who don't activate it.

## Privacy

- Zero telemetry, zero external API calls
- All data (conversations, documents, embeddings, models) stored locally
- Qdrant payloads no longer contain text content (vectors + IDs only)
- Optional encryption at rest for SQLite, sessions, and document text
- No cookies, no tracking, no analytics

## Security Audits

All security audits are performed by autonomous AI sessions **(Claude, Gemini, Codex, and other models depending on availability)** as part of the development process. The developer launches dedicated review sessions that analyze code, run tests, and generate structured reports with findings. When a decision needs to be challenged or bias detected, **cross-reviews** are run (one AI audits what another AI produced). These are not external audits by human third-party security firms.

### AI Audit v1 (March 2026)
- 73 findings across 11 areas
- 40 fixes implemented
- Grade: B+ → A-

### AI Audit v2 (March 2026)
- 12 additional findings
- All resolved
- 229 failing tests → 0
- Grade: A

### Mega-Test v1 Pre-Release (March 2026)
- 4-phase autonomous audit: baseline, security (23 findings), functional (158 tests), GO/NO-GO
- 23 findings (1 critical, 6 high, 7 medium, 7 low)
- Verdict: **GO WITH CONDITIONS**
- Fixes applied: UI input validation, RAG context sanitization, rate limiting, dependency CVEs

### Mega-Test v2 Post-Fixes (March 2026)
- Same 4-phase methodology, re-run after applying v1 fixes
- 10 findings (vs 23 in v1, **57% reduction**)
- 7 additional fixes applied: memory endpoint validation (CRITICAL), session path traversal, filename validation, rate limiting all UI endpoints, Unicode normalization in injection detectors, print()→logger migration
- Final run (v0.9.9): **4842 collected tests passed, 0 failed** (4990 total, 148 deselected by markers)
- Verdict: **GO WITH CONDITIONS** (improved)

### Key fixes from audits
- Memory endpoint input validation (NF-001 — CRITICAL)
- Session path traversal protection (NF-002)
- Upload filename validation (NF-003)
- Rate limiting on all UI endpoints (NF-004)
- Unicode normalization in 6 injection detectors (NF-005/006)
- Router prefix set in constructor (FastAPI bug)
- Real IP logging in auth failures (F-013)
- Sanitizer context parameter to reduce false positives in chat (F-005)
- `repr(e)` instead of `str(e)` for httpx exceptions (empty string bug)
- print() → logger.info() migration for runtime code
- Dependencies CVEs fixed (pypdf, starlette)

### Honesty note

These AI audits find many issues but are **not exhaustive** — there are certainly vulnerabilities and bugs that have not been detected. Actual test coverage is **~85% global** (honest baseline, not inflated — old badges of 97.4%/91.1%/93% were overly optimistic phase-specific numbers and have been revised). The encryption system is new and has not been battle-tested in production with real users yet. This is a personal open-source project reviewed by AI, not a formally audited enterprise product.

## Accepted Risks

- **Local model limitations:** Models may follow prompt injection instructions. Mitigation: sanitizer + jailbreak patterns + Unicode normalization.
- **Single-user design:** No multi-user isolation. One API key = full access.
- **No TLS by default:** HTTP on localhost. Use reverse proxy (nginx/caddy) for HTTPS if exposing to network.
- **Encryption defaults to `auto`:** Activates automatically if `sqlcipher3` is available. Can be forced with `NEXE_ENCRYPTION_ENABLED=true` or disabled with `false`.
- **New encryption system:** CryptoProvider is recently added and has not been through production use with external users.

## Security Checklist

- [ ] `.env` file has restricted permissions (chmod 600)
- [ ] API keys are strong (32+ hex characters)
- [x] Qdrant embedded — no network port exposed (no firewall rules needed for Qdrant)
- [ ] Server port (9119) bound to 127.0.0.1 (not 0.0.0.0)
- [ ] Disk encryption enabled (FileVault on macOS, LUKS on Linux)
- [ ] Rate limiting configured appropriately
- [ ] Encryption at rest enabled if handling sensitive data (`NEXE_ENCRYPTION_ENABLED=true`)
- [ ] Regular updates applied
- [ ] Security logs reviewed periodically

## Reporting Vulnerabilities

Report security issues via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
