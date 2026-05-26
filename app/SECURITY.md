# Security Policy

## Reporting a Vulnerability

This repository is a **starter template** for Tauri v2 desktop apps.

- For vulnerabilities in **this template** (e.g., the `plugin://` resolver, CSP
  baseline, CI workflow, resolve-path logic): open a private security advisory
  via the GitHub Security tab of the repo.
- For vulnerabilities in **Tauri, Vite, or transitive dependencies**: report
  directly to the respective upstream projects. See:
  - Tauri: https://github.com/tauri-apps/tauri/security
  - Vite: https://github.com/vitejs/vite/security
  - RustSec advisory DB: https://rustsec.org/

**Please do not report vulnerabilities via public issues.**

## Supported Versions

This is a template, not a released product. Security fixes will be applied
to the default branch; users are encouraged to keep their fork rebased on
latest.

## Security Baseline

Post-security audit v2 (2026-04-22, tag `v0.1.2-fase0-security-v2`) baseline.
**Updated after independent red team broke v0.1.1-fase0-security** —
Sprint 0.18 tanca els 1 P0 + 2 P1 + 9 P2 + 16 P3
identificats, reescriu 5 tests teatre amb mutation-verified regression, i passa
red team final F7 amb veredicte CLEAR.

**Principi d'enginyeria crític:** cada fix Sprint 0.18 té un test regression
mutation-verified — el test falla amb codi pre-fix i passa amb el codi post-fix.
Un test que passa amb ambdós és teatre i s'ha eliminat o reescrit.

**CSP + WebView:**
- Strict CSP: `default-src 'self'`, no inline scripts, no inline styles (C11).
- Modern directives: `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'` (C12).
- Per-response hardening headers: `Permissions-Policy`, `Referrer-Policy: no-referrer`,
  `Cross-Origin-Opener-Policy: same-origin`, `X-Frame-Options: SAMEORIGIN` (C51).
- SRI integrity on dist assets (`crossorigin="anonymous" integrity="sha384-..."`) via
  `scripts/add-sri-to-dist.js` build step (C65).
- `freezePrototype: true` — blocks prototype pollution XSS (C22).

**IPC + Isolation:**
- Isolation Pattern active with explicit allowlist including drift detection CI
  test — if any new `#[tauri::command]` is registered without updating
  `isolation-frame/isolation.js`, CI fails (C02).
- `tauri-plugin-store` + `tauri-plugin-notification` **removed entirely**
  (Sprint 0.18 B9 — not just capability filter): plugin `.init()` calls removed
  from `run()` + `[dependencies]` entries removed from `Cargo.toml`. Red team
  automated red team va detectar que la versió v0.1.1-security afirmava "removed" però
  només havia netejat capabilities; els plugins seguien inicialitzats. Binary
  size ~-600KB est., IPC surface -2 plugin command sets. Remaining capabilities:
  `core:default`, `dialog:default`, `deep-link:*` (specific subset) (C13 + B9).
- `fetch_from_sidecar` URL validation parses structurally via `url::Url::parse`
  (Rust) + `new URL(...)` (JS) — rebutja userinfo hijack, hostname `localhost`,
  IPv6 mapped, wrong scheme, missing port (Sprint 0.18 B2 — red team consens
  2/2 IAs del bypass `starts_with("http://127.0.0.1:")` acceptant 4 PoC vectors).
- `withGlobalTauri: false` (no global `window.__TAURI__`).

**Plugin system:**
- `plugin://` URI scheme with `canonicalize` + per-plugin scope + size cap.
- Integrity SHA-256 with **atomic snapshot verify+load** (B5 Sprint 0.18 security):
  `verify_and_load_plugin_asset` opens **all plugin file descriptors BEFORE any
  read**, reads all content from the held fds (Unix: inode pinned against
  rename/unlink/write externs; Windows: `File::open` denies exclusive writers),
  hashes from in-memory snapshot, verifies against manifest, and returns the
  requested file's bytes **from the same snapshot**. Bytes served are, by
  invariant, the bytes that produced the matching hash. Red team PoC
  against v0.1.1 (separate verify + read) showed **70.5% TOCTOU exploitation**
  rate; v0.1.2 test `b5_verify_and_load_atomic_snapshot_no_bypass` confirms 0%
  under spin-write attacker (release-only, 500 requests).
- Previous algorithm (C01 v0.1.1: re-hash per request via separate `verify` +
  `File::open + read_to_end`) retained only for `HEAD` requests which need no
  body I/O. GET path uses atomic snapshot exclusively.
- Per-file cap `MAX_HASH_FILE_BYTES = 10 MB` + total cap `MAX_HASH_TOTAL_BYTES = 50 MB`
  prevent OOM via sparse/malicious plugin layouts (B6 Sprint 0.18). Test
  `b6_hash_per_file_cap_enforced`.
- Bundle resources glob allowlist prevents accidental `.DS_Store`/`.env`/`.git/`
  in DMG (C17).

**Queue + runtime:**
- Pre-queue bound via **atomic CAS counter** (B3 Sprint 0.18): `PENDING_COUNT:
  AtomicUsize` + `fetch_add(1, AcqRel)` before enqueue; if current `>= MAX_QUEUED`,
  `fetch_sub(1)` + 503. RAII `PendingGuard` decrements on Drop. Red team
  showed that v0.1.1 `queued_count() + execute()` non-atomic pattern allowed
  `peak > MAX_QUEUED` under contention; v0.1.2 test `b3_queue_bound_atomic_race`
  confirms strict bound under N=MAX_QUEUED+100 concurrent threads.
- Rate limiting per-plugin 1000 req/s token bucket; burst-resistant.
- `graceful_quit` atomic guard (B1+T1 Sprint 0.18): extracted
  `graceful_quit_try_acquire() -> bool` helper; multiple trigger sources (X /
  Alt+F4 / tray Quit / quit_app command) converge on single dialog. Test
  `t1_dialog_guard_only_one_acquires_under_concurrency` (256 threads + Barrier)
  asserts exactly 1 acquire — mutation-verified against helper pre-fix.
- `tauri::async_runtime::spawn_blocking` for dialog (no runtime starvation) (C40).
- Panic hook writes crash reports to `app_data_dir()/crashes/` mode 0600 Unix
  (not `/tmp/` world-readable); backtrace truncated at 10KB, message sanitized
  against control chars + capped at 1024 chars (C29, C63, B30 Sprint 0.18).
- `err_response` includes defensive headers (Z3 Sprint 0.18): CSP `default-src
  'none'`, X-Content-Type-Options nosniff, Cache-Control no-store,
  Permissions-Policy, Referrer-Policy, X-Frame-Options DENY. Error paths are not
  fingerprinting oracles.

**Auth + secrets:**
- `fetch_from_sidecar` skeleton command injects Bearer token at Rust boundary — main
  webview never sees raw token (C25). `get_auth_token` legacy deprecated with
  `tracing::warn!`.
- Auth token UUID v4 per session (no persistence).

**Observability:**
- Unified logger pipeline: `tracing-subscriber` + `tracing-appender` (daily
  rolling). Single global logger by construction — no `SetLoggerError` class
  of bug. Release builds persist structured logs cross-platform to:
    - macOS: `~/Library/Application Support/com.nexe.app/logs/`
    - Linux: `~/.local/share/com.nexe.app/logs/`
    - Windows: `%LOCALAPPDATA%\com.nexe.app\logs\`
  (ADR-0017). Windows GUI release (`windows_subsystem="windows"`) has no
  stdout; the file layer delivers support visibility there. Bug #2 Fase 0
  real-closed — runtime-verified on macOS. **Correction note:** the previous
  `C15` claim in this section (`tauri-plugin-log active with tracing feature`)
  was empirically false and is retracted in `CHANGELOG.md [0.1.2-hotfix-runtime]`;
  `tauri-plugin-log` is no longer a dependency.
- Control-char sanitization + path truncation 200 chars (log DoS prevention) (C64).

**Supply chain:**
- `cargo audit` blocking CI gate + `.cargo/audit.toml` with `review-date` per CVE
  ignore — `scripts/check-audit-dates.sh` fails CI on expired dates (C18).
- `informational_warnings = []` — forces explicit documentation of each exception
  (no global silencing) (C66).
- `pnpm audit --prod` blocker + `pnpm audit` warning-only (dev deps separated) (C31).
- `pnpm-workspace.yaml` ignoredOptionalDependencies `@rolldown/binding-*` — avoids
  500MB prerelease downloads per CI run (C20).
- Rust toolchain pinned exact (`rust-toolchain.toml channel = "1.94.1"`) for
  reproducibility L3 (ADR-0015, C59).
- Cargo duplicate deps threshold enforced via `scripts/verify.sh` + documented
  in `docs/supply-chain/duplicate-deps.md` (C37).

**Release pipeline:**
- `draft: true` + `SHA256SUMS` generated before upload — no automatic public
  release without maintainer review (C03).
- Release permissions least privilege: `contents: read` workflow, `contents: write`
  only on release job (C09).
- Quality gate (cargo test + clippy + audit + pnpm test) required dependency for
  release job — no tag publishes without green checks (C08).
- `actions/checkout persist-credentials: false` everywhere — GITHUB_TOKEN not
  dropped in `.git/config` workspace (C24).
- Matrix covers macOS x64 + macOS arm64 + macOS Universal + Linux x64 + Linux
  ARM64 + Windows x64 + Windows ARM64 (C23, C47, C48).
- `concurrency.cancel-in-progress: true` prevents double-tag race (C32).
- SBOM dual format CycloneDX + SPDX (C33).
- Weekly bundle smoke test (full `tauri build` with bundle) (C45).

**Starter hygiene:**
- `rename.sh` enriched with author/email/repo/homepage prompts + logo placeholder
  replacement + spike removal option (C39).
- UI default minimal (no "Welcome to Tauri" + branding) — clones don't inherit
  framework branding (C46).
- `authors = ["Jordi Goy..."]` + `publish = false` + repository/homepage metadata
  (C21).
- Window config `minWidth/minHeight/center` prevents UI breakage (C50).

**Code quality:**
- `rustfmt.toml`: `max_width=100`, `imports_granularity=Crate`, `group_imports`.
- `cargo clippy --locked -- -D warnings` blocking gate on lib + bins.
- `cargo clippy --all-targets` warning-only (test code debt tracked).
- MSRV 1.88 CI job (`msrv-check` workflow in `check.yml`, Sprint 0.18 B29) —
  fails if code uses Rust 1.89+ features without bumping declared MSRV.

**Testing discipline:**
- **Mutation testing obligatory for all regression tests:** each test MUST fail
  when the specific line(s) of the fix are reverted (manually verified with a
  `/tmp/` copy of the repo). Tests that pass both pre-fix and post-fix are
  considered "theater" and either rewritten or removed.
- **Test helpers extracted from `#[tauri::command]` bodies** for testability
  without replicating logic in tests (T1 `graceful_quit_try_acquire`, T4
  `emit_deprecation_warning_and_return_token`, T5 `validate_sidecar_method`).
- **Red team final F7 cross-IA gate pre-tag:** 2 independent Opus subagents
  attack the candidate tag; if any P0/P1 bypass found, no tag. v0.1.2 passed.

Audit it before using it as a production base. Apply signing/notarization
(macOS) and code-signing (Windows) yourself.

## App Sandbox decision (F027)

**`com.apple.security.app-sandbox` is intentionally absent.**

The Python sidecar (server-nexe) requires filesystem access and localhost networking that is incompatible with macOS App Sandbox restrictions. Sandboxing the shell while the sidecar runs outside would create a false sense of security.

**Mitigations in place:**
- `canonicalize` + path traversal checks on all plugin:// requests
- CSP + postMessage isolation pattern
- Rate limiting (token bucket, burst-resistant)
- Sidecar auth token (planned Sprint S10)
- Process tree lifecycle management (planned Sprint S12)

This decision is subject to review at Fase 5 (hardening before v1 release).

## Supply chain (F056)

This template has a substantial dependency tree:

| Layer | Count | Notes |
|---|---|---|
| Rust crates | ~495 | Audited by `cargo audit` (blocking CI gate) |
| npm packages | ~90 | `pnpm audit` in CI (dev deps included) |
| build.rs scripts | Multiple | Execute at build time — Tauri, sha2, other crates |

**Current mitigations:**
- `cargo audit` with explicit ignores and justifications (`src-tauri/.cargo/audit.toml`)
- Cargo.lock committed (reproducible builds)
- `pnpm-lock.yaml` committed
- `cargo build --locked` enforced in CI

**Planned (roadmap):**
- SBOM generation (Sprint S11a — `cargo cyclonedx`)
- Reproducible builds with SOURCE_DATE_EPOCH (`./scripts/reproducible-build.sh`)
- Ed25519 plugin signatures (Sprint S17)
- SLSA provenance attestation (Fase 5)
