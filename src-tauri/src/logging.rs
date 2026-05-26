//! Logger pipeline — ADR-0017 (2026-04-22).
//!
//! Single source of truth for logging: `tracing` + `tracing-subscriber`
//! with stdout (dev) + file rolling daily layers (release + dev). Replaces
//! `tauri-plugin-log` (bug #2 real Phase 0 — the plugin called
//! `log::set_boxed_logger` after `tracing-subscriber` had already
//! installed its own via the `LogTracer` pulled in by transitive `tracing-log`,
//! producing `SetLoggerError` at boot).
//!
//! Cross-platform: `dirs::data_local_dir()` resolves natively to:
//!   - macOS: `~/Library/Application Support/com.nexe.app/logs/`
//!   - Linux: `~/.local/share/com.nexe.app/logs/`
//!   - Windows: `%LOCALAPPDATA%\com.nexe.app\logs\`
//!
//! On Windows GUI release (`windows_subsystem="windows"`) there is no stdout
//! attached; the file layer is the source for support. The stdout layer is
//! harmless in this case (writes to a disconnected handle, no panic).
//!
//! Third-party crates emitting via `log::*` (internal tauri,
//! tauri-plugin-dialog, etc.) reach this subscriber automatically
//! via the global `LogTracer` that `tracing-subscriber` installs by default
//! when the transitive feature `tracing-log` is in the dep graph.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use tracing_appender::non_blocking::{NonBlocking, WorkerGuard};
use tracing_appender::rolling;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

/// The `WorkerGuard` from the non-blocking appender must live for the entire
/// process duration so the worker thread does not stop and pending messages
/// are flushed. `OnceLock::set` guarantees only one call wins; subsequent
/// calls are no-ops (idempotent defense against double `init()`).
static APPENDER_GUARD: OnceLock<WorkerGuard> = OnceLock::new();

const APP_DATA_SUBDIR: &str = "com.nexe.app";
const LOGS_SUBDIR: &str = "logs";
const LOG_FILE_PREFIX: &str = "nexe-app.log";

/// Initializes the global logger.
///
/// Call it ONCE from `run()`. Idempotent: a second call
/// returns `Err` from `try_init()` which we log to `stderr` without panicking.
pub(crate) fn init() {
    let log_dir = resolve_log_dir();
    let file_writer = build_file_writer(&log_dir);
    // `Option<fmt::Layer<..>>` implements `Layer<S>` natively (idiomatic
    // tracing-subscriber: `None` is a no-op). Avoids `Box<dyn Layer>` which breaks
    // `SubscriberInitExt` on the resulting `Layered`.
    let file_layer = file_writer.map(|writer| {
        fmt::layer()
            .with_writer(writer)
            .with_ansi(false)
            .with_target(true)
    });

    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    let stdout_layer = fmt::layer().with_writer(std::io::stdout).with_target(true);

    let init_result = tracing_subscriber::registry()
        .with(filter)
        .with(stdout_layer)
        .with(file_layer)
        .try_init();

    match init_result {
        Ok(()) => {
            tracing::info!(
                version = env!("CARGO_PKG_VERSION"),
                log_dir = %log_dir.display(),
                "nexe-app tracing initialized"
            );
        }
        Err(e) => {
            eprintln!("nexe-app: tracing init skipped ({e})");
        }
    }
}

/// Resolves the log directory cross-platform.
fn resolve_log_dir() -> PathBuf {
    resolve_log_dir_with(dirs::data_local_dir())
}

/// Injectable version for pure testability (no syscall).
fn resolve_log_dir_with(base: Option<PathBuf>) -> PathBuf {
    base.map(|p| p.join(APP_DATA_SUBDIR).join(LOGS_SUBDIR))
        .unwrap_or_else(|| PathBuf::from("./logs"))
}

/// Builds the `NonBlocking` writer for the file appender if the directory can be created.
/// Best-effort: if `create_dir_all` fails (read-only FS, permission denied,
/// parent is a file, invalid cross-platform path), returns `None`
/// and the logger falls back to stdout-only without panicking.
///
/// The `WorkerGuard` from `non_blocking()` is stored in `APPENDER_GUARD`.
/// A second invocation (double-init test) causes `.set()` to return `Err`
/// which we ignore (first-init wins).
///
/// We return the `NonBlocking` (not the `Layer`) because `Option<fmt::Layer<..>>`
/// implements `Layer<S>` natively and allows chaining with `registry().with(...)`
/// without `Box<dyn Layer>` / `SubscriberInitExt` type issues.
fn build_file_writer(log_dir: &Path) -> Option<NonBlocking> {
    std::fs::create_dir_all(log_dir).ok()?;
    let file_appender = rolling::daily(log_dir, LOG_FILE_PREFIX);
    let (writer, guard) = tracing_appender::non_blocking(file_appender);
    let _ = APPENDER_GUARD.set(guard);
    Some(writer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_log_dir_ends_with_app_logs() {
        let base = PathBuf::from("/tmp/fake-data-local");
        let got = resolve_log_dir_with(Some(base.clone()));
        assert!(
            got.ends_with(Path::new(APP_DATA_SUBDIR).join(LOGS_SUBDIR)),
            "expected path to end with {APP_DATA_SUBDIR}/{LOGS_SUBDIR}, got {got:?}"
        );
        assert!(
            got.starts_with(&base),
            "expected path prefixed by {base:?}, got {got:?}"
        );
    }

    #[test]
    fn resolve_log_dir_fallback_when_data_local_dir_missing() {
        let got = resolve_log_dir_with(None);
        assert_eq!(got, PathBuf::from("./logs"));
    }

    #[test]
    fn build_file_writer_returns_none_when_parent_is_a_file() {
        // Creates a regular file and tries to create a subdir inside it — `create_dir_all`
        // must fail cross-platform (cannot create a directory inside a regular file).
        // This way we do not touch `APPENDER_GUARD` (the `ok()?` early-return path)
        // and the test is deterministic and parallel-safe.
        let tmp = std::env::temp_dir();
        let file_path = tmp.join(format!(
            "nexe-app-logging-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        std::fs::write(&file_path, b"x").expect("write temp marker file");
        let subdir = file_path.join("subdir");

        let writer = build_file_writer(&subdir);

        // Clean up before asserting to guarantee removal regardless of assertion outcome.
        let _ = std::fs::remove_file(&file_path);

        assert!(
            writer.is_none(),
            "expected None when parent is a file (path {subdir:?})"
        );
    }
}
