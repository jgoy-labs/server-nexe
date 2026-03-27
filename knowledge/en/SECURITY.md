# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-security-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Security documentation for server-nexe 0.8.2. Covers dual-key API authentication with rotation, rate limiting (6 tiers), 6 injection detectors (XSS, SQL, NoSQL, command, path traversal, LDAP), 69 jailbreak patterns, OWASP security headers (CSP, HSTS), RFC5424 audit logging, input sanitization with context param, real IP logging. Includes consultoria v1+v2 audit results (73+12 findings, grade A) and security checklist."
tags: [security, authentication, api-key, dual-key, rate-limiting, headers, csp, injection, jailbreak, sanitizer, audit, logging, rfc5424, consultoria]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Security — server-nexe 0.8.2

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

6 configurable tiers via `.env`:

| Tier | Default | Endpoints |
|------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | All other endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Global cap |

Implementation: `RateLimitTracker` in `plugins/security/core/rate_limiting.py`.

## Security Headers (OWASP)

Applied via `core/security_headers.py` and middleware:

- `Content-Security-Policy`: script-src 'self' (no inline scripts — i18n uses `data-nexe-lang` attribute instead)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (deprecated, CSP used instead)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: restricted

## Input Validation & Injection Detection

**6 injection detectors** in `plugins/security/core/injection_detectors.py`:
1. XSS detector
2. SQL injection detector
3. NoSQL injection detector
4. Command injection detector
5. Path traversal detector
6. LDAP injection detector

**Context-aware sanitization:** `validate_string_input()` accepts a `context` parameter (e.g., `context="chat"`) that disables command injection and LDAP detectors for chat messages (too many false positives on normal conversation).

**69 jailbreak patterns** in `plugins/security/sanitizer/`: Multilingual pattern matching for prompt injection attempts.

**Request size limit:** 100MB maximum request body (DoS protection).

## Audit Logging

**RFC5424-compliant** security event logging via `plugins/security/security_logger/`:
- Log path: `storage/system-logs/security/`
- Events: auth failures, rate limit triggers, injection attempts, admin actions
- Real IP logging: `request.client.host` (fixed in consultoria finding F-013, was logging placeholder before)

## Privacy

- Zero telemetry, zero external API calls
- All data (conversations, documents, embeddings, models) stored locally
- Qdrant vectors stored unencrypted on disk (acceptable for trusted local device)
- No cookies, no tracking, no analytics

## Security Audits

### Consultoria v1 (March 2026)
- 73 findings across 11 areas
- 40 fixes implemented
- Grade: B+ → A-

### Consultoria v2 (March 2026)
- 12 additional findings
- All resolved
- 229 failing tests → 0
- Grade: A

### Key fixes from audits
- Router prefix set in constructor (was dead code after constructor — FastAPI bug)
- Real IP logging in auth failures (F-013)
- Sanitizer context parameter to reduce false positives in chat (F-005)
- `repr(e)` instead of `str(e)` for httpx exceptions (empty string bug)
- Docker USER non-root (F-030)
- Dead code elimination (F-006, F-007)

## Accepted Risks

- **Qdrant unencrypted:** Vectors stored in plaintext on disk. Mitigation: local-only access, disk encryption (FileVault/LUKS).
- **Local model limitations:** Models may follow prompt injection instructions. Mitigation: sanitizer + jailbreak patterns.
- **Single-user design:** No multi-user isolation. One API key = full access.
- **No TLS by default:** HTTP on localhost. Use reverse proxy (nginx/caddy) for HTTPS if exposing to network.

## Security Checklist

- [ ] `.env` file has restricted permissions (chmod 600)
- [ ] API keys are strong (32+ hex characters)
- [ ] Qdrant port (6333) not exposed to network
- [ ] Server port (9119) bound to 127.0.0.1 (not 0.0.0.0)
- [ ] Disk encryption enabled (FileVault on macOS, LUKS on Linux)
- [ ] Rate limiting configured appropriately
- [ ] Regular updates applied
- [ ] Security logs reviewed periodically

## Reporting Vulnerabilities

Report security issues via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
