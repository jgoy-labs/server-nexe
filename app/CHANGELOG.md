# Changelog

All notable changes to nexe-app are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [0.1.2-hotfix-runtime] — 2026-04-22

### 🔧 Runtime hotfix — bug #2 Fase 0 real-closed + honest retraction of C15 claim

Branch: `hotfix/runtime-logger-unified` (local, unpushed, unmerged, untagged).
Commit base: `0c278c6` (`main` at time of fork).

#### Context

The `v0.1.2-fase0-militar-v2` tag (same commit `0c278c6`) was created at the
end of Sprint 0.18 and was **not pushed**. At 2026-04-22 12:30 the first human
`pnpm tauri dev` against that commit produced:

```
[nexe-app] fatal: failed to build app: failed to initialize plugin `log`:
    attempted to set a logger after the logging system was already initialized
```

The app did not boot. None of the 80 Rust release tests nor the 55 Vitest
tests caught this: they exercise units, not `tauri::Builder::default().run()`
boot. Red team subagent passes (F7) conducted without a GUI session could not
observe it either.

#### Honest retraction of C15

Sprint 0.18 finding C15 stated in `CHANGELOG.md [0.1.2-fase0-militar-v2]`,
`SECURITY.md §Observability`, and inline in `src-tauri/src/lib.rs`:

> "tracing_subscriber sense `tracing-log` feature NO crida `log::set_logger`
> — per tant coexisteix amb `tauri-plugin-log` (que crida `log::set_boxed_logger`)"

This claim was empirically false. `cargo tree` of the Sprint 0.18 commit
shows `tracing-log 0.2.0` present as a transitive dependency of
`tracing-subscriber 0.3.23` (default features enable it). The default
`tracing-subscriber` build **does** install a `LogTracer` global, which calls
`log::set_logger`. The subsequent `tauri-plugin-log::Builder::default().build()`
then calls `log::set_boxed_logger` → `SetLoggerError` → `Builder::run()` panic.

The C15 entry in the previous changelog section ("Supply chain / Misc — `tauri-plugin-log`
reactivated with `tracing` feature") is now superseded. The previous
`SECURITY.md` line `tauri-plugin-log active with tracing feature — release
builds persist structured logs to app_data_dir()/logs/ (C15). Bug #2 Fase 0
closed.` was also incorrect: the plugin prevented boot, so no logs were
persisted. This hotfix rewrites that entry.

#### Fix (ADR-0017)

Unified logging pipeline: `tracing-subscriber` + `tracing-appender`. No
`tauri-plugin-log`. See `docs/adr/ADR-0017-logging-pipeline.md` for the full
rationale.

- **Removed**
  - `tauri-plugin-log = { version = "2", features = ["tracing"] }` from
    `src-tauri/Cargo.toml`.
  - `.plugin(tauri_plugin_log::Builder::default()...)` block from
    `src-tauri/src/lib.rs run()` Builder chain.
  - The C15 comment blocks in both files.
- **Added**
  - `tracing-appender = "0.2"` in `src-tauri/Cargo.toml` (direct dependency).
  - `src-tauri/src/logging.rs`: new module owning `init()`, pure helper
    `resolve_log_dir_with(base: Option<PathBuf>)` for testability,
    best-effort `build_file_writer()` returning `Option<NonBlocking>` with
    stdout-only fallback, `static APPENDER_GUARD: OnceLock<WorkerGuard>`
    keeping the non-blocking worker alive for the process lifetime.
  - 3 OS-agnostic unit tests (`resolve_log_dir_ends_with_app_logs`,
    `resolve_log_dir_fallback_when_data_local_dir_missing`,
    `build_file_writer_returns_none_when_parent_is_a_file`).
- **Changed**
  - `src-tauri/src/lib.rs run()` now calls `crate::logging::init()` once at
    the top. The `tracing_subscriber::fmt().try_init()` inline block is
    removed.

#### Cross-platform behavior

| Platform | Log directory                                      |
|----------|----------------------------------------------------|
| macOS    | `~/Library/Application Support/com.nexe.app/logs/` |
| Linux    | `~/.local/share/com.nexe.app/logs/`                |
| Windows  | `%LOCALAPPDATA%\com.nexe.app\logs\`                |

Daily rotation: `nexe-app.log.YYYY-MM-DD`. On Windows GUI release
(`windows_subsystem="windows"`), stdout is not connected but the file layer
captures all events — this was the original support-visibility motivation for
C15, now delivered without the broken plugin.

#### Verification status (runtime gates)

- ✅ **macOS** (Jordi, 2026-04-22, Mac Studio M4 Max):
  1. `pnpm tauri dev` opens the window with no `failed to initialize plugin`
     error (previous bug resolved).
  2. `~/Library/Application Support/com.nexe.app/logs/nexe-app.log.2026-04-22`
     is created and contains `INFO nexe_app_lib::logging: nexe-app tracing
     initialized version="0.1.2" log_dir=...`, `INFO nexe_app_lib: auth token
     generated (uuid v4, 128 bits entropy)`, `INFO nexe_app_lib::lifecycle:
     graceful_quit invoked`, `quit confirmed — exiting`, `ExitRequested
     post-confirm — letting Tauri exit`.
  3. UX quit dialog behavior (X click / Cmd+Q / tray Quit 3× rapid) all converge
     on a single dialog per the B3+C14 atomic CAS from Sprint 0.18. No runtime
     regression from the logger refactor.
  4. `pnpm tauri build --debug` produces a working bundle
     (`src-tauri/target/debug/bundle/macos/nexe-app.app`); the bundled binary
     starts without panic and exits cleanly under `kill`.
- 🟡 **Windows ARM64 (UTM VM)** — runtime gates **deferred to a follow-up
  session**. The CI matrix (windows-latest) covers cargo build/test/clippy/audit
  on every push; GUI-level gates will be exercised separately.
- 🟡 **Linux (UTM Ubuntu 24.04 ARM64)** — runtime gates **deferred to a
  follow-up session**. CI matrix (ubuntu-latest) same as above.
- 🟢 **Automated:** `cargo test --release --locked` 83/83 passed (80 prior +
  3 new `logging::tests`); `cargo clippy --locked -- -D warnings` clean
  (matching CI invocation, not `--all-targets`); `cargo audit` 0 vulns; `pnpm
  audit` 0 vulns.

#### Findings observed during runtime verification — NOT touched in this hotfix

These are flagged here for future work. Each is out of scope for a single-purpose
logger fix; touching them would widen the blast radius and risk regressing
other Sprint 0.18 work.

1. **CSP script inline on `Greet` button.** Running `pnpm tauri dev` and clicking
   the `Greet` button produces `Refused to execute a script because its hash,
   its nonce, or 'unsafe-inline' does not appear in the script-src directive of
   the Content Security Policy. (localhost, line 228)`. This is a frontend
   concern (`index.html` / bundled JS) unrelated to the logger and present on
   `main @ 0c278c6` before this hotfix. Requires a separate CSP-scoped patch
   (nonce or hash for the inline script, or refactor the script to an external
   asset with SRI).
2. **Tauri bundle identifier warning.** `pnpm tauri build` emits
   `The bundle identifier "com.nexe.app" ... ends with '.app'. This is not
   recommended because it conflicts with the application bundle extension on
   macOS.` Changing the identifier would break the `data_local_dir()/com.nexe.app/logs/`
   path just introduced and invalidate the existing `v0.1.0-fase0` /
   `v0.1.1-fase0-militar` / `v0.1.2-fase0-militar-v2` tags. Out of scope.
3. **Pre-existing `unused imports` warning** in `src-tauri/src/lib.rs:30`
   (`verified_plugins`, `CacheEntry`, `VERIFIED_LRU_CAP`). Verified via `git
   stash` that this warning exists on `main @ 0c278c6` before this hotfix.
   Removing the imports requires analysing whether other `cfg(test)` paths
   rely on them; out of scope for a logger-focused change.
4. **`src-tauri/src/lib.rs` is 1668 lines.** Creating `logging.rs` is a
   minimal mitigation; a larger split (tray / Builder chain / tests) is
   deliberately deferred to a separate refactor task.
5. **Coverage not measured** for `logging.rs`: `cargo-tarpaulin` and
   `cargo-llvm-cov` are not installed on the build host. Installing new
   tooling is out of scope. Two of the three module-public helpers
   (`resolve_log_dir_with`, `build_file_writer`) are covered by the new unit
   tests; `init()` is intentionally not unit-testable (global subscriber
   state) and is covered only by the runtime gates above.
6. **Binary size delta** not measured (`cargo bloat` not installed).
   Expected to be a reduction given `tauri-plugin-log`'s `fern` + `colored`
   + related transitives are removed and `tracing-appender` adds only
   `crossbeam-channel` + `time`. Flagged as desirable follow-up measurement.

#### Tag status

The `v0.1.2-fase0-militar-v2` local tag still points at `0c278c6` (the broken
runtime commit). This hotfix **does not modify the tag**. The decision to
retag `v0.1.2-fase0-militar-v2` at the new HEAD or to bump to `v0.1.3` is
explicitly deferred to Jordi post-merge.

## [0.1.2-fase0-militar-v2] — 2026-04-22

### 🎖️ Post-RedTeam security — atomic integrity + real mutation-verified tests

Tag després de:
1. Red team multi-pass independent security audit sobre `v0.1.1-fase0-security`
   → veredicte **BROKEN** (1 P0 empíric, 2 P1, 9 P2, 16+ P3, 5 tests teatre confirmats).
2. Sprint 0.18 de correccions (6 fases F1-F6) amb mutation testing obligatori.
3. Red team final F7 pre-tag per validar sprint.
4. Hotfixes post-F7 (2 commits) aplicant tot el feedback red team final.

**Tests finals:** 69 Rust debug / **80 Rust release** / 55 Vitest / clippy clean
(`-D warnings`) / cargo audit 0 vulns / pnpm audit 0.

### Security — P0 resolt (1)

- **B5 — TOCTOU verify→serve double-read (P0 empíric):** red team Claude-ext va
  demostrar amb PoC que el handler feia dues lectures separades del FS (verify +
  read_to_end). Un atacant local amb spin-write entre les dues lectures
  aconseguia que **70.5% dels requests retornessin bytes no verificats** post-hash-OK.
  Això trencava el claim central d'ADR-0014 "tamper-evident delivery even under
  local in-place attacks".

  **Fix (atomic snapshot via open fd):** nova funció `verify_and_load_plugin_asset`
  a `src-tauri/src/integrity.rs` fa walk → **open all fds BEFORE any read** → read
  all from pinned fds → hash from in-memory snapshot → verify → return requested
  file's bytes **from the same snapshot**. Unix garanteix que fds oberts pinnen
  la inode contra rename/unlink/write externs; Windows `File::open` per defecte
  denega exclusive writers. Invariant: bytes servits == bytes hashats, by
  construction.

  **Mutation test verified:** `b5_verify_and_load_atomic_snapshot_no_bypass`
  (release-only) executa spin-write attacker + 500 requests; 0 bypasses amb el
  fix. Pre-fix reintroduït (pattern verify+read separat amb ~100µs sleep):
  **~67-72 bypasses de 500 (13-14% hit-rate reproduït independentment per
  F7-RT1 i red team extern Claude-ext2 — variabilitat ±2% segons scheduler)**.
  Test regressió pre-fix fallava consistentment; post-fix 0/500.

  ADR-0014 actualitzat a v3 documentant el TOCTOU verify→serve gap + el nou
  algoritme snapshot atòmic.

### Security — P1 resolts (2)

- **B1 — Drift regex bypass (P1, consens 2/2 IAs):** el test
  `allowlist covers all registered handler commands` usava `.match()` sense flag
  `/g`. Un atacant amb commit access podia afegir:
  ```rust
  // legacy: generate_handler![greet]    ← decoy comentari
  .invoke_handler(tauri::generate_handler![evil_cmd, greet, ...])
  ```
  i el test capturava només el decoy, amagant `evil_cmd` registrat sense validator
  isolation.

  **Fix:** strip de comentaris `//` i `/* */` abans del regex + `matchAll(/g)` per
  capturar totes les ocurrències + `expect(matches.length).toBe(1)`.
  **Mutation verified:** decoy + `evil_cmd` a còpia temporal → test FAIL com
  s'esperava.

- **B8 — `release.yml quality-gate ⊂ check.yml` (P1):** el job `quality-gate`
  executava només 4 checks; `check.yml` n'executava 10+. Un tag push directe
  podia publicar amb format errors, clippy warnings, CVEs pnpm prod, vite/tauri
  build trencat.

  **Fix:** `quality-gate` ara és **superset** de `check.yml` (10+ passos: fmt,
  test, clippy, audit, pnpm install/test/audit--prod/build, tauri build
  --no-bundle). `release` job depèn explícitament de `[build, sbom, quality-gate]`.
  Cap tag publica sense checks verds complets.

### Security — P2 resolts (9)

- **B2 — `fetch_from_sidecar` URL whitelist strict (P1 latent Fase 2):** 4 vectors
  userinfo-hijack (`http://127.0.0.1:8000@evil.example.com/exfil`) passaven
  `starts_with("http://127.0.0.1:")`. Fix: `url::Url::parse` amb checks scheme +
  host + userinfo + port a **Rust i JS** (doble barrera). Mutation verified: 8/9
  tests FAIL amb pattern pre-fix.

- **B3 — Queue bound race check-then-act (P2):** `queued_count() + execute()` no
  atòmic permetia que N threads veiessin `count < MAX_QUEUED` simultaniament i
  enqueegessin tots. Fix: `PENDING_COUNT: AtomicUsize` amb `fetch_add(1, AcqRel)`
  + RAII `PendingGuard` Drop decrementa. Mutation verified: pattern antic →
  `peak=257 > MAX_QUEUED=256` fa fallar el test.

- **B6 — `compute_plugin_hash` unbounded memory (P2):** plugin amb fitxer de 100GB
  o manifest gegant podia OOM. Fix: `MAX_HASH_FILE_BYTES = 10 MB` per fitxer +
  `MAX_HASH_TOTAL_BYTES = 50 MB` combinat. 413 si excedeix. Test
  `b6_hash_per_file_cap_enforced`.

- **B9 — `tauri_plugin_store` + `tauri_plugin_notification` realment eliminats
  (P2):** v0.1.1 claim "removed" era parcial (només capabilities). Ara plugins
  removed de `lib.rs .plugin()` + `Cargo.toml [dependencies]`. Binary -~600KB,
  IPC surface -2 plugin command sets. SECURITY.md + CHANGELOG actualitzats amb
  la realitat.

- **B10 — ADR-0014 v3 acknowledge verify→serve gap:** document actualitzat amb
  descripció precisa del gap previ (verify separat + read separat) + nou
  algoritme atomic snapshot + fd-pinning rationale (Unix + Windows).

- **B11 — CSP `*.localhost` wildcard retallat (P2):** `frame-src` ara usa hosts
  específics (`tauri.localhost`, `ipc.localhost`, `isolation-*.localhost` per
  Windows) en lloc del wildcard genèric `*.localhost`.

- **B12 — `dialog:default` retallat a `dialog:allow-message` (P2):** el codi
  només usa `.message()` (graceful_quit). `open`/`save` file pickers no
  necessaris, eliminats del capabilities default.

- **B4 — SHA256SUMS step bloquejant (P2):** `release.yml` afegeix `test -s
  SHA256SUMS` + `wc -l >= 7 artifacts`. Cap release amb SUMS buit o parcial.

- **Z3 — `err_response` headers defensius (P2):** responses 400/403/404/429/503
  ara inclouen Content-Type, X-Content-Type-Options, Cache-Control, CSP
  `default-src 'none'`, Permissions-Policy, Referrer-Policy, X-Frame-Options DENY.
  Error paths ja no són oracle de fingerprinting.

### Tests teatre reescrits (5)

Red team cross-IA va identificar 5 tests que passaven tant amb codi pre-fix com
post-fix (exercien stdlib o replicaven lògica al test). Reescrits per
mutation-verified:

- **T1 `dialog_showing_guard_semantics`:** exercia `AtomicBool::swap` stdlib, no
  `graceful_quit`. Reescrit → `t1_dialog_guard_only_one_acquires_under_concurrency`:
  extreu helper `graceful_quit_try_acquire`, test amb 256 threads + Barrier
  verifica **exactament 1 acquire**. Mutation verified: guard removed → 256
  acquire instead of 1.
- **T2 + T2bis `max_queued_constant_sanity` + `handler_pool_queue_count_accessible`:**
  tautologies (`usize < usize::MAX`). Eliminats — subsumits per
  `b3_queue_bound_atomic_race` (F4a) que exerceix el pattern real.
- **T4 `get_auth_token_emits_deprecation_warning`:** el test feia `fetch_add(1)`
  ell mateix. Reescrit → `t4_emit_deprecation_increments_counter_via_real_helper`:
  extreu helper `emit_deprecation_warning_and_return_token`, test invoca helper
  real. Mutation verified: `fetch_add` removed → counter unchanged → FAIL.
- **T5 `fetch_from_sidecar_rejects_external_url` + `_method_allowlist`:** el test
  definia `validate_url` local. Eliminats — subsumits per `validate_sidecar_url_*`
  (F3 B2). Nou `t5_method_allowlist_*` (3 tests) extreu helper
  `validate_sidecar_method` + 12 vectors reals (TRACE/CONNECT/PATCH/case/CRLF).

### Polish P3 (16+ findings B7 + B15-B30)

- **B7:** `scripts/rename.sh` afegeix helper `escape_for_sed_rhs()` per input
  user (nom/email/URL). Protegeix `|`, `&`, `\`, `/`.
- **B13:** version drift resolt — `Cargo.toml`, `tauri.conf.json`, `package.json`
  tots `"0.1.2"`. SBOM amb versió correcta.
- **B14:** ADR filenames sense sufixos enganyós — `ADR-0013-isolation-pattern.md`
  (era `-deferred`) + `ADR-0014-plugin-integrity.md` (era `-stub`) + cross-refs
  actualitzades a `README.md`, `SECURITY.md`, `TEMPLATE.md`, `docs/adr/README.md`.
- **B15-B17:** docs drift — CHANGELOG "14 fitxers Vitest" → "2 fitxers 55 tests",
  TEMPLATE counts reals post-v0.1.2.
- **B18:** `pnpm-workspace.yaml` afegeix `@rolldown/binding-linux-ppc64-gnu` a
  `ignoredOptionalDependencies` (cobreix nova plataforma rc.16).
- **B19:** `scripts/add-sri-to-dist.js` `stripExistingCrossorigin()` abans
  d'afegir nou `crossorigin="anonymous"` — `dist/index.html` sense duplicats.
- **B20:** `scripts/check-audit-dates.sh` documenta limitació coarse-bucket
  (tots 19 CVE comparteixen `2026-10-01`) + pattern stagger per Sprint 0.19.
- **B21:** `sign-macos.sh` rebutja `TAURI_APPLE_PASSWORD` literal (exit 1 amb
  guidance). Només accepta `@keychain:<ref>`.
- **B22:** `reproducible-build.sh` fa `cargo clean` per defecte + flag
  `--no-clean` amb WARNING prominent (prevenció "pseudo-reproducible via cache").
- **B23:** comentari al `rename.sh` sobre `dist/` gitignored (no cal
  actualitzar-lo post-rename).
- **B24:** `isolation-frame/index.html` afegeix CSP meta (`default-src 'self';
  script-src 'self'`) com a defensa in-depth — Tauri ja aplica CSP runtime,
  aquest és fallback.
- **B25:** comentari documentant per què isolation.js no usa SRI (servit via
  bundle, no xarxa).
- **B27:** `release.yml` SBOM comentari cdxgen npm TODO expandit amb rationale
  + link a cdxgen docs.
- **B28:** `src-tauri/src/main.rs` comentari sobre `panic = "abort"` + RAII
  Drop semantics (guards no executen Drop en abort; workers aïllats).
- **B29:** `check.yml` nou job `msrv-check` amb `dtolnay/rust-toolchain@1.88.0`
  — falla si el codi usa features 1.89+ sense bump MSRV.
- **B30:** panic hook sanitize control chars del missatge + cap a 1024 chars
  (previene ANSI injection a logs stderr redirigits).

### Changed

- **`integrity.rs` refactoritzat:** `verify_and_load_plugin_asset` és el nou
  entry point runtime (GET `plugin://`). `verify_plugin_integrity` retingut per
  HEAD (no body I/O saved) i per al CLI `scripts/plugin-hash`. `compute_plugin_hash`
  retingut per al CLI build-time; el runtime usa `compute_hash_from_snapshot`
  que treballa amb bytes en memòria.
- **`handler.rs` pattern GET:** una sola crida a `verify_and_load_plugin_asset`
  en lloc de `verify_plugin_integrity` + `File::open + read_to_end`. Cap TOCTOU
  window.
- **`lifecycle.rs`:** extret `graceful_quit_try_acquire() -> bool` per tests
  sòlids. `graceful_quit` delega a aquest helper abans de spawn_blocking.
- **`auth.rs`:** extret `emit_deprecation_warning_and_return_token` +
  `validate_sidecar_method` per tests sòlids (no replica al test).

### Added

- **Nous tests regression** (tots mutation-verified):
  - `b5_verify_and_load_atomic_snapshot_no_bypass` (release, 500 requests spin-write)
  - `b6_hash_per_file_cap_enforced` (release)
  - `b3_queue_bound_atomic_race` (release, N threads + Barrier)
  - `err_response_has_security_headers` + `err_response_different_status_same_headers` + `err_response_preserves_body_bytes`
  - `t1_dialog_guard_only_one_acquires_under_concurrency` (256 threads)
  - `t4_emit_deprecation_increments_counter_via_real_helper`
  - `t5_method_allowlist_accepts_safe_methods_via_real_helper` + `_rejects_non_safe_methods_via_real_helper` (12 vectors) + `_rejects_body_on_get_via_real_helper`
  - Vitest: `allowlist covers all registered handler commands (drift check — comment-immune)` + B1 mutation vector inline
  - Vitest: 6 tests `fetch_from_sidecar` JS mirroring el Rust
- **Nou CI job** `msrv-check` a `check.yml` (Rust 1.88.0).
- **Dep afegida:** `url = "2"` (strict URL parsing per `fetch_from_sidecar`).

### Post-F7 hotfixes (2 commits aplicant feedback red team final)

**F7-RT2 hotfix (`c6a1301`):**
- **B18 P0 CI-breaker**: `pnpm-workspace.yaml` havia afegit
  `@rolldown/binding-linux-ppc64-gnu` a `ignoredOptionalDependencies` però
  `pnpm-lock.yaml` no va ser regenerat. Resultat empíric: `pnpm install
  --frozen-lockfile` fallava amb `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` tant a
  `check.yml` com a `release.yml` quality-gate. Fix: `pnpm install
  --no-frozen-lockfile` + commit lock regenerat.

  **Nota post-red-team-extern (scope commit message c6a1301)**: el missatge del
  commit va dir "una línia nova" al lock; el diff real és ~13 línies en 4
  seccions (`packages`, `ignoredOptionalDependencies`, `snapshots`,
  `optionalDependencies` dins `rolldown`), tot coherent mecànicament amb
  l'acció de pnpm quan es mou una dep a ignored. No és supply chain attack;
  simplement el commit message subestimava l'abast observable.
- **B8 claim accuracy**: afegit step `pnpm audit --audit-level=moderate`
  (warning-only) al quality-gate per paritat real amb `check.yml`. Comentari
  actualitzat a "superset blocking-equivalent" (matrix multi-OS intencionalment
  no duplicada per evitar cost CI doble).
- **B20 CI integration**: script `scripts/check-audit-dates.sh` ara invocat
  com a step a `check.yml` (abans només via `verify.sh` manual). La claim
  SECURITY.md "CI bloqueja si data passada" és ara real.
- **tag_name dead input**: `workflow_dispatch.inputs.tag_name` (mai
  referenciat) eliminat de `release.yml`.

**F7-RT1 hotfix (`2aef816`) — test quality reforçat:**
- **B3 test teatre eliminat**: el test `b3_queue_bound_atomic_race` replicava
  el pattern CAS al propi closure dels threads — no fallava si algú revertia
  el codi de producció. Fix patró F5 (extract-helper):
  - Nou `pub(crate) fn try_acquire_pending_slot() -> Option<PendingGuard>` al
    mòdul `lib` — única ruta al codi productiu per adquirir un slot de cua.
  - Nou `pub(crate) struct PendingGuard` amb constructor privat (`_marker: ()`)
    — només `try_acquire_pending_slot` pot instanciar. Drop decrementa counter.
  - `register_asynchronous_uri_scheme_protocol` crida el helper en lloc de
    replicar el pattern CAS inline.
  - Test actualitzat: N threads criden el helper REAL + Barrier + assert
    peak PENDING_COUNT <= MAX_QUEUED.
  - **Mutation verificat empíricament**: helper defectuós (mai retorna None)
    → test FAIL amb `CAS acotament violat: PENDING_COUNT peak=356 > MAX_QUEUED=256`.
- **B6 total cap test gap**: `MAX_HASH_TOTAL_BYTES` (50MB) estava implementat
  al codi però sense regression test. Nou test
  `b6_hash_total_cap_enforced`: plugin amb 6 fitxers × 9MB (54MB total, cada
  fitxer sota 10MB per-file) → `Err(413)` esperat.
- **T1 docstring accuracy**: el docstring afirmava que catching load+store
  race mutations; F7-RT1 verificat empíricament 10/10 passades a macOS M4 + 256
  threads + Barrier → NO caça load+store. Docstring actualitzat per precisió:
  catches "always-true" mutations (verified), NO catches load+store races
  (loom/model-checker needed — Sprint 0.19+).

### Credit

- **Red team cross-IA 2026-04-21 (consultoria externa):** Claude Opus 4.7 1M
  extern (30 bypasses + 5 tests teatre), external audit (4 bypasses + 2 tests
  teatre).
- **Red team final 2026-04-22 (F7):** 2 subagents Opus independents (RT1
  crític — 0 bypasses codi + 1 P2 test teatre B3 + 2 minor; RT2 supply/drift/CI
  — 1 P0 CI-breaker B18 + 3 minor). Hotfixes post-F7 van tancar tots els
  residuals abans del tag.
- **Sprint 0.18 Dev sessions:** 1 Director+Dev Opus 4.7 1M (B5 refactor) + 6
  subagents Claude 4.6 coordinats amb mutation testing obligatori i auditor
  independent.

## [0.1.1-fase0-militar] — 2026-04-21

## [0.1.1-fase0-security] — 2026-04-21

### 🎖️ Security hardening baseline

Tag després d'auditoria de seguretat multi-pass independent i aplicació del
consolidat 2026-04-21 amb 6 worktrees paral·leles. Objectiu: base clonable
amb garanties de seguretat sòlides per a múltiples apps Tauri futures.

**Tests finals:** 58 Rust debug / 65 Rust release / 55 Vitest (2 fitxers) / clippy
clean (`-D warnings`) / cargo audit 0 vulns actives / pnpm audit 0.

### Security — Findings P0 resolts (5/5)

- **C01 — TOCTOU mtime integrity cache bypass:** `CacheEntry { known_hash }` re-computa
  hash a cada request (cost ~10ms per plugin petit, acceptable). Edit
  in-place d'un fitxer existent detectat empíricament (APFS test regressió).
  ADR-0014 v2 actualitzat.
- **C02 — Isolation allowlist incomplet:** `quit_app` + `get_auth_token` afegits
  al `isolation-frame/isolation.js` amb validators. Drift check test parseja
  `generate_handler![]` i falla CI si algú afegeix un `#[tauri::command]` sense
  actualitzar l'allowlist.
- **C03 — Release pipeline unsigned + xattr bypass:** `draft: true` al release step
  (publicat manualment), `SHA256SUMS` generat abans del release, body substitueix
  instrucció `xattr -dr com.apple.quarantine` per warning "unsigned — not for
  production".
- **C04 — Closeout MDs privats committed:** `git filter-repo` purga els 3 fitxers
  `20260418_closeout_codex*.md` del history sencer. `.gitignore` blindat amb
  patterns `20*_closeout_*.md`, `20*_auditoria_*.md`, `DIARI-*.md`, `diari/`.
- **C05 — iframe registry race (Gemini únic):** DESCARTAT després d'investigació
  empírica. No reproduït com a vector explotable. Rebaixat a P2
  "defense in depth hardening". Documentació a
  `docs/security/iframe-race-investigation-20260421.md` amb 4 hypothesis H1-H4.

### Security — Findings P1 resolts (19/21)

- **C06 — DoS cua plugin:// pre-queue:** validació + rate-limit + bounded queue
  (503 si > 256 queued). Cua no creix indefinidament sota flood.
- **C07 — Drift dev↔publication mirror:** internal dev paths + codi executable
  eliminats; només docs mantinguts.
- **C08 — Release sense quality gate:** job `quality-gate` (cargo test + clippy +
  audit + pnpm test) és dependency del job `release`.
- **C09 — Release contents: write global:** workflow `permissions: contents: read`;
  `contents: write` només al job `release`.
- **C10 — allow-top-navigation iframe:** eliminat del `src/index.html:54` (W6 UI
  minimal aprofitant).
- **C11 — CSP unsafe-inline styles:** eliminat (Vite no genera inline CSS).
- **C12 — CSP directives modernes:** `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`, `frame-ancestors 'none'` afegits.
- **C13 — core:default sobre-autoritzat:** `store:default` + `notification:default`
  eliminats del capabilities (dead permissions).
- **C14 — graceful_quit guard concurrent:** `DIALOG_SHOWING: AtomicBool` amb
  `compare_exchange` → triple-click tray Quit mostra 1 sol dialog.
- **C15 — tauri-plugin-log disabled:** reactivat amb feature `tracing` — bug #2
  Fase 0 tancat. Release logs persistits a `app_data_dir()/logs/`.
- **C16 — ADR-0014 drift doc/codi:** actualitzat amb `LruCache<String, CacheEntry
  { known_hash }>` real.
- **C17 — bundle.resources no allowlist:** glob explícit `.html/.css/.js/.toml`
  per plugins-dev/, prevé `.DS_Store`/`.env`/`.git/` accidentals al DMG.
- **C18 — audit.toml sense expiració automàtica:** `review-date` per cada ignore
  + `scripts/check-audit-dates.sh` CI bloqueja si data passada.
- **C19 — Info leak internal identifiers + paths personals:** `docs/adr/ADR-0016`
  + altres docs netejats; zero mencions de paths o identificadors interns.
- **C20 — rolldown rc.15:** `pnpm-workspace.yaml` amb
  `ignoredOptionalDependencies` — 51 binaris prerelease → 0 descàrregues CI.
  Estalvi ~500MB per CI run.
- **C21 — Cargo.toml "The Authors":** `authors = ["Jordi Goy..."]`, `publish = false`,
  `repository`, `homepage`, `keywords`, `categories`.
- **C22 — freezePrototype absent:** `app.security.freezePrototype: true` — bloqueja
  prototype pollution XSS.
- **C23 — Windows ARM64 (validat) no publicat:** matrix ampliada amb
  `aarch64-pc-windows-msvc`.
- **C24 — actions/checkout sense persist-credentials: false:** aplicat a tots els
  workflows. Tokens ja no queden a `.git/config` del workspace.
- **C25 — Auth token exposure main doc:** `fetch_from_sidecar` skeleton (intercepta
  sidecar calls + injecta Bearer al Rust side). `get_auth_token` emet deprecation
  warning via `tracing::warn!`. Main webview ja no ha de tocar token raw a Fase 2.
- **C26 — No E2E Windows automatitzat:** DIFERIT a Sprint 0.18 (nou worktree W7
  pendent).

### Security — Findings P2/P3 resolts (22 de 44)

CI/supply: C31 (pnpm audit separat), C32 (cancel-in-progress), C33 (SBOM SPDX +
CycloneDX dual), C37 (duplicate deps report), C45 (weekly bundle smoke), C47
(macOS Universal), C48 (Linux ARM64), C66 (informational_warnings empty), C70
(clippy all-targets warning-only).

Runtime: C28 (timing oracle 2ms → 50ms), C29 (panic hook `app_data_dir` mode 0600),
C30 (rate limiter alloc-per-request resolt), C40 (spawn_blocking), C41 (checked_sub
Duration), C42 (tauri-plugin-log dep ara usada), C51 (Permissions-Policy,
Referrer-Policy, COOP, X-Frame-Options headers), C52 (HEAD fast path), C63
(backtrace truncat 10KB), C64 (log path truncat 200 chars).

UI/DX: C39 (rename.sh enriquit), C46 (UI default minimal), C50 (window config
minWidth/center), C55-C58-C60-C61-C62-C65-C68-C71-C72 (polish).

Privacy: C56 (README ADRs 16), C19 (+ C69 parcial).

### Changed

- **Crash reports:** ja no a `/tmp/` (world-readable), sinó a `app_data_dir/crashes/`
  amb mode 0600 Unix. Backtrace truncat a 10KB per prevenir DoS.
- **Rate limiter:** lookup-then-insert pattern (cap `String` allocat per request
  cache hit).
- **HEAD requests:** fast path sense llegir body (I/O saving).
- **ADR-0013:** "deferred" → "active" + documenta quit_app + get_auth_token +
  fetch_from_sidecar.
- **rustfmt.toml:** `max_width = 100`, `imports_granularity = "Crate"`,
  `group_imports = "StdExternalCrate"`.
- **Rust toolchain:** pin exacte `1.94.1` (ADR-0015 L3 reproducibility).

### Added

- `scripts/add-sri-to-dist.js` — post-build SRI sha384 per assets (dist/index.html
  amb `integrity="..."`).
- `scripts/check-audit-dates.sh` — CI helper que falla si review-date CVE passada.
- `scripts/verify.sh` — sync amb CI + duplicate deps threshold check.
- `docs/security/iframe-race-investigation-20260421.md` — investigació C05.
- `docs/supply-chain/duplicate-deps.md` — snapshot duplicats + roadmap bumps.
- `.github/workflows/weekly-bundle-smoke.yml` — tauri build full bundle weekly.
- `.eslintrc.json` + `.prettierrc` — ara coherents amb `.vscode/extensions.json`.
- `src/assets/app-logo.svg` — placeholder "YOUR LOGO HERE".
- `SOURCE_OF_TRUTH.md` a dev — prescripció source of truth.

### Deferred (explicitament per Sprint 0.18+)

- **C26 E2E tauri-driver:** harness GUI automàtic per lifecycle/tray/quit. ~6-8h.
- **C34 + C38 CI plugin hash check:** step verifica plugin hashes vs manifest.toml.
  ~2h.
- **C36 gen/schemas:** decisió committed vs generated. ~1h.
- **C43 is_ok() → assert_eq!** fragils tests. ~1h.
- **C44 CI smoke bundle** (parcialment resolt via weekly-bundle-smoke C45).
- **C49 bundle.targets explícit:** `["dmg", "appimage", "msi", "nsis"]` a
  tauri.conf.json. Trivial però requereix W1 re-open.
- **C53-C54 minor monotonic/reserved:** polish deferit.
- **C62 err_response Content-Type:** parcial via C51 headers; complet deferit.
- **C67 tag_name unused:** trivial, deferit.
- **Windows SSH VM validation:** full Mac + Linux SSH + Windows ARM64 physical
  runtime validació pre-public release.

### Consolidat

Per llistat complet de findings i veredictes, veure la documentació interna
del consolidat d'auditoria de seguretat.

### Credit

- **Independent security audit (2026-04-20):** 3 auditors independents,
  95 findings totals consolidats.
- **Correction sprint:** 6 fases amb worktree isolation — temps wall-clock
  total ~1h15min.

## [0.1.0-fase0] — 2026-04-19

### 🏆 Fase 0 end-to-end validada al Windows ARM64 real

Primer moment de la història del projecte on l'app s'ha validat GUI cross-platform
amb tests manuals humans al Windows real (UTM VM + SSH). 10 bugs runtime descoberts
i fixats que no sortien a cap CI o test unitari.

### Added
- 27 sprints del pla completats (S01-S15e + S11a, més merges)
- Validació completa Greet + isolation + CSP + lifecycle cross-platform
- Fluxe unificat de Quit: X, Alt+F4, tray Quit, quit_app command → mateix dialog "Quit nexe-app?"
- `EXIT_CONFIRMED` flag AtomicBool per trencar cicle viciós Tauri ExitRequested re-dispatch
- Auth token baseline (UUID v4) + api-contract v0.1 amb Bearer
- Refactor lib.rs en 6 mòduls cohesius (<300L cada un)
- 7 plugins Tauri baseline (single-instance, dialog, log, store, notification, deep-link, updater)
- Release pipeline skeleton (workflows/release.yml) amb matrix 4 OSs + SBOM
- Tests: 48 Rust debug / 57 Rust release (Windows) / 28 vitest / clippy clean

### Fixed (runtime GUI bugs, només detectables amb test real)
- `2def038` esbuild devDep missing (build fail Windows)
- `0096126` tauri-plugin-log vs tracing_subscriber conflict (crash silent)
- `092bcbc` CSP frame-src bloqueja isolation-*.localhost (crypto.importKey crash)
- `784ee6c` Dialog blocking_show deadlock + prevent_exit missing
- `ff00adc` Tauri 2 payload shape `args.payload.name`
- `6ddb5f1` Iframe load event (contentWindow canvia)
- `ac7fbe6` IPC shape filter (tot origin="null" a Tauri 2)
- `2430514` Tray Quit async task + blocking_show
- `71ebd86` Tray Quit dialog requireix finestra visible com parent
- `3d12d4e` EXIT_CONFIRMED flag — trenca cicle ExitRequested → dialog

### Security
- TOCTOU + cache-poisoning eliminats (S02)
- Thread-bomb DoS eliminat via threadpool bounded (S03)
- LRU caps a RATE_LIMITERS + VERIFIED_PLUGINS (no OOM)
- CSP estricta sense unsafe-inline al plugin response
- Object.create(null) isolation (no prototype pollution)
- Reserved names Windows bloquejats
- Entitlements hardened + SECURITY.md supply chain

### Known issues (documentades, NO blockers)
- Warning cosmètic "Navigation to external protocol blocked by sandbox" al Windows WebView2 (del iframe plugin://rag — tradeoff conegut)
- iframe rag contingut no es veu al Windows standalone (resource_dir path; a investigar Fase 1)
- cargo audit falla al Windows ARM64 (aws-lc-sys bug upstream, no regressió nostra)

### Added
- Sprint 0.5: `plugin_root_for(app)` dev/release split, path traversal protection, CSP, 9 unit tests, CI
- Sprint 0.6: Access-Control-Allow-Origin null, remove `opener:default`, Cache-Control, `validate_plugin_id`, tracing logs, extended MIME types
- Sprint 0.7: Vite 8, Vitest 4, `withGlobalTauri: false`, extended CI (cargo-audit + build + test)
- Sprint 0.8–0.15: Security hardening (SHA-256 plugin integrity, Isolation Pattern, SLSA baseline, rate limiting, timing oracle mitigation)

### Security
- Plugin integrity SHA-256 (ADR-0014 active)
- Isolation Pattern with postMessage firewall (ADR-0013 active)
- Rate limiting per-plugin (token bucket, burst-resistant) — Sprint S06 F023
- Timing oracle mitigation 2ms — Sprint S06 F022
- `dragDropEnabled: false` to prevent XSS via File.path — Sprint S06 F028
- `STRICT_INTEGRITY` dev/release split — Sprint S06 F024

---

## [0.1.0] — Unreleased (Fase 0 scaffold complete)

### Added
- Tauri v2 shell + system tray (Show/Hide/Quit)
- `plugin://` URI scheme handler (ADR-0009)
- 15 ADRs covering architecture decisions
- Apache-2.0 license
- GitHub Actions CI (check + audit + build + test)
- TEMPLATE.md for fork/reuse

### Notes
- Fase 0 scaffolding complete. Not yet production-ready (Fase 1+ required).
- 41 Rust tests + 13 Vitest tests passing.

[Unreleased]: https://github.com/jgoy-labs/nexe-app/compare/HEAD...HEAD
[0.1.0]: https://github.com/jgoy-labs/nexe-app/releases/tag/v0.1.0
