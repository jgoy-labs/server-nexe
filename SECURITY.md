# Security Policy

## Scope and threat model

Server Nexe is a **single-user, local-first** AI server. It is designed to run on a personal machine behind `127.0.0.1`, not exposed to the public internet. The security model assumes a trusted local user and defends primarily against:

- Accidental exposure of the API port
- Prompt injection and jailbreak attempts via chat input
- Unauthorized access if the port is reachable on a local network
- Data at rest on a shared or stolen device

It does **not** defend against:

- A malicious user with shell access to the same machine
- Nation-state adversaries
- Multi-tenant or multi-user deployments

## Current protections

### Authentication
- API key required for all endpoints (`X-API-Key` header)
- Key configured via `.env` file with restricted permissions
- Auth failures logged with client IP

### Input validation
- 6 injection detectors: XSS, SQL, NoSQL, command injection, path traversal, LDAP
- Unicode normalization (NFKC) applied before detection
- `validate_string_input()` on all Web UI endpoints
- Filename validation on file uploads
- Path traversal protection on session IDs
- Upload content denylist (v0.9.1): scans first 8KB of uploads for API tokens (`sk-ant-`, `sk-proj-`, `ghp_`, `github_pat_`, `AIzaSy`), PEM private keys, and `/etc/passwd` signatures. Speed-bump only — protects against accidental upload, not determined adversaries.

### Jailbreak detection (v0.9.1)
- 47 pattern speed-bump detector for common jailbreak attempts (multilingual: ca/en/es)
- Injects `[SECURITY NOTICE]` prefix instead of rejecting — preserves UX on false positives
- Defense-in-depth only. Sophisticated attacks evade trivially. Real protection requires model-level content moderation.

### Memory and RAG injection protection (v0.9.1)
- Memory tag stripping on all input: `[MEM_SAVE:]`, `[SYSTEM:]`, `[USER:]`, `[ASSISTANT:]`, `[TOOL:]`, `[FUNCTION:]`, `[MEMORY:]`, `[MEMORIA:]`
- Applied uniformly on both `/ui/chat` and `/v1/chat/completions` (previously only Web UI was protected)
- RAG ingest pipeline applies `_filter_rag_injection` to document chunks before storing
- Anti-re-save guard prevents delete-then-memorize loops

### Pipeline enforcement (v0.9.1)
- All chat goes through two canonical endpoints: `/ui/chat` (Web UI) and `/v1/chat/completions` (OpenAI-compatible API)
- Direct plugin endpoints (`/mlx/chat`, `/llama-cpp/chat`, `/ollama/api/chat`) removed — return 403
- Ensures all requests pass through the full security pipeline (auth, rate limiting, input validation, jailbreak detection, memory tag stripping)

### Rate limiting
- Per-endpoint rate limits hardcoded in route decorators:
  - `/v1/chat/completions`: 20/minute
  - `/ui/chat`: 20/minute
  - `/ui/upload`: 5/minute
  - `/ui/memory/*`: 10-30/minute depending on operation
- Applied to all Web UI and API endpoints

### Transport and headers
- CSRF protection
- CSP headers (`script-src 'self'`, no `unsafe-inline`)
- Trusted host middleware
- No inline scripts — language injection via `data-` HTML attributes

### Encryption at rest (opt-in, v0.9.0+)
- AES-256-GCM with HKDF-SHA256 key derivation
- Master key stored in OS Keyring (preferred), environment variable, or file fallback
- SQLCipher for encrypted SQLite databases
- **Fail-closed** (v0.9.1): server refuses to start if encryption is requested but `sqlcipher3` is not installed. No silent fallback to plaintext.
- Session files encrypted (.json to .enc migration)
- RAG document text removed from Qdrant payloads (stored in encrypted TextStore)
- CLI: `nexe encryption status`, `nexe encryption encrypt-all`, `nexe encryption export-key`

### Logging
- Structured security event logs (JSON format)
- Auth successes/failures, rate limit events, jailbreak detections, module rejections logged
- No `print()` calls in production code — all output via structured logger

## What this project has NOT done

Honest disclosure:

- **Not tested in production.** Server Nexe has not been deployed in a production environment with real users. All testing has been done in development by the author. The 4572 automated tests cover code correctness, not real-world adversarial conditions.
- **No human security audit.** All security testing has been performed by AI (Claude). AI can find patterns and run systematic checks, but it is not a substitute for a professional penetration test.
- **No formal threat model document.** The threat model above is implicit in the code, not a reviewed artifact.
- **No bug bounty program.** This is a personal project with no budget for bounties.
- **No CVE tracking process.** If a vulnerability is found, it will be fixed in the next release.
- **No SOC 2, ISO 27001, or similar certification.** This is a local tool, not a SaaS.

The AI audit covered: injection detection, authentication flows, rate limiting, encryption implementation, input validation, header security, and common OWASP patterns. Results were applied as code fixes. Tests verify the fixes hold. But "AI-audited" is not the same as "independently audited by security professionals," and "tested in dev" is not the same as "battle-tested in production."

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.9.1   | Current release, receives fixes |
| 0.8.2   | No longer supported |
| < 0.8.0 | Not supported |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security bugs.

Use GitHub's private reporting flow:
1. Go to the repository **Security** tab
2. Click **Report a vulnerability**

If that option is not available, open a minimal issue that says "security report requested" and ask for a private contact channel.

**Response time:** I aim to acknowledge reports within 72 hours and provide a fix timeline within one week. This is a personal project maintained in spare time, so response times may vary.

## Security-related configuration

| Setting | Purpose | Location |
|---------|---------|----------|
| `NEXE_PRIMARY_API_KEY` | API authentication | `.env` |
| `NEXE_ENCRYPTION_ENABLED` | Enable encryption at rest | `.env` or environment |
| `NEXE_TRUSTED_HOSTS` | Allowed host headers | `.env` |

## Dependencies

Server Nexe uses `cryptography` (>=44.0.0) for encryption, `keyring` (>=25.0.0) for master key storage, and `sqlcipher3` (>=0.5.0) for encrypted databases. These are maintained, well-audited libraries. The full dependency list is in `requirements.txt`.

---

*v0.9.1 · Apache 2.0 · Jordi Goy*
