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
- Upload content denylist (v0.9.1+): scans first 8KB of uploads for API tokens (`sk-ant-`, `sk-proj-`, `ghp_`, `github_pat_`, `AIzaSy`), PEM private keys, and `/etc/passwd` signatures. Speed-bump only — protects against accidental upload, not determined adversaries.

### Jailbreak detection (v0.9.1+)
- 47 pattern speed-bump detector for common jailbreak attempts (multilingual: ca/en/es)
- Injects `[SECURITY NOTICE]` prefix instead of rejecting — preserves UX on false positives
- Defense-in-depth only. Sophisticated attacks evade trivially. Real protection requires model-level content moderation.

### Memory and RAG injection protection (v0.9.1+)
- Memory tag stripping on all input: `[MEM_SAVE:]`, `[SYSTEM:]`, `[USER:]`, `[ASSISTANT:]`, `[TOOL:]`, `[FUNCTION:]`, `[MEMORY:]`, `[MEMORIA:]`
- Applied uniformly on both `/ui/chat` and `/v1/chat/completions` (previously only Web UI was protected)
- RAG ingest pipeline applies `_filter_rag_injection` to document chunks before storing
- Anti-re-save guard prevents delete-then-memorize loops
- **v0.9.9 hardening:** `_filter_rag_injection` now also neutralizes `[MEM_DELETE:…]`, `[MEM_SAVE:…]`, `[OLVIDA|OBLIT|FORGET:…]` and `[MEMORIA:…]` at both ingest time (`ingest_docs`, `ingest_knowledge`) and retrieval time (`_sanitize_rag_context`). A malicious document can no longer embed a `MEM_DELETE` tag that the LLM would copy verbatim — every such tag becomes `[FILTERED]` before the model ever sees it.
- **v0.9.9 clear-all safety rail:** "oblida-ho tot" / "forget everything" triggers `clear_all` intent with an explicit two-turn confirmation (`session._pending_clear_all`). Nothing is wiped until the user confirms with `sí, esborra-ho tot` / `yes delete everything` / `confirmo` / `go ahead`.

### Pipeline enforcement (v0.9.1+)
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

### Encryption at rest (default `auto`, fail-closed, v0.9.2+)
- AES-256-GCM with HKDF-SHA256 key derivation
- Master Encryption Key (MEK) fallback order: **file → keyring → env → generate** (v0.9.9, bug #19b). The file at `~/.nexe/master.key` (mode `0o600`) is written on every generation and synced from the keyring when only the keyring has a key, so `.enc` sessions and SQLCipher data survive macOS upgrades, Keychain resets, and sandbox changes.
- SQLCipher for encrypted SQLite databases
- **Default is `auto`** (v0.9.2+): if `sqlcipher3` is available at startup, encryption is enabled automatically. If it is not, the server logs a `WARNING` and continues in plaintext. Set `NEXE_ENCRYPTION_ENABLED=false` to suppress the warning, or `NEXE_ENCRYPTION_ENABLED=true` to require encryption.
- **Fail-closed** (v0.9.1+): when encryption is explicitly required (`NEXE_ENCRYPTION_ENABLED=true`) and `sqlcipher3` is not installed, the server refuses to start with a clear `RuntimeError`. No silent fallback to plaintext.
- Session files encrypted (`.json` to `.enc` migration). Corrupted `.enc` files log at `ERROR` level and `SessionManager` exposes `corrupted_sessions_count` for health checks (v0.9.9, bug #19c).
- RAG document text removed from Qdrant payloads (stored in encrypted TextStore)
- CLI: `nexe encryption status`, `nexe encryption encrypt-all`, `nexe encryption export-key`

### Logging
- Structured security event logs (JSON format)
- Auth successes/failures, rate limit events, jailbreak detections, module rejections logged
- No `print()` calls in production code — all output via structured logger

## What this project has NOT done

Honest disclosure:

- **Not tested in production.** Server Nexe has not been deployed in a production environment with real users. All testing has been done in development by the author. The 4842 automated tests cover code correctness, not real-world adversarial conditions.
- **No human security audit.** All security testing has been performed by AI (Claude). AI can find patterns and run systematic checks, but it is not a substitute for a professional penetration test.
- **No formal threat model document.** The threat model above is implicit in the code, not a reviewed artifact.
- **No bug bounty program.** This is a personal project with no budget for bounties.
- **No CVE tracking process.** If a vulnerability is found, it will be fixed in the next release.
- **No SOC 2, ISO 27001, or similar certification.** This is a local tool, not a SaaS.

The AI audit covered: injection detection, authentication flows, rate limiting, encryption implementation, input validation, header security, and common OWASP patterns. Results were applied as code fixes. Tests verify the fixes hold. But "AI-audited" is not the same as "independently audited by security professionals," and "tested in dev" is not the same as "battle-tested in production."

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.0-beta    | Current release, receives fixes |
| 0.9.9         | End of line (superseded by 1.0.0-beta) |
| 0.9.0 – 0.9.8 | Not supported — upgrade to 1.0.0-beta |
| < 0.9.0       | Not supported |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security bugs.

Use GitHub's private reporting flow:
1. Go to the repository **Security** tab
2. Click **Report a vulnerability**

If that option is not available, open a minimal issue that says "security report requested" and ask for a private contact channel.

**Response time:** I aim to acknowledge reports within 72 hours and provide a fix timeline within one week. This is a personal project maintained in spare time, so response times may vary.

## Security-related configuration

| Setting | Default | Purpose | Location |
|---------|---------|---------|----------|
| `NEXE_PRIMARY_API_KEY` | _required_ | API authentication | `.env` |
| `NEXE_ENCRYPTION_ENABLED` | `auto` | Enable encryption at rest (`auto` = on if `sqlcipher3` present, else plaintext with warning; `true` = required, fail-closed; `false` = plaintext, no warning) | `.env` or environment |
| `NEXE_MASTER_KEY` | _unset_ | Overrides the MEK source (env slot in the file → keyring → env → generate chain) | `.env` or environment |
| `NEXE_TRUSTED_HOSTS` | _unset_ | Allowed host headers | `.env` |

## Dependencies

Server Nexe uses `cryptography` (>=44.0.0) for encryption, `keyring` (>=25.0.0) for master key storage, and `sqlcipher3` (>=0.5.0) for encrypted databases. These are maintained, well-audited libraries. The full dependency list is in `requirements.txt`.

---

*v1.0.0-beta · Apache 2.0 · Jordi Goy*
