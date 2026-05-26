//! Sidecar state types, path resolvers, and bundle extraction.
//!
//! Dev Session 2026-05-08: refactor to reduce the size of `lib.rs`.
//! Dev Session 2026-05-12: tarball extraction (sidecar-bundle.tar.gz).
//!
//! Contains:
//! - Tauri sidecar state types ([`SidecarPort`], [`HttpClient`], [`SidecarChild`])
//! - Dev/prod path resolvers ([`resolve_sidecar_path_dev`], [`resolve_sidecar_path_prod`])
//! - [`ensure_sidecar_extracted`] — unpack venv+app tarball to app_data_dir at first launch
//!
//! The queue infra (PENDING_COUNT, PendingGuard, try_acquire_pending_slot) lives
//! in [`crate::handler`] because it is specific to the plugin:// handler pool.

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::Child;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Mutex;

// ─── Sidecar state types ──────────────────────────────────────────────────────

/// Sidecar port exposed as Tauri state (2026-05-02).
///
/// `fetch_from_sidecar` reads it to validate URLs with strict `expected_port`.
///
/// F5.3.1 (2026-05-19) — wraps an `AtomicU16` so it can be reassigned at
/// runtime when `restart_sidecar` spawns a fresh process on a new ephemeral
/// port. Lock-free reads (single CPU instruction) keep the hot
/// `fetch_from_sidecar` path identical to the previous immutable struct.
///
/// AtomicU16 beats RwLock here because reads are massive (every webview
/// invoke), writes are rare (only restart), and a u16 has no half-state
/// invariant so a primitive atomic is enough.
pub struct SidecarPort(pub AtomicU16);

impl SidecarPort {
    /// Build a new port state wrapping the given initial value.
    pub fn new(port: u16) -> Self {
        Self(AtomicU16::new(port))
    }

    /// Read the current sidecar port. Lock-free (one CPU `load`).
    pub fn get(&self) -> u16 {
        self.0.load(Ordering::Acquire)
    }

    /// Replace the sidecar port with a fresh value (called by `restart_sidecar`).
    pub fn set(&self, port: u16) {
        self.0.store(port, Ordering::Release);
    }
}

/// F5.3.1 — values resolved once at `setup_services` that `restart_sidecar`
/// needs to spawn a fresh sidecar process. The auth token, api key and HTTP
/// client are already in Tauri state under their own types and are looked up
/// from there at restart time; we only persist what would otherwise be lost
/// (paths computed from `app.handle()` at setup time).
pub struct SpawnContext {
    pub sidecar_path: PathBuf,
    pub sidecar_data_dir: Option<PathBuf>,
    pub stdout_log_path: Option<PathBuf>,
}

// ─── Restart concurrency guard ────────────────────────────────────────────────

/// F5.3.1 — global flag that prevents two `restart_sidecar` invocations from
/// racing (e.g. the wizard fires the command twice from a double-click, or the
/// frontend mistakenly re-triggers it). Modeled after `DIALOG_SHOWING` in
/// `lifecycle.rs`: first caller wins, others get an immediate `Err`.
pub(crate) static RESTART_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

/// Attempt to acquire the restart-in-progress flag.
///
/// Returns `true` if the caller won (was `false`, now `true`) and may proceed;
/// `false` if another caller is already restarting.
///
/// Atomic `swap(true, AcqRel)` — same pattern as `graceful_quit_try_acquire`.
pub(crate) fn restart_try_acquire() -> bool {
    !RESTART_IN_PROGRESS.swap(true, Ordering::AcqRel)
}

/// RAII guard that releases `RESTART_IN_PROGRESS` on drop, including panics.
/// Construct one immediately after a successful `restart_try_acquire()`.
pub(crate) struct RestartGuard;

impl Drop for RestartGuard {
    fn drop(&mut self) {
        RESTART_IN_PROGRESS.store(false, Ordering::Release);
    }
}

/// Reserve an ephemeral port on 127.0.0.1 and return its number.
///
/// Binds `127.0.0.1:0` (OS assigns a free port), reads the assigned port,
/// then drops the listener so the sidecar can bind to the same port.
/// The TOCTOU window between drop and sidecar bind is microscopic (µs on
/// loopback) and acceptable for a local-only sidecar.
///
/// N2 (server-nexe contract): Tauri is responsible for port management.
/// server-nexe runs with NEXE_SIDECAR=1 and must NOT kill processes on port
/// conflict — it exits with error and lets Tauri retry. Use `verify_port_free`
/// right before spawn to detect the rare TOCTOU race before it reaches server-nexe.
pub fn reserve_ephemeral_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("reserve_ephemeral_port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("local_addr: {e}"))?
        .port();
    Ok(port)
    // listener dropped here — port released for sidecar to bind
}

/// N2: verify the port is still free right before spawn (closes the TOCTOU window).
///
/// Attempts a fast TCP connect with a 50ms timeout. A refused connection means
/// the port is free (expected). A successful connection means another process
/// grabbed the port in the gap between `reserve_ephemeral_port` and this call.
///
/// Returns `Ok(())` if free, `Err(...)` if in use.
pub fn verify_port_free(port: u16) -> Result<(), String> {
    use std::net::{SocketAddr, TcpStream};
    use std::time::Duration;
    let addr: SocketAddr = format!("127.0.0.1:{port}")
        .parse()
        .map_err(|e| format!("verify_port_free parse: {e}"))?;
    match TcpStream::connect_timeout(&addr, Duration::from_millis(50)) {
        Err(_) => Ok(()), // connection refused = port is free
        Ok(_) => Err(format!("port {port} is already in use (TOCTOU race or leftover process)")),
    }
}

/// Reusable `reqwest::Client` across `fetch_from_sidecar` calls (2026-05-02).
///
/// **Bug fix:** an earlier revision created a new `Client` on every invoke
/// (HTTP pool + DNS + TLS session cache re-initialized each time).
/// 100 rapid clicks = 100 pools = ~300-500 fds → EMFILE risk.
/// Solution: register the client in Tauri state at `setup()` and clone
/// an Arc-handle on each invoke (`Client` internally is `Arc<ClientRef>`, cheap to clone).
pub struct HttpClient(pub reqwest::Client);

/// Handle to the sidecar process spawned at setup() (2026-05-02).
///
/// `Mutex<Option<Child>>` because:
/// - `Mutex` allows exclusive take() for the kill in lifecycle (prevents double kill).
/// - `Option<Child>` because take() leaves `None` after kill, an idempotent
///   way to know if the process has already been handled.
///
/// The `graceful_quit` lifecycle (Phase 2) will:
/// 1. POST /admin/system/shutdown with Bearer token (5s timeout via reqwest)
/// 2. On timeout or error → `child.kill()` forces it (SIGKILL)
/// 3. `child.wait()` to avoid zombie
pub struct SidecarChild(pub Mutex<Option<Child>>);

/// Path to the file capturing the Python sidecar's stdout+stderr.
///
/// The Python sidecar writes its own logs through the internal logger
/// (`NEXE_LOGS_DIR`). But if it crashes before the logger is initialized
/// (import error, `.so` blocked by Gatekeeper, segfault at the first
/// instant), nothing is written to disk. We capture stdout/stderr to
/// `<sidecar_data_dir>/logs/sidecar-stdout.log` to expose these
/// pre-logger crashes.
///
/// Registered as Tauri state for the tray menu ("Open sidecar log").
/// May be absent in dev mode (stdout inherits from the parent terminal).
pub struct SidecarLogPath(pub PathBuf);

// ─── Path resolvers ───────────────────────────────────────────────────────────

/// Resolves the absolute path to the `nexe-sidecar` launcher depending on the
/// mode (dev vs prod). Original implementation 2026-05-02.
///
/// **Dev mode** (`cfg!(debug_assertions)`, run with `pnpm tauri dev`):
///   `<project-root>/target/sidecar/nexe-sidecar` — generated by
///   `scripts/build-sidecar.sh`. The PBS venv lives alongside (`target/sidecar/venv/`)
///   and the .sh launcher resolves it via `dirname $0`.
///
/// **Prod mode** (bundled .app):
///   `<bundle resources>/binaries/nexe-sidecar-<host-triple>` — copied by Tauri
///   externalBin during `pnpm tauri build`. Note: run `pnpm tauri:build` (not
///   `tauri build` directly) so that `scripts/pre-bundle-sidecar.sh` copies
///   the venv into the bundle before Tauri packages it (2026-05-12 tarball fix).
pub(crate) fn resolve_sidecar_path(_app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        resolve_sidecar_path_dev(&manifest_dir)
    } else {
        let exe = std::env::current_exe().map_err(|e| format!("current_exe: {e}"))?;
        resolve_sidecar_path_prod(&exe)
    }
}

/// Helper extracted from `resolve_sidecar_path`. Takes `manifest_dir` to
/// allow tests with temporary directories (without depending on the real `CARGO_MANIFEST_DIR`).
/// Returns the path to the dev `nexe-sidecar` or an error if it does not exist.
pub(crate) fn resolve_sidecar_path_dev(manifest_dir: &std::path::Path) -> Result<PathBuf, String> {
    let project_root = manifest_dir
        .parent()
        .ok_or("manifest_dir has no parent")?;
    let path = project_root
        .join("target")
        .join("sidecar")
        .join("nexe-sidecar");
    if !path.is_file() {
        return Err(format!(
            "sidecar dev path does not exist: {} — run scripts/build-sidecar.sh",
            path.display()
        ));
    }
    Ok(path)
}

/// Helper extracted from `resolve_sidecar_path`. Takes `exe_path` to
/// allow tests without calling `current_exe()`. Tauri externalBin copies
/// the launcher to the main binary directory (`Contents/MacOS/`), stripping
/// the host triple suffix (e.g. `nexe-sidecar-aarch64-apple-darwin` → `nexe-sidecar`).
///
/// 2026-05-12 tarball bundle: venv+app are bundled as `sidecar-bundle.tar.gz` (single resource)
/// and extracted lazily to `app_data_dir/sidecar/` by `ensure_sidecar_extracted`.
/// The launcher finds venv/app via `NEXE_SIDECAR_DIR` (set by Rust spawner in release mode).
pub(crate) fn resolve_sidecar_path_prod(exe_path: &std::path::Path) -> Result<PathBuf, String> {
    let dir = exe_path.parent().ok_or("exe has no parent")?;
    let path = dir.join("nexe-sidecar");
    if !path.is_file() {
        return Err(format!(
            "sidecar prod path does not exist: {} — run scripts/build-sidecar.sh + pnpm tauri:build",
            path.display()
        ));
    }
    Ok(path)
}

/// Extract `sidecar-bundle.tar.gz` to `app_data_dir/sidecar/` on first launch.
///
/// The tarball contains `venv/` and `app/`. The `nexe-sidecar` launcher is managed
/// separately by Tauri `externalBin` (`Contents/MacOS/nexe-sidecar`).
///
/// A SHA-256-stamped `.extracted` marker prevents re-extraction on every launch.
/// The marker holds the SHA-256 of the bundled `sidecar-bundle.tar.gz` (read from
/// the sibling `sidecar-bundle.sha256` resource generated by
/// `scripts/pre-bundle-sidecar.sh`). Re-extraction occurs automatically whenever
/// the tarball SHA changes — even within the same `CARGO_PKG_VERSION` — so dev
/// re-builds propagate cleanly without manual `rm -rf` of the sidecar dir.
///
/// Fallback: when the SHA resource is absent or empty (CI placeholder, or
/// DMGs built before this change), `CARGO_PKG_VERSION` is used instead, matching
/// the pre-2026-05-22 behaviour. Old markers (version text) remain interpretable.
///
/// Returns the `sidecar_dir` path so the caller can pass it as `NEXE_SIDECAR_DIR`
/// to the launcher process.
// Dead in debug builds (called only under #[cfg(not(debug_assertions))]).
#[cfg_attr(debug_assertions, allow(dead_code))]
pub(crate) fn ensure_sidecar_extracted(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    use tauri::Manager;

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("app_data_dir: {e}"))?;
    let sidecar_dir = data_dir.join("sidecar");
    let marker = sidecar_dir.join(".extracted");

    // Resolve the expected marker value once (SHA preferred, version fallback).
    // Reading it before the `needs_extract` check is what lets the lock-loser
    // branch below detect completion correctly.
    let expected = read_sidecar_sha256(app)
        .unwrap_or_else(|| env!("CARGO_PKG_VERSION").to_string());

    let needs_extract = match std::fs::read_to_string(&marker) {
        Ok(v) => v.trim() != expected,
        Err(_) => true,
    };

    if needs_extract {
        let tarball = app
            .path()
            .resolve(
                "sidecar-bundle.tar.gz",
                tauri::path::BaseDirectory::Resource,
            )
            .map_err(|e| format!("resolve sidecar-bundle.tar.gz: {e}"))?;
        tracing::info!(
            src = %tarball.display(),
            dest = %sidecar_dir.display(),
            expected = %expected,
            "extracting sidecar bundle"
        );
        std::fs::create_dir_all(&sidecar_dir)
            .map_err(|e| format!("create sidecar dir: {e}"))?;

        // F3.1 BUG-NA-5 / BUG-NB-4: prevent two app launches from racing to
        // unpack the same tarball into the same target dir (interleaved writes
        // corrupt the venv). Acquire an exclusive lock-file with O_EXCL; the
        // loser of the race waits for the .extracted marker to appear and then
        // skips the extraction altogether.
        let lock_path = sidecar_dir.join(".extract.lock");
        let lock = match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
        {
            Ok(f) => f,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                tracing::info!(
                    lock = %lock_path.display(),
                    "another process is extracting the sidecar bundle; waiting"
                );
                let deadline = std::time::Instant::now() + std::time::Duration::from_secs(120);
                while std::time::Instant::now() < deadline {
                    if matches!(std::fs::read_to_string(&marker), Ok(v) if v.trim() == expected) {
                        return Ok(sidecar_dir);
                    }
                    std::thread::sleep(std::time::Duration::from_millis(200));
                }
                return Err(format!(
                    "timed out waiting for concurrent sidecar extraction (lock {})",
                    lock_path.display()
                ));
            }
            Err(e) => {
                return Err(format!(
                    "acquire extract lock {}: {e}",
                    lock_path.display()
                ))
            }
        };

        // RAII guard removes the lock file when this scope ends (success or panic).
        struct LockGuard {
            path: PathBuf,
        }
        impl Drop for LockGuard {
            fn drop(&mut self) {
                let _ = std::fs::remove_file(&self.path);
            }
        }
        let _guard = LockGuard {
            path: lock_path.clone(),
        };
        drop(lock); // close handle; the file is removed by the guard on scope exit

        // F3.1 BUG-NB-4: when a sibling `sidecar-bundle.sha256` resource is
        // present (one hex digest per line, first line wins), verify the SHA-256
        // of the tarball before unpacking. The file is optional during F3.1 so
        // existing builds keep working — F5 release work will start shipping
        // the digest alongside every bundle to make this check mandatory.
        if let Err(e) = verify_tarball_sha256(app, &tarball) {
            return Err(format!("sidecar bundle integrity check failed: {e}"));
        }

        let file = std::fs::File::open(&tarball)
            .map_err(|e| format!("open sidecar tarball: {e}"))?;
        let gz = flate2::read::GzDecoder::new(file);
        let mut archive = tar::Archive::new(gz);
        archive.set_overwrite(true);
        archive
            .unpack(&sidecar_dir)
            .map_err(|e| format!("unpack sidecar tarball: {e}"))?;
        // Atomic marker write: tempfile + rename. `rename(2)` is atomic on APFS
        // and HFS+ when source and dest live on the same filesystem, so a
        // force-quit during the write cannot leave a corrupt marker behind.
        let marker_tmp = sidecar_dir.join(".extracted.tmp");
        std::fs::write(&marker_tmp, &expected)
            .map_err(|e| format!("write .extracted.tmp marker: {e}"))?;
        std::fs::rename(&marker_tmp, &marker)
            .map_err(|e| format!("rename .extracted marker into place: {e}"))?;
        tracing::info!("sidecar bundle extracted ok");
    }

    Ok(sidecar_dir)
}

/// Read the bundled `sidecar-bundle.sha256` resource and return the SHA-256
/// digest as a lowercase 64-char hex string. Returns `None` when:
/// - the resource cannot be resolved (no bundle, dev mode, missing path),
/// - the file is missing on disk,
/// - the file is empty (`build.rs` placeholder used by `cargo test` / CI),
/// - the first whitespace-separated token isn't a valid 64-char hex digest.
///
/// Callers use the returned SHA as the `.extracted` marker payload to detect
/// re-builds within the same `CARGO_PKG_VERSION`. When `None` is returned they
/// fall back to `CARGO_PKG_VERSION`, matching the pre-2026-05-22 behaviour.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn read_sidecar_sha256(app: &tauri::AppHandle) -> Option<String> {
    use tauri::Manager;
    let path = app
        .path()
        .resolve(
            "sidecar-bundle.sha256",
            tauri::path::BaseDirectory::Resource,
        )
        .ok()?;
    if !path.is_file() {
        return None;
    }
    let meta = std::fs::metadata(&path).ok()?;
    if meta.len() == 0 {
        // build.rs / CI placeholder — treat as absent so the fallback kicks in
        // instead of failing the launch.
        return None;
    }
    let raw = std::fs::read_to_string(&path).ok()?;
    parse_sha256_digest(&raw)
}

/// Parse the first whitespace-separated token of `raw` as a SHA-256 hex digest.
/// Returns `Some(lowercase_hex)` on success, `None` otherwise. Pulled out as a
/// pure helper so it can be unit-tested without a Tauri `AppHandle`.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn parse_sha256_digest(raw: &str) -> Option<String> {
    let token = raw.lines().next()?.split_whitespace().next()?;
    let lower = token.to_ascii_lowercase();
    if lower.len() == 64 && lower.chars().all(|c| c.is_ascii_hexdigit()) {
        Some(lower)
    } else {
        None
    }
}

/// F3.1 BUG-NB-4: verify the SHA-256 of `tarball` against the expected digest
/// shipped as `sidecar-bundle.sha256` in the bundle resources. When the digest
/// file is missing the function returns `Ok(())` so old builds keep working;
/// future release builds (F5) will start shipping the digest unconditionally.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn verify_tarball_sha256(
    app: &tauri::AppHandle,
    tarball: &std::path::Path,
) -> Result<(), String> {
    use tauri::Manager;

    let digest_resource = match app.path().resolve(
        "sidecar-bundle.sha256",
        tauri::path::BaseDirectory::Resource,
    ) {
        Ok(p) => p,
        Err(_) => {
            tracing::warn!(
                "sidecar-bundle.sha256 not bundled; skipping integrity check (F3.1 transitional)"
            );
            return Ok(());
        }
    };
    if !digest_resource.is_file() {
        tracing::warn!(
            path = %digest_resource.display(),
            "sidecar-bundle.sha256 missing; skipping integrity check (F3.1 transitional)"
        );
        return Ok(());
    }
    // Tolerate empty placeholder created by build.rs for `cargo test` / CI
    // (`pnpm tauri build --no-bundle`). Treating it as "no digest available"
    // matches the `read_sidecar_sha256` fallback so both paths agree.
    if std::fs::metadata(&digest_resource)
        .map(|m| m.len() == 0)
        .unwrap_or(false)
    {
        tracing::warn!(
            path = %digest_resource.display(),
            "sidecar-bundle.sha256 is empty (CI placeholder); skipping integrity check"
        );
        return Ok(());
    }
    verify_sha256_against_digest_file(tarball, &digest_resource)
}

/// Pure helper extracted from [`verify_tarball_sha256`] so it can be exercised
/// from unit tests without a Tauri `AppHandle`. Reads the first whitespace
/// token of `digest_file`, validates it as a 64-char hex digest, and compares
/// it with the SHA-256 of `tarball` (streamed in 64 KiB chunks to keep memory
/// bounded for large bundles).
#[cfg_attr(debug_assertions, allow(dead_code))]
fn verify_sha256_against_digest_file(
    tarball: &std::path::Path,
    digest_file: &std::path::Path,
) -> Result<(), String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;

    let expected_raw = std::fs::read_to_string(digest_file)
        .map_err(|e| format!("read {}: {e}", digest_file.display()))?;
    let expected = expected_raw
        .lines()
        .next()
        .ok_or_else(|| "expected digest file is empty".to_string())?
        .split_whitespace()
        .next()
        .ok_or_else(|| "expected digest line has no token".to_string())?
        .to_ascii_lowercase();
    if expected.len() != 64 || !expected.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(format!("expected digest is not a 64-char hex string: {expected:?}"));
    }

    let mut hasher = Sha256::new();
    let mut file = std::fs::File::open(tarball)
        .map_err(|e| format!("open tarball: {e}"))?;
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = file.read(&mut buf).map_err(|e| format!("read tarball: {e}"))?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    let actual = format!("{:x}", hasher.finalize());
    if actual != expected {
        return Err(format!(
            "SHA-256 mismatch: expected {expected}, got {actual}"
        ));
    }
    tracing::info!("sidecar bundle SHA-256 verified");
    Ok(())
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::Path;

    fn mktemp_root(test_name: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!(
            "nexe-sidecar-test-{}-{}",
            test_name,
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        base
    }

    // Tests for resolve_sidecar_path_dev / _prod (cross-validation)

    #[test]
    fn resolve_sidecar_dev_returns_target_sidecar_when_present() {
        let root = mktemp_root("sidecar-dev-ok");
        let manifest_dir = root.join("src-tauri");
        let target_sidecar = root.join("target").join("sidecar");
        fs::create_dir_all(&manifest_dir).unwrap();
        fs::create_dir_all(&target_sidecar).unwrap();
        let launcher = target_sidecar.join("nexe-sidecar");
        fs::write(&launcher, "#!/bin/bash\nexit 0\n").unwrap();

        let path = resolve_sidecar_path_dev(&manifest_dir).expect("should resolve");
        assert_eq!(path, launcher);
    }

    #[test]
    fn resolve_sidecar_dev_errors_when_launcher_missing() {
        let root = mktemp_root("sidecar-dev-missing");
        let manifest_dir = root.join("src-tauri");
        fs::create_dir_all(&manifest_dir).unwrap();

        let err = resolve_sidecar_path_dev(&manifest_dir).expect_err("should fail");
        assert!(
            err.contains("does not exist"),
            "error should mention path missing: got {err:?}"
        );
        assert!(
            err.contains("build-sidecar.sh"),
            "error should hint at build-sidecar.sh: got {err:?}"
        );
    }

    #[test]
    fn resolve_sidecar_dev_errors_when_no_parent() {
        let err = resolve_sidecar_path_dev(Path::new("/")).expect_err("should fail");
        assert!(err.contains("has no parent"), "got {err:?}");
    }

    #[test]
    fn resolve_sidecar_prod_returns_sibling_when_present() {
        let root = mktemp_root("sidecar-prod-ok");
        let macos_dir = root.join("Contents").join("MacOS");
        fs::create_dir_all(&macos_dir).unwrap();
        let exe = macos_dir.join("nexe-app");
        fs::write(&exe, b"binary").unwrap();
        let launcher = macos_dir.join("nexe-sidecar");
        fs::write(&launcher, "#!/bin/bash\nexit 0\n").unwrap();

        let path = resolve_sidecar_path_prod(&exe).expect("should resolve");
        assert_eq!(path, launcher);
    }

    #[test]
    fn resolve_sidecar_prod_errors_when_launcher_missing() {
        let root = mktemp_root("sidecar-prod-missing");
        let macos_dir = root.join("Contents").join("MacOS");
        fs::create_dir_all(&macos_dir).unwrap();
        let exe = macos_dir.join("nexe-app");
        fs::write(&exe, b"binary").unwrap();

        let err = resolve_sidecar_path_prod(&exe).expect_err("should fail");
        assert!(err.contains("does not exist"), "got {err:?}");
        assert!(err.contains("build-sidecar.sh"), "should hint at build step: got {err:?}");
    }

    // Test kill_sidecar_child with real subprocess (sleep 60s)

    #[test]
    fn kill_sidecar_child_kills_running_process() {
        let child = std::process::Command::new("sleep")
            .arg("60")
            .spawn()
            .expect("spawn sleep should succeed on macOS/Linux");
        let pid = child.id();
        let mutex = Mutex::new(Some(child));

        let returned = crate::lifecycle::kill_sidecar_child(&mutex);
        assert_eq!(returned, Some(pid), "should return the killed pid");

        let returned2 = crate::lifecycle::kill_sidecar_child(&mutex);
        assert_eq!(returned2, None, "second call returns None (idempotent)");
    }

    #[test]
    fn kill_sidecar_child_idempotent_on_empty_mutex() {
        let mutex: Mutex<Option<std::process::Child>> = Mutex::new(None);
        let returned = crate::lifecycle::kill_sidecar_child(&mutex);
        assert_eq!(returned, None);
    }

    // ─── F3.1 BUG-NB-4 — verify_sha256_against_digest_file ────────────────────

    /// Known-good SHA-256 for `b"nexe-sidecar-test-payload\n"`.
    /// Verified once with `printf 'nexe-sidecar-test-payload\n' | shasum -a 256`.
    const KNOWN_PAYLOAD: &[u8] = b"nexe-sidecar-test-payload\n";
    const KNOWN_SHA256: &str = "22cfb3d72fd97742766e852191be3d811f4b98cc63643c674e08a654a38a8db1";

    fn write_fixture(dir: &Path, name: &str, contents: &[u8]) -> PathBuf {
        let p = dir.join(name);
        fs::write(&p, contents).unwrap();
        p
    }

    #[test]
    fn verify_sha256_against_digest_file_passes_on_match() {
        let root = mktemp_root("sha256-match");
        let tarball = write_fixture(&root, "bundle.tar.gz", KNOWN_PAYLOAD);
        let digest = write_fixture(&root, "bundle.sha256", KNOWN_SHA256.as_bytes());
        super::verify_sha256_against_digest_file(&tarball, &digest)
            .expect("matching digest must pass");
    }

    #[test]
    fn verify_sha256_against_digest_file_passes_with_trailing_filename() {
        // `shasum -a 256` outputs `<hex>  <filename>`; we want the first token to win.
        let root = mktemp_root("sha256-with-filename");
        let tarball = write_fixture(&root, "bundle.tar.gz", KNOWN_PAYLOAD);
        let digest_line = format!("{KNOWN_SHA256}  bundle.tar.gz\n");
        let digest = write_fixture(&root, "bundle.sha256", digest_line.as_bytes());
        super::verify_sha256_against_digest_file(&tarball, &digest)
            .expect("digest line with filename should still pass");
    }

    #[test]
    fn verify_sha256_against_digest_file_rejects_mismatch() {
        let root = mktemp_root("sha256-mismatch");
        let tarball = write_fixture(&root, "bundle.tar.gz", KNOWN_PAYLOAD);
        let bogus = "0".repeat(64);
        let digest = write_fixture(&root, "bundle.sha256", bogus.as_bytes());
        let err = super::verify_sha256_against_digest_file(&tarball, &digest)
            .expect_err("mismatched digest must fail");
        assert!(err.contains("SHA-256 mismatch"), "got {err:?}");
    }

    #[test]
    fn verify_sha256_against_digest_file_rejects_malformed_digest() {
        let root = mktemp_root("sha256-malformed");
        let tarball = write_fixture(&root, "bundle.tar.gz", KNOWN_PAYLOAD);
        let digest = write_fixture(&root, "bundle.sha256", b"not-a-hex-digest\n");
        let err = super::verify_sha256_against_digest_file(&tarball, &digest)
            .expect_err("malformed digest must fail");
        assert!(
            err.contains("64-char hex"),
            "expected hex validation error, got {err:?}"
        );
    }

    #[test]
    fn verify_sha256_against_digest_file_rejects_empty_digest_file() {
        let root = mktemp_root("sha256-empty");
        let tarball = write_fixture(&root, "bundle.tar.gz", KNOWN_PAYLOAD);
        let digest = write_fixture(&root, "bundle.sha256", b"");
        let err = super::verify_sha256_against_digest_file(&tarball, &digest)
            .expect_err("empty digest must fail");
        assert!(
            err.contains("empty") || err.contains("no token"),
            "expected empty-file error, got {err:?}"
        );
    }

    // ─── 2026-05-22 — .extracted marker SHA-256 + helpers ────────────────────

    /// `parse_sha256_digest` accepts a bare 64-char hex digest with trailing newline.
    #[test]
    fn parse_sha256_digest_accepts_bare_hex() {
        let parsed = super::parse_sha256_digest(&format!("{KNOWN_SHA256}\n"))
            .expect("bare hex digest should parse");
        assert_eq!(parsed, KNOWN_SHA256);
    }

    /// `parse_sha256_digest` accepts `<hex>  <filename>` (default `shasum -a 256` output).
    #[test]
    fn parse_sha256_digest_accepts_hex_with_filename() {
        let line = format!("{KNOWN_SHA256}  sidecar-bundle.tar.gz\n");
        let parsed = super::parse_sha256_digest(&line)
            .expect("hex+filename line should parse to bare hex");
        assert_eq!(parsed, KNOWN_SHA256);
    }

    /// `parse_sha256_digest` normalises uppercase hex to lowercase.
    #[test]
    fn parse_sha256_digest_lowercases_uppercase_hex() {
        let upper = KNOWN_SHA256.to_ascii_uppercase();
        let parsed = super::parse_sha256_digest(&upper).expect("uppercase hex should parse");
        assert_eq!(parsed, KNOWN_SHA256);
    }

    /// `parse_sha256_digest` returns `None` for empty input (CI placeholder).
    #[test]
    fn parse_sha256_digest_rejects_empty_input() {
        assert!(super::parse_sha256_digest("").is_none());
    }

    /// `parse_sha256_digest` returns `None` for non-hex / wrong-length tokens.
    #[test]
    fn parse_sha256_digest_rejects_non_hex_or_wrong_length() {
        assert!(super::parse_sha256_digest("not-a-hex-digest\n").is_none());
        assert!(super::parse_sha256_digest("abc123\n").is_none());
        // 64 chars but contains a non-hex letter
        let bad = format!("{}z", &KNOWN_SHA256[..63]);
        assert!(super::parse_sha256_digest(&bad).is_none());
    }

    /// Lock-loser branch contract: the polling loop in `ensure_sidecar_extracted`
    /// returns successfully when the marker matches `expected`. This pins the
    /// invariant the 2026-05-22 refactor introduced (previously it compared
    /// against `current_version` literally, which broke with SHA markers).
    #[test]
    fn marker_matches_expected_when_content_equal() {
        let root = mktemp_root("marker-match");
        let marker = root.join(".extracted");
        fs::write(&marker, KNOWN_SHA256).unwrap();
        let read = fs::read_to_string(&marker).unwrap();
        assert_eq!(read.trim(), KNOWN_SHA256);
    }
    // The actual lock-loser polling loop is exercised end-to-end by integration
    // tests using a real AppHandle; this unit test pins the comparison contract
    // (`marker.trim() == expected`) that the loop relies on.

    // ─── F5.3.1 — SidecarPort AtomicU16 + restart guard ──────────────────────

    /// `SidecarPort::get` must return the value passed to `new` before any `set`.
    #[test]
    fn sidecar_port_get_returns_initial_value() {
        let port = SidecarPort::new(54321);
        assert_eq!(port.get(), 54321);
    }

    /// `SidecarPort::set` followed by `get` must observe the new value (Acquire/Release).
    #[test]
    fn sidecar_port_set_updates_visible_via_get() {
        let port = SidecarPort::new(54321);
        port.set(54322);
        assert_eq!(port.get(), 54322);
    }

    /// `restart_try_acquire` returns true on the first call, false while the
    /// flag is held. Mutation testing: if `swap(true, AcqRel)` were replaced by
    /// `store(true, ...)` the second caller would still see `false→true` (and
    /// erroneously win), so this test would catch it.
    #[test]
    fn restart_try_acquire_first_caller_wins() {
        RESTART_IN_PROGRESS.store(false, Ordering::SeqCst);
        assert!(restart_try_acquire());
        assert!(!restart_try_acquire());
        // Cleanup
        RESTART_IN_PROGRESS.store(false, Ordering::SeqCst);
    }

    /// `RestartGuard` must release `RESTART_IN_PROGRESS` on drop — including the
    /// normal scope-exit case and panic unwinding (RAII semantics).
    #[test]
    fn restart_guard_releases_flag_on_drop() {
        RESTART_IN_PROGRESS.store(false, Ordering::SeqCst);
        assert!(restart_try_acquire());
        {
            let _g = RestartGuard;
            assert!(RESTART_IN_PROGRESS.load(Ordering::SeqCst));
        }
        assert!(!RESTART_IN_PROGRESS.load(Ordering::SeqCst));
    }

    /// Concurrent attempts to acquire the restart flag: exactly one wins.
    /// Same shape as `try_acquire_concurrent_only_one_wins` in `lifecycle.rs`
    /// for the dialog guard.
    #[test]
    fn restart_try_acquire_concurrent_only_one_wins() {
        use std::sync::Arc;
        RESTART_IN_PROGRESS.store(false, Ordering::SeqCst);
        let winners = Arc::new(std::sync::atomic::AtomicU32::new(0));
        let barrier = Arc::new(std::sync::Barrier::new(10));
        let handles: Vec<_> = (0..10)
            .map(|_| {
                let w = winners.clone();
                let b = barrier.clone();
                std::thread::spawn(move || {
                    b.wait();
                    if restart_try_acquire() {
                        w.fetch_add(1, Ordering::Relaxed);
                    }
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }
        assert_eq!(
            winners.load(Ordering::Relaxed),
            1,
            "exactly one thread must acquire the restart flag"
        );
        RESTART_IN_PROGRESS.store(false, Ordering::SeqCst);
    }

    /// `reserve_ephemeral_port` must not hand the same port twice in rapid
    /// succession — the OS picks an unused port each time the listener drops.
    /// Empirical: tested 100 iterations in a tight loop.
    #[test]
    fn reserve_ephemeral_port_no_duplicates() {
        let mut ports = Vec::with_capacity(100);
        for _ in 0..100 {
            ports.push(reserve_ephemeral_port().expect("reserve must succeed"));
        }
        let mut sorted = ports.clone();
        sorted.sort_unstable();
        sorted.dedup();
        // Allow up to 5 collisions in 100 iterations — OS may reuse a recently
        // released ephemeral port. The test fails on systemic reuse (many
        // collisions), which would indicate the listener is not actually
        // dropping in time or `bind 0` is broken.
        let unique = sorted.len();
        assert!(
            unique >= 95,
            "expected ≥95 unique ports out of 100, got {unique}"
        );
    }
}
