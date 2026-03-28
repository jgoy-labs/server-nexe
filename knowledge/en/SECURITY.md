# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-security-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Security documentation for server-nexe 0.8.5 pre-release. Covers dual-key API authentication with rotation, rate limiting (all endpoints), 6 injection detectors with Unicode normalization, 69 jailbreak patterns, OWASP security headers, RFC5424 audit logging, input validation (validate_string_input on all UI routes), RAG context sanitization, encryption at-rest (CryptoProvider AES-256-GCM, SQLCipher, encrypted sessions), AI audit results (v1+v2+mega-test), and security checklist."
tags: [security, authentication, api-key, dual-key, rate-limiting, headers, csp, injection, jailbreak, sanitizer, ai-audit, logging, rfc5424, encryption, crypto, sqlcipher]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Security — server-nexe 0.8.5 pre-release

server-nexe is designed for trusted local environments. All data stays on-device. No telemetry, no external calls.

## Authentication

**Dual-key system** with rotation support:
- `NEXE_PRIMARY_API_KEY` — always active, configured in `.env`
- `NEXE_SECONDARY_API_KEY` — grace period key for rotation
- Expiry tracking: `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`
- Validation: `secrets.compare_digest()` (timing-safe comparison)
- Header: `X-API-Key`

**Bootstrap token:** One-time setup token generated at startup. 128-bit entropy, SQLite-persistent, 30-minute TTL. Localhost-only regeneration.

## Rate Limiting

Rate limiting is applied to **all endpoints** — both the API (`/v1/*`) and the Web UI (`/ui/*`).

### API endpoints (configurable via `.env`)

| Variable | Default | Endpoints |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | All other endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Global cap |

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

Implementation: `slowapi` with `@limiter.limit()` decorator on every endpoint. `RateLimitTracker` in `plugins/security/core/rate_limiting.py`.

## Security Headers (OWASP)

Applied via `core/security_headers.py` and middleware:

- `Content-Security-Policy`: script-src 'self' (no inline scripts — i18n uses `data-nexe-lang` attribute instead)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (deprecated, CSP used instead)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: restricted

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

**Pipeline consistency:** As of v0.8.5, the API and Web UI share the same security layers — input validation, RAG sanitization, and rate limiting are applied consistently across both interfaces.

## Injection Detection

**6 injection detectors** in `plugins/security/core/injection_detectors.py`:
1. XSS detector
2. SQL injection detector
3. NoSQL injection detector
4. Command injection detector
5. Path traversal detector
6. LDAP injection detector

**Unicode normalization:** All 6 detectors apply `unicodedata.normalize('NFKC', text)` before pattern matching. This prevents bypass via Unicode homoglyphs or encoding variations (e.g., fullwidth characters, composed vs decomposed forms).

**69 jailbreak patterns** in `plugins/security/sanitizer/`: Multilingual pattern matching for prompt injection attempts.

**Request size limit:** 100MB maximum request body (DoS protection).

**Log truncation:** User messages are truncated to 80 characters in log output to prevent log injection and reduce log volume.

## Audit Logging

**RFC5424-compliant** security event logging via `plugins/security/security_logger/`:
- Log path: `storage/system-logs/security/`
- Events: auth failures, rate limit triggers, injection attempts, admin actions
- Real IP logging: `request.client.host`
- Runtime logging uses `logger.info()` instead of `print()` (migrated in v0.8.5)

## Encryption at Rest (opt-in)

**Added in v0.8.5.** Encryption at rest is opt-in and recently added. It has been tested (68 tests) but has not yet been through production use with real users outside development.

### CryptoProvider

- Algorithm: **AES-256-GCM** with **HKDF-SHA256** key derivation
- Key management chain: OS Keyring (macOS Keychain) → env var `NEXE_MASTER_KEY` → file `~/.nexe/master.key` (permissions 600)
- Derived keys per purpose: `"sqlite"`, `"sessions"`, `"text_store"`, `"backup"`
- Implementation: `core/crypto/provider.py`

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

All security audits are performed by autonomous AI sessions (Claude) as part of the development process. The developer launches dedicated review sessions that analyze code, run tests, and generate structured reports with findings. These are not external audits by third-party security firms.

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
- 4-phase autonomous audit: baseline (298 tests, 97.4% coverage), security (23 findings), functional (158 tests, 91.1%), GO/NO-GO
- 23 findings (1 critical, 6 high, 7 medium, 7 low)
- Verdict: **GO WITH CONDITIONS**
- Fixes applied: UI input validation, RAG context sanitization, rate limiting, dependency CVEs

### Mega-Test v2 Post-Fixes (March 2026)
- Same 4-phase methodology, re-run after applying v1 fixes
- 10 findings (vs 23 in v1, **57% reduction**)
- 7 additional fixes applied: memory endpoint validation (CRITICAL), session path traversal, filename validation, rate limiting all UI endpoints, Unicode normalization in injection detectors, print()→logger migration
- 3213 tests passed, 0 failed
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
- Docker USER non-root (F-030)
- print() → logger.info() migration for runtime code
- Dependencies CVEs fixed (pypdf, starlette)

### Honesty note

These AI audits find many issues but are **not exhaustive** — there are certainly vulnerabilities and bugs that have not been detected. Test coverage (97.4% baseline, 91.1% functional) is good but not 100%. The encryption system is new and has not been battle-tested in production with real users yet. This is a personal open-source project reviewed by AI, not a formally audited enterprise product.

## Accepted Risks

- **Local model limitations:** Models may follow prompt injection instructions. Mitigation: sanitizer + jailbreak patterns + Unicode normalization.
- **Single-user design:** No multi-user isolation. One API key = full access.
- **No TLS by default:** HTTP on localhost. Use reverse proxy (nginx/caddy) for HTTPS if exposing to network.
- **Encryption is opt-in:** Not enabled by default. Users must explicitly activate it.
- **New encryption system:** CryptoProvider is recently added and has not been through production use with external users.

## Security Checklist

- [ ] `.env` file has restricted permissions (chmod 600)
- [ ] API keys are strong (32+ hex characters)
- [ ] Qdrant port (6333) not exposed to network
- [ ] Server port (9119) bound to 127.0.0.1 (not 0.0.0.0)
- [ ] Disk encryption enabled (FileVault on macOS, LUKS on Linux)
- [ ] Rate limiting configured appropriately
- [ ] Encryption at rest enabled if handling sensitive data (`NEXE_ENCRYPTION_ENABLED=true`)
- [ ] Regular updates applied
- [ ] Security logs reviewed periodically

## Reporting Vulnerabilities

Report security issues via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
