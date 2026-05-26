# ADR-0017: Unified logging pipeline — `tracing-subscriber` + `tracing-appender`

**Date:** 2026-04-22
**Status:** Accepted
**Decided by:** Jordi Goy

## Context

`nexe-app` has used `tracing::*` macros throughout the Rust codebase since Sprint
0.6. Configuration of the global subscriber has been via
`tracing_subscriber::fmt().try_init()` (stdout only, no file persistence).

Between Fase 0 (2026-04-19) and Sprint 0.18 (2026-04-22) the logger
configuration oscillated:

1. **Fase 0 (v0.1.0-fase0)** — `tauri-plugin-log` was added then removed (bug
   #2) because initializing it after `tracing_subscriber::fmt().try_init()`
   produced `SetLoggerError: attempted to set a logger after the logging system
   was already initialized`. The plugin was left commented out; release Windows
   (`windows_subsystem="windows"`) users had no log file since stdout is not
   connected.
2. **Sprint 0.18 (2026-04-22, v0.1.2-fase0-militar-v2 candidate)** — finding
   C15 theorized that `tracing-subscriber` without the `tracing-log` feature
   did not call `log::set_logger`, and that `tauri-plugin-log` could therefore
   coexist by reactivating it with the `tracing` feature. This claim was merged
   into `main`, tagged locally, and documented across `SECURITY.md`,
   `CHANGELOG.md`, and inline comments.
3. **Runtime verification (2026-04-22 12:30)** — the first human `pnpm tauri
   dev` after the Sprint 0.18 tag produced:
   ```
   [nexe-app] fatal: failed to build app: failed to initialize plugin `log`:
       attempted to set a logger after the logging system was already initialized
   ```
   The claim was empirically false. `cargo tree` confirms `tracing-subscriber
   0.3.23` has `tracing-log 0.2.0` as a direct (transitive-but-default)
   dependency: the default features of `tracing-subscriber` install a
   `LogTracer` global that bridges `log::*` events into `tracing`, and this
   install calls `log::set_logger`. `tauri-plugin-log` subsequently calls
   `log::set_boxed_logger`, producing the `SetLoggerError`.

None of the 80 Rust release tests nor the 55 Vitest tests caught this: they
exercise units and frontend logic, not `tauri::Builder::default().run()` boot.
Red team subagents (F7) produced no GUI session. The regression was only
observable by a human running the desktop app.

The bug invalidated a signed claim in the `v0.1.2-fase0-militar-v2` tag body.
The tag is local-only (unpushed) as of this ADR.

## Decision

**Use `tracing-subscriber` + `tracing-appender` as the single global logger
pipeline. Remove `tauri-plugin-log` from the dependency graph entirely.**

Concretely:

- `tauri-plugin-log` removed from `src-tauri/Cargo.toml [dependencies]` and
  from `src-tauri/src/lib.rs .plugin(...)` chain.
- `tracing-appender = "0.2"` added as a direct dependency.
- New module `src-tauri/src/logging.rs` owns the init sequence:
  - `resolve_log_dir()` → `dirs::data_local_dir()/com.nexe.app/logs` with a
    `./logs` fallback for environments where `data_local_dir` returns `None`
    (headless CI without `HOME`, unusual sandbox).
  - `build_file_writer()` → best-effort `std::fs::create_dir_all` + a daily
    rolling `tracing_appender::rolling::daily(log_dir, "nexe-app.log")` wrapped
    in a `non_blocking` writer. On failure (read-only FS, permission denied,
    parent-is-a-file, invalid path), returns `None` and the subscriber falls
    back to stdout-only without panic.
  - `init()` builds the `Registry` with three layers: `EnvFilter` (from
    `RUST_LOG` env, defaulting to `info`), `fmt::Layer` writing to
    `std::io::stdout`, and the optional file `fmt::Layer` (ANSI off). Uses
    `.try_init()` so a second invocation returns `Err` which is logged to
    `stderr` rather than panicking.
  - `APPENDER_GUARD: OnceLock<WorkerGuard>` at static scope keeps the
    non-blocking worker thread alive for the lifetime of the process so that
    pending writes are flushed before exit. `OnceLock::set` makes a redundant
    init idempotent (first-init wins).

The path resolves cross-platform via `dirs::data_local_dir()`:

| Platform | Resolved log directory                           |
|----------|--------------------------------------------------|
| macOS    | `~/Library/Application Support/com.nexe.app/logs/` |
| Linux    | `~/.local/share/com.nexe.app/logs/`              |
| Windows  | `%LOCALAPPDATA%\com.nexe.app\logs\`              |

Daily rolling produces files named `nexe-app.log.YYYY-MM-DD`.

Third-party crates that emit via `log::*` (Tauri internals,
`tauri-plugin-dialog`, `tauri-plugin-single-instance`, `tauri-plugin-deep-link`,
transitive deps) reach this subscriber automatically via the `LogTracer` that
`tracing-subscriber` installs by default (feature `tracing-log` is enabled by
the `tracing-subscriber` default feature set and is present in `Cargo.lock` as
a transitive dependency). No manual `LogTracer::init()` call is required.

## Alternatives rejected

| Option | Reason rejected |
|---|---|
| **A — Revert Sprint 0.18 C15, accept bug #2 as known deferred debt** | The original motivation for reactivating `tauri-plugin-log` (release Windows users have no log file) remains valid. Accepting the debt means shipping a product that is harder to support. `tracing-appender` solves the same problem without the global-logger conflict. |
| **B — Drop `tracing-subscriber::fmt().try_init()`, keep only `tauri-plugin-log`** | Would break every `tracing::info!/warn!/debug!` call in the Rust codebase (auth, handler, integrity, lifecycle, rate_limit, validate, logging, lib). Structured fields (`%log_dir.display()`, `version = env!(...)`) are not first-class in the `log` macros. |
| **C — Formal interop layer (`tauri-plugin-log` with `tracing` feature + custom `Layered`)** | Was the Sprint 0.18 C15 plan. Empirically broken (this ADR exists because of it). Even with theoretical fix, keeps two crates doing the job of one and preserves the risk of future regressions when either upstream changes its `set_logger` strategy. |
| **D — Replace `tracing-appender` with `logroller` or `tracing-appender-plus`** | Both offer richer rotation (size-based retention) but at the cost of less-maintained crate and larger dependency graphs. `tracing-appender` is the official subcrate of the `tracing` project. Retention can be added manually (cron, manual cleanup) or revisited when data volume justifies it. |

## Consequences

**Positive:**
- Single global logger, by construction: no more `SetLoggerError` class of bug.
- Bug #2 Fase 0 closed for real: release Windows (`windows_subsystem="windows"`)
  writes to `%LOCALAPPDATA%\com.nexe.app\logs\nexe-app.log.YYYY-MM-DD`. Support
  has a file to ask for.
- Structured `tracing::info!(key = value, ...)` fields reach both stdout and
  the file layer. No format divergence between transports.
- `cargo tree | wc -l` decreases: `tauri-plugin-log` brought `fern`, `colored`,
  and other transitive deps; `tracing-appender` adds only
  `crossbeam-channel` + `time`. Net binary size delta is a reduction (not
  measured in this session — tooling absent; flagged as desirable metric for
  follow-up).
- Runtime-verified on macOS at commit-time (Mac Gates 1–4 all pass with file
  writes confirmed).

**Negative / risks:**
- Daily rotation produces an unbounded number of files over time (no automatic
  retention). Acceptable for typical single-user desktop app volumes; if this
  becomes a support concern, revisit option **D** or add a retention cron.
- `tracing-appender` uses a background worker thread (the non-blocking writer).
  The `WorkerGuard` must remain live for the entire process lifetime to flush
  pending writes. The `static APPENDER_GUARD: OnceLock<WorkerGuard>` pattern in
  `logging.rs` covers this; any future refactor must preserve it.
- Integration testing of `init()` itself is intentionally absent from the unit
  test suite: `tracing` global state is set-once-per-process, so a unit test
  that called `init()` would contaminate every subsequent test. Coverage of
  `init()` is via runtime gates only. The helper functions (`resolve_log_dir_with`,
  `build_file_writer`) are covered by OS-agnostic unit tests.

## Runtime gates that verify this ADR's claim

This ADR is validated post-hoc by the following runtime observations, all of
which must hold on every supported platform before the decision can be
considered safely shipped:

1. `pnpm tauri dev` opens a window without any `failed to initialize plugin`
   error.
2. The log directory (`data_local_dir()/com.nexe.app/logs/`) is created and
   contains a `nexe-app.log.YYYY-MM-DD` file.
3. The file contains at minimum an `INFO nexe_app_lib::logging: nexe-app
   tracing initialized` line and an `INFO nexe_app_lib: auth token generated`
   line.
4. The bundled debug binary
   (`src-tauri/target/debug/bundle/<platform>/...`) starts without panic.

**Status 2026-04-22:** macOS runtime-verified 4/4 by Jordi (session logged in
`diari/informes/20260422_runtime_fix_aplicat.md` — internal diary, not exposed
in this OSS repo). Windows ARM64 VM + Linux UTM human GUI gates are deferred
to a follow-up session; the CI matrix (ubuntu-latest + macos-latest +
windows-latest) covers cargo-level build/test/clippy/audit on every push.

## Implementation references

- `src-tauri/src/logging.rs` — module ownership of the init pipeline (this
  commit).
- `src-tauri/src/lib.rs:run()` — calls `crate::logging::init()` once before
  `tauri::Builder::default()`.
- `src-tauri/Cargo.toml` — declares `tracing-appender = "0.2"`; no
  `tauri-plugin-log` entry.
- `CHANGELOG.md [0.1.2-hotfix-runtime]` — records the claim
  retraction and fix.
- `SECURITY.md §Observability` — updated to describe the new pipeline.

## Notes

This ADR is also a retraction: the Sprint 0.18 documentation added `(C15)`
markers to `SECURITY.md` and `CHANGELOG.md` claiming that the plugin coexisted
safely with `tracing-subscriber`. Those claims were empirically incorrect. The
lesson recorded alongside this decision is that runtime gates (human GUI
boot) are not substitutable with unit/integration test counts. Red team passes
conducted by subagent sessions cannot execute a windowed desktop process.

Every future claim about logger, dialog, tray, deep-link, or any other Tauri
plugin behavior in `nexe-app` must be gated on a human `pnpm tauri dev`
observation on at least one target platform before being written into
`SECURITY.md` or `CHANGELOG.md` as verified. This is the same principle as
"tests verify code correctness, not feature correctness" applied one level up.
