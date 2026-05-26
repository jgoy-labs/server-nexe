//! `plugin://` URI scheme handler — ADR-0009.
//!
//! Serves plugin assets via `plugin://<plugin-id>/<path>`.
//! Example: `plugin://rag/index.html` → `plugins-dev/rag/ui/index.html`.
//!
//! Layered defenses: per-plugin rate limit + 10MB size cap + method validation
//! + strict URI validation + timing oracle padding + reentrancy guard.

use crate::integrity::{verify_and_load_plugin_asset, verify_plugin_integrity};
use crate::validate::{plugin_root, resolve_plugin_path, validate_request};
use std::collections::HashMap;
use std::path::Path;
use std::sync::OnceLock;
use std::time::Instant;
use tauri::{
    http::{Request, Response},
    Runtime,
};
use threadpool::ThreadPool;

// S03 F004: global bounded pool for the plugin:// handler (prevents thread-bomb).
// 8 threads sufficient to serve assets concurrently; excess requests are queued.
static HANDLER_POOL: OnceLock<ThreadPool> = OnceLock::new();

pub(crate) fn handler_pool() -> &'static ThreadPool {
    HANDLER_POOL.get_or_init(|| ThreadPool::new(8))
}

/// C06(2026-04-21): bounded queue threshold. If `queued_count() > MAX_QUEUED`
/// before enqueuing, we return 503. Prevents OOM from flood with late rate-limiting.
/// 256 = 32 requests/worker buffer, sufficient for legitimate bursts without
/// threatening DoS.
pub(crate) const MAX_QUEUED: usize = 256;

// F052: per-thread reentrancy counter — prevents stack overflow if a plugin
// serves a plugin://other/x recursively.
thread_local! {
    pub(crate) static HANDLER_DEPTH: std::cell::Cell<u32> = const { std::cell::Cell::new(0) };
}

pub(crate) const MAX_HANDLER_DEPTH: u32 = 4;

/// Panic-free response helper. Response::builder().body() only fails with
/// invalid headers; since we build only known static values, it should
/// never fail. Safe fallback here just in case.
///
/// Z3 Sprint 0.18 (2026-04-21): security review detected that error
/// responses (400/403/404/413/429/503) emitted by
/// this function included no defensive headers. An attacker forcing consistent
/// errors (probing non-existent plugins, rate-limit intensity) could:
///   - embed error responses in `<iframe>` (no X-Frame-Options)
///   - MIME-sniff the body text (no X-Content-Type-Options: nosniff)
///   - cache errors at an intermediary (no Cache-Control: no-store)
///   - use side-channels (no Permissions-Policy)
///
/// Fix: we add the same defensive headers as `apply_common_headers` in the
/// happy-path GET, with a stricter CSP (`default-src 'none'; frame-ancestors
/// 'none'`) because an error response MUST NOT load anything. Defense in depth
/// consistent with the rest of the handler.
pub(crate) fn err_response(status: u16, body: &[u8]) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header("Content-Type", "text/plain; charset=utf-8")
        .header("X-Content-Type-Options", "nosniff")
        .header("Cache-Control", "no-store")
        .header(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        )
        .header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), usb=(), serial=(), payment=()",
        )
        .header("Referrer-Policy", "no-referrer")
        .header("X-Frame-Options", "DENY")
        .header("Access-Control-Allow-Origin", "null")
        .body(body.to_vec())
        .unwrap_or_else(|_| Response::new(body.to_vec()))
}

/// C28/C41(2026-04-21): timing oracle mitigation.
/// 2ms was below the real cost of a cache miss (canonicalize + re-hash integrity)
/// → security theater. 50ms covers the pessimistic case with margin; UX cost
/// negligible for local assets (human eye threshold ~100ms).
/// C41: `checked_sub` prevents panic if `elapsed > TARGET` (monotonic clock wraparound).
pub(crate) fn finish_with_timing(
    response: Response<Vec<u8>>,
    started: Instant,
) -> Response<Vec<u8>> {
    const TARGET: std::time::Duration = std::time::Duration::from_millis(50);
    let elapsed = started.elapsed();
    if let Some(remaining) = TARGET.checked_sub(elapsed) {
        std::thread::sleep(remaining);
    }
    response
}

/// C06: extracts the `plugin_id` from a `plugin://<id>/<path>` URI.
/// Returns `None` if the URI has no host or the host does not pass basic format.
/// Pre-queue usage — does not perform full validation (done inside the worker via
/// `validate_plugin_id`). Simply allows us to build the rate-limit key without
/// constructing the full request yet.
pub(crate) fn extract_plugin_id_from_uri(uri: &str) -> Option<String> {
    // "plugin://<host>/<path>" — find "//" and the subsequent "/"
    let after_scheme = uri.strip_prefix("plugin://")?;
    let host_end = after_scheme.find('/').unwrap_or(after_scheme.len());
    let host = &after_scheme[..host_end];
    if host.is_empty() {
        return None;
    }
    Some(host.to_string())
}

// MIME type lookup — OnceLock<HashMap> replaces the if-else chain (CCN 21 → 3).
// Key is the lowercase extension without the dot; `content_type_for` extracts
// the extension via `rsplit('.')` (equivalent to `ends_with` for simple extensions).
static MIME_MAP: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();

fn mime_map() -> &'static HashMap<&'static str, &'static str> {
    MIME_MAP.get_or_init(|| {
        let mut m = HashMap::new();
        m.insert("html", "text/html; charset=utf-8");
        m.insert("htm", "text/html; charset=utf-8");
        m.insert("css", "text/css; charset=utf-8");
        m.insert("js", "application/javascript; charset=utf-8");
        m.insert("mjs", "application/javascript; charset=utf-8");
        m.insert("json", "application/json; charset=utf-8");
        m.insert("map", "application/json");
        m.insert("svg", "image/svg+xml");
        m.insert("png", "image/png");
        m.insert("jpg", "image/jpeg");
        m.insert("jpeg", "image/jpeg");
        m.insert("webp", "image/webp");
        m.insert("avif", "image/avif");
        m.insert("gif", "image/gif");
        m.insert("ico", "image/x-icon");
        m.insert("woff", "font/woff");
        m.insert("woff2", "font/woff2");
        m.insert("ttf", "font/ttf");
        m.insert("otf", "font/otf");
        m.insert("wasm", "application/wasm");
        m
    })
}

pub(crate) fn content_type_for(path: &str) -> &'static str {
    let ext = path.rsplit('.').next().map(|e| e.to_ascii_lowercase());
    ext.as_deref()
        .and_then(|e| mime_map().get(e).copied())
        .unwrap_or("application/octet-stream")
}

pub(crate) fn plugin_protocol_handler<R: Runtime>(
    app: &tauri::AppHandle<R>,
    request: Request<Vec<u8>>,
) -> Response<Vec<u8>> {
    let started = Instant::now();

    // F052: reentrancy guard — decrement via RAII Drop
    struct DepthGuard;
    impl Drop for DepthGuard {
        fn drop(&mut self) {
            HANDLER_DEPTH.with(|d| d.set(d.get().saturating_sub(1)));
        }
    }
    let depth = HANDLER_DEPTH.with(|d| {
        let v = d.get();
        d.set(v + 1);
        v
    });
    let _dg = DepthGuard;
    tracing::trace!(depth, "plugin:// handler depth");
    if depth >= MAX_HANDLER_DEPTH {
        tracing::warn!(depth, "plugin:// handler max depth exceeded");
        return finish_with_timing(err_response(429, b"too many nested requests"), started);
    }

    // Method + URI validation (extracted to a pure testable function)
    let method = request.method().as_str().to_string();
    if let Err(status) = validate_request(&method, request.uri()) {
        let body: &[u8] = match status {
            405 => b"method not allowed",
            _ => b"bad request",
        };
        return finish_with_timing(err_response(status, body), started);
    }

    let uri = request.uri();
    let plugin_id = uri.host().unwrap_or("").to_string();
    let path = uri.path();

    if plugin_id.is_empty() {
        return finish_with_timing(err_response(400, b"missing plugin id"), started);
    }

    // C06(2026-04-21): per-plugin rate-limiting is applied PRE-QUEUE
    // in `lib.rs` (before the job enters the threadpool queue). Here we do NOT
    // consume a token to avoid double-counting the same legitimate request.
    // Callers invoking `plugin_protocol_handler` directly (tests,
    // future integrations) must apply `rate_limit_ok_for` beforehand if they
    // want the equivalent defense.

    // C64 + F075: allocate path_safe with 200-char truncation to prevent
    // log DoS (arbitrary path can be very long). Only at DEBUG level to
    // save CPU in prod.
    let sanitize = |p: &str| -> String {
        p.chars()
            .filter(|c| !c.is_control() && *c != '\x1b')
            .take(200)
            .collect()
    };
    if tracing::enabled!(tracing::Level::DEBUG) {
        tracing::debug!(plugin_id = %plugin_id, path = %sanitize(path), "plugin:// request");
    }

    // Path resolution via pure function `resolve_plugin_path` (testable).
    let plugins_root = plugin_root(app);
    let canon_file = match resolve_plugin_path(&plugins_root, &plugin_id, path) {
        Ok(p) => p,
        Err(status) => {
            tracing::warn!(
                plugin_id = %plugin_id,
                path = %sanitize(path),
                status = status,
                "plugin:// denied"
            );
            let body: &[u8] = match status {
                400 => b"bad request",
                403 => b"forbidden",
                404 => b"not found",
                413 => b"payload too large",
                _ => b"error",
            };
            return finish_with_timing(err_response(status, body), started);
        }
    };

    // C52(2026-04-21): HEAD request fast path — no I/O to read body.
    // Integrity is still verified because a HEAD returning 200 for a plugin with
    // violated integrity would be an existence oracle without integrity. Cost: full
    // verify, but no read of the requested file to fill the body.
    if method == "HEAD" {
        if let Err(status) = verify_plugin_integrity(&plugin_id, &plugins_root) {
            tracing::warn!(
                plugin_id = %plugin_id,
                path = %sanitize(path),
                status = status,
                "plugin:// HEAD integrity check failed"
            );
            return finish_with_timing(err_response(status, b"integrity check failed"), started);
        }
        let size = std::fs::metadata(&canon_file).map(|m| m.len()).unwrap_or(0);
        return finish_with_timing(build_head_response(&canon_file, size), started);
    }

    // B5 Sprint 0.18 (2026-04-21): GET — verify + load in ONE atomic
    // snapshot. `verify_and_load_plugin_asset` opens all plugin fds BEFORE
    // any read, reads from the fds (Unix: inode alive against external rename/unlink),
    // hashes from the in-memory snapshot and returns the bytes of the requested
    // file FROM THE SAME snapshot.
    //
    // Eliminates the TOCTOU verify→serve window from the previous pattern
    // (separate verify + File::open + read_to_end), exploitable with a 70.5% hit-rate.
    //
    // We compute `requested_rel_path` as the relative path of `canon_file`
    // with respect to `plugin_dir` (plugins_root/plugin_id/). `resolve_plugin_path`
    // has already validated canonicalize + size + path traversal.
    let plugin_dir = plugins_root.join(&plugin_id);
    let requested_rel_path = match canon_file.strip_prefix(&plugin_dir) {
        Ok(rel) => rel.to_string_lossy().replace('\\', "/"),
        Err(_) => {
            tracing::error!(
                plugin_id = %plugin_id,
                "canon_file not under plugin_dir — resolve_plugin_path invariant broken"
            );
            return finish_with_timing(err_response(500, b"internal error"), started);
        }
    };

    let bytes = match verify_and_load_plugin_asset(&plugin_id, &plugins_root, &requested_rel_path) {
        Ok(b) => b,
        Err(status) => {
            tracing::warn!(
                plugin_id = %plugin_id,
                path = %sanitize(path),
                status = status,
                "plugin:// verify_and_load failed"
            );
            let body: &[u8] = match status {
                403 => b"integrity check failed",
                404 => b"not found",
                413 => b"payload too large",
                _ => b"error",
            };
            return finish_with_timing(err_response(status, body), started);
        }
    };

    let response = build_plugin_response(&canon_file, bytes);
    finish_with_timing(response, started)
}

/// Common response builder — defensive headers shared between GET and HEAD.
/// C51(2026-04-21): adds Permissions-Policy, Referrer-Policy,
/// X-Frame-Options, COOP (defense in depth against XSS/clickjacking/cross-origin).
fn apply_common_headers(
    builder: tauri::http::response::Builder,
    content_type: &'static str,
) -> tauri::http::response::Builder {
    builder
        .header("Content-Type", content_type)
        // ACL null for sandboxed iframes
        .header("Access-Control-Allow-Origin", "null")
        // Hot-reload dev — WKWebView caches aggressively
        .header("Cache-Control", "no-cache, must-revalidate")
        .header("X-Content-Type-Options", "nosniff")
        // Plugin document's own CSP. S04 F008 (no unsafe-inline) + F037 (media-src).
        .header(
            "Content-Security-Policy",
            "default-src 'self' plugin:; \
            script-src 'self' plugin:; \
            style-src 'self' plugin:; \
            img-src 'self' plugin: data:; \
            font-src 'self' plugin: data:; \
            media-src 'self' plugin: blob:; \
            connect-src 'none'; \
            frame-ancestors 'self'",
        )
        // C51 — modern headers
        .header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), usb=(), serial=(), payment=()",
        )
        .header("Referrer-Policy", "no-referrer")
        .header("X-Frame-Options", "SAMEORIGIN")
        .header("Cross-Origin-Opener-Policy", "same-origin")
}

fn build_plugin_response(canon_file: &Path, bytes: Vec<u8>) -> Response<Vec<u8>> {
    let ct = content_type_for(&canon_file.to_string_lossy());
    apply_common_headers(Response::builder().status(200), ct)
        .body(bytes.clone())
        .unwrap_or_else(|_| Response::new(bytes))
}

/// C52: HEAD response — same headers as GET + Content-Length
/// from metadata, empty body. Standard compliance HTTP RFC 9110 §9.3.2.
fn build_head_response(canon_file: &Path, size: u64) -> Response<Vec<u8>> {
    let ct = content_type_for(&canon_file.to_string_lossy());
    apply_common_headers(Response::builder().status(200), ct)
        .header("Content-Length", size)
        .body(Vec::new())
        .unwrap_or_else(|_| Response::new(Vec::new()))
}

// ─── Queue infra (B3 + F7-RT1) ───────────────────────────────────────────────

/// B3 Sprint 0.18 (2026-04-21) — atomic pre-queue job counter.
///
/// Security review (B3): the old pattern was:
/// ```ignore
/// if handler_pool().queued_count() > MAX_QUEUED {
///     return ... 503;
/// }
/// handler_pool().execute(move || { ... });
/// ```
/// `queued_count()` (poll) and `execute()` (enqueue) are NOT atomic. If N concurrent
/// threads all see `queued_count == 250` (< MAX_QUEUED=256), all enqueue →
/// queue 250+N, exceeding the limit. `threadpool` uses `mpsc::channel()`
/// without a bound; there is no secondary backstop.
///
/// Fix: `PENDING_COUNT.fetch_add(1, AcqRel)` returns the PRE-increment value. If
/// it is `>= MAX_QUEUED`, we decrement immediately and reject 503. A RAII
/// `PendingGuard` inside the worker closure decrements on Drop (covers panic too).
/// This way the queue is TRULY bounded.
pub(crate) static PENDING_COUNT: std::sync::atomic::AtomicUsize =
    std::sync::atomic::AtomicUsize::new(0);

/// B3 Sprint 0.18 F7-RT1 fix (2026-04-22) — RAII guard that decrements
/// `PENDING_COUNT` on `Drop`. Covers panic with `panic = "unwind"` (debug);
/// with `panic = "abort"` (release) Drop does not run but the whole process
/// crashes — acceptable, counter is redundant at that point.
///
/// **Only acquirable via `try_acquire_pending_slot()`** — the constructor is
/// private to prevent callers from creating guards without having incremented the counter.
pub(crate) struct PendingGuard {
    _marker: (),
}

impl Drop for PendingGuard {
    fn drop(&mut self) {
        PENDING_COUNT.fetch_sub(1, std::sync::atomic::Ordering::AcqRel);
    }
}

/// B3 + F7-RT1 fix (2026-04-22) — atomic helper that tries to acquire a queue slot.
/// **Only route** to increment `PENDING_COUNT` in production code and tests;
/// prevents tests from replicating the CAS pattern in their own body.
///
/// Returns `Some(PendingGuard)` if a slot was acquired (< MAX_QUEUED); the
/// guard decrements the counter on Drop. Returns `None` if the queue was
/// full — the caller must respond with 503.
#[must_use]
pub(crate) fn try_acquire_pending_slot() -> Option<PendingGuard> {
    let current = PENDING_COUNT.fetch_add(1, std::sync::atomic::Ordering::AcqRel);
    if current >= MAX_QUEUED {
        PENDING_COUNT.fetch_sub(1, std::sync::atomic::Ordering::AcqRel);
        None
    } else {
        Some(PendingGuard { _marker: () })
    }
}

// ─── Tests (B3 queue bound) ───────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    #[allow(unused_imports)]
    use super::*;
    // Only consumed by the release-only test below.
    #[cfg(not(debug_assertions))]
    use std::sync::atomic::{AtomicUsize, Ordering};

    // B3 Sprint 0.18 (2026-04-21) — queue bound atomic CAS.
    // Verifies that try_acquire_pending_slot is bounded by MAX_QUEUED under N concurrent threads.
    // Mutation: if someone reverts to the `queued_count + execute` pattern
    // without PENDING_COUNT, admitted_n would exceed MAX_QUEUED and the test would fail.
    #[cfg(not(debug_assertions))]
    #[test]
    fn b3_queue_bound_atomic_race() {
        use std::sync::{Arc, Barrier};
        use std::thread;
        PENDING_COUNT.store(0, Ordering::Release);

        let n = MAX_QUEUED + 100;
        let admitted = Arc::new(AtomicUsize::new(0));
        let rejected = Arc::new(AtomicUsize::new(0));

        let start_gate = Arc::new(Barrier::new(n));
        let hold_gate = Arc::new(Barrier::new(n + 1));

        let mut handles = Vec::with_capacity(n);
        for _ in 0..n {
            let a = admitted.clone();
            let r = rejected.clone();
            let sg = start_gate.clone();
            let hg = hold_gate.clone();
            handles.push(thread::spawn(move || {
                sg.wait();
                match try_acquire_pending_slot() {
                    Some(guard) => {
                        a.fetch_add(1, Ordering::Relaxed);
                        hg.wait();
                        drop(guard);
                    }
                    None => {
                        r.fetch_add(1, Ordering::Relaxed);
                        hg.wait();
                    }
                }
            }));
        }

        hold_gate.wait();
        let admitted_peak = PENDING_COUNT.load(Ordering::Acquire);
        assert!(
            admitted_peak <= MAX_QUEUED,
            "CAS bound violated: PENDING_COUNT peak={admitted_peak} > MAX_QUEUED={MAX_QUEUED}"
        );

        for h in handles {
            h.join().unwrap();
        }

        let admitted_n = admitted.load(Ordering::Relaxed);
        let rejected_n = rejected.load(Ordering::Relaxed);

        assert_eq!(
            admitted_n + rejected_n,
            n,
            "thread accounting leak: admitted={admitted_n} rejected={rejected_n} n={n}"
        );
        assert_eq!(
            PENDING_COUNT.load(Ordering::Relaxed),
            0,
            "PENDING_COUNT leak: final value != 0"
        );
        assert!(
            admitted_n <= MAX_QUEUED,
            "admitted_n={admitted_n} > MAX_QUEUED={MAX_QUEUED} (CAS bound broken)"
        );
        let expected_min_rejects = n - MAX_QUEUED;
        assert!(
            rejected_n >= expected_min_rejects,
            "CAS bound violat: rejected={rejected_n} < expected_min={expected_min_rejects}"
        );
    }
}
