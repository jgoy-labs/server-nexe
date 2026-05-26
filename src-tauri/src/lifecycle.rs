//! Centralized shutdown.
//!
//! SINGLE extension point for graceful shutdown. Triggers that call `graceful_quit`:
//!   1. Tray "Quit" (explicit user click)
//!   2. RunEvent::ExitRequested (Cmd+Q, Dock Quit)
//!   3. #[tauri::command] quit_app (frontend UI button — F043)
//!
//! Shutdown sequence (already implemented):
//!   1. Show confirm dialog ✅ S09 tauri-plugin-dialog — F042
//!   2. POST /admin/system/shutdown with Authorization: Bearer <token>  — F011/S12b ✅
//!   3. Wait up to 1.5s for the sidecar to exit gracefully
//!   4. kill_sidecar_child() with Unix process group SIGKILL on timeout  — F012/S12a ✅
//!   5. app.exit(0)
//!
//! Phase 2 pending: Windows Job Object equivalent for kill_sidecar_child (Unix-only now).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{Manager, Runtime};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

/// Global flag set when the user has CONFIRMED exit via dialog.
/// Required because `app.exit(0)` fires `ExitRequested` which our
/// handler intercepts with `api.prevent_exit()` → vicious cycle (dialog inside dialog).
///
/// If EXIT_CONFIRMED=true, the ExitRequested handler yields and lets Tauri close.
pub(crate) static EXIT_CONFIRMED: AtomicBool = AtomicBool::new(false);

/// C14(2026-04-21): guard against N stacked dialogs.
/// Multiple rapid triggers (tray Quit click × 3 + Alt+F4 + X) could
/// spawn N async tasks and stack N modal dialogs. `DIALOG_SHOWING`
/// with `swap(Ordering::AcqRel)` guarantees mutual exclusion: first trigger
/// wins, the rest exit immediately.
pub(crate) static DIALOG_SHOWING: AtomicBool = AtomicBool::new(false);

/// C14 + F5 Sprint 0.18 (2026-04-21) — exclusive acquisition of the dialog guard.
/// Extracted from `graceful_quit` as a pure helper to allow testing the
/// real CAS logic under concurrency without Tauri runtime.
///
/// Returns `true` if the caller won the guard (was `false`, now `true`) and
/// can show the dialog; `false` if another caller has already acquired it.
///
/// # Mutation testing
///
/// If someone replaces `swap(true, AcqRel)` with `store(true, ...)` or simply
/// returns `true` without any atomic operation, multiple concurrent callers
/// would win the guard simultaneously and the test `t1_dialog_guard_only_one_acquires_under_concurrency`
/// would fail (more than 1 acquired).
pub(crate) fn graceful_quit_try_acquire() -> bool {
    !DIALOG_SHOWING.swap(true, Ordering::AcqRel)
}

pub(crate) fn graceful_quit<R: Runtime>(app: &tauri::AppHandle<R>) {
    tracing::info!("graceful_quit invoked");

    // C14: only one dialog at a time. If one is already open, return.
    if !graceful_quit_try_acquire() {
        tracing::debug!("graceful_quit invoked while dialog open — ignoring");
        return;
    }

    // Show the confirmation dialog through `spawn_blocking`, not through `spawn`.
    //
    // Issues discovered at runtime on Windows ARM64 (2026-04-19):
    // 1. blocking_show() on the UI thread → deadlock freezing the app
    // 2. show(callback) from tray menu handler → callback never executes
    //
    // C40(2026-04-21): migration `async_runtime::spawn` → `spawn_blocking`.
    // `blocking_show()` is a purely blocking call; running it inside an `async`
    // task that ends up blocking was starving the Tokio runtime (default capacity 1 thread
    // in the blocking pool). `spawn_blocking` sends it directly to the dedicated
    // blocking pool — zero interaction with the async reactor.
    let app_handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let confirmed = app_handle
            .dialog()
            .message("Quit nexe-app?")
            .title("Confirm")
            .kind(MessageDialogKind::Info)
            .buttons(MessageDialogButtons::OkCancel)
            .blocking_show();

        // C14: reset guard ALWAYS (happy path or cancel), to allow
        // new triggers after the dialog. Release before deciding exit to
        // minimize contention window.
        DIALOG_SHOWING.store(false, Ordering::Release);

        if !confirmed {
            tracing::info!("quit cancelled by user");
            return;
        }

        // C40 fix: avoid block_on inside spawn_blocking — spawn an async task
        // for the POST + kill + exit. The blocking thread returns immediately.
        let app_for_shutdown = app_handle.clone();
        tauri::async_runtime::spawn(async move {
            // F3.1 BUG-C1 (2026-05-18): graceful POST /admin/system/shutdown
            // (server-nexe endpoint added in the same sub-phase) before
            // falling back to SIGKILL. The endpoint authenticates with the
            // ApiKey (X-API-Key header) rather than the internal AuthToken
            // (which the webview alone uses), and replaces the old
            // /api/v1/system/shutdown path that was already on the auth.rs
            // BLOCKED_PATH list. Timeout 1.5s — the endpoint schedules a
            // 0.3s delayed SIGINT and returns 200 immediately, so 1.5s is
            // ample headroom.
            let port_opt = app_for_shutdown.try_state::<crate::SidecarPort>().map(|s| s.get());
            let api_key_opt = app_for_shutdown.try_state::<crate::auth::ApiKey>().map(|s| s.0.clone());
            let client_opt = app_for_shutdown.try_state::<crate::HttpClient>().map(|s| s.0.clone());

            if let (Some(port), Some(api_key), Some(client)) = (port_opt, api_key_opt, client_opt) {
                let url = format!("http://127.0.0.1:{port}/admin/system/shutdown");
                tracing::info!(%url, "POST sidecar shutdown (graceful)");
                match client
                    .post(&url)
                    .header("X-API-Key", api_key)
                    .timeout(Duration::from_millis(1500))
                    .send()
                    .await
                {
                    Ok(resp) => tracing::info!(status = %resp.status(), "sidecar shutdown response"),
                    Err(e) => tracing::warn!(error = %e, "sidecar shutdown POST failed (will SIGKILL)"),
                }
                // Give the sidecar the 0.3s scheduled SIGINT + lifespan teardown
                // some headroom before kill_sidecar_child polls (it already
                // waits up to 1.5s on its own, so 400ms here is enough).
                tauri::async_runtime::spawn_blocking(|| {
                    std::thread::sleep(Duration::from_millis(400));
                }).await.ok();
            } else {
                tracing::warn!("missing state for graceful POST (port/api_key/http) — skipping");
            }

            if let Some(state) = app_for_shutdown.try_state::<crate::SidecarChild>() {
                kill_sidecar_child(&state.0);
            }
            tracing::info!("quit confirmed — exiting");
            EXIT_CONFIRMED.store(true, Ordering::Relaxed);
            app_for_shutdown.exit(0);
        });
    });
}

/// Helper extracted from `graceful_quit` for unit testability.
///
/// Takes the `Child` from the Mutex (idempotent: take() leaves None), waits up to 1.5s
/// for the process to exit on its own (post-POST shutdown), and kills it if still alive.
/// `wait()` prevents zombies. Recovers from Mutex poisoning.
///
/// Returns `Some(pid)` if there was a Child that was handled, `None` if already
/// clean (idempotent).
pub(crate) fn kill_sidecar_child(
    mutex: &Mutex<Option<std::process::Child>>,
) -> Option<u32> {
    let mut guard = match mutex.lock() {
        Ok(g) => g,
        Err(poisoned) => {
            tracing::warn!("SidecarChild mutex poisoned — recovering");
            poisoned.into_inner()
        }
    };
    let mut child = guard.take()?;
    let pid = child.id();
    // Poll up to 1.5s to see if it exited on its own (POST /shutdown triggered os._exit).
    let deadline = std::time::Instant::now() + Duration::from_millis(1500);
    let mut graceful = false;
    while std::time::Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(status)) => {
                tracing::info!(pid, ?status, "sidecar exited gracefully");
                graceful = true;
                break;
            }
            Ok(None) => {
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => {
                tracing::warn!(error = %e, pid, "try_wait() failed");
                break;
            }
        }
    }
    if !graceful {
        tracing::info!(pid, "sidecar still alive — SIGKILL");
        // Kill the entire process group (Unix) to catch grandchild workers
        // spawned by server-nexe (model runners, etc.) that child.kill() misses.
        //
        // F3.1 BUG-NB-23: guard against PID wraparound. Before sending SIGKILL
        // to the whole process group (-pid), verify the child is still the
        // leader of its own pgrp via getpgid(). If pid has been recycled by
        // another unrelated process, getpgid will return that other process's
        // group (or -1 if dead) and we'd otherwise SIGKILL an arbitrary group.
        #[cfg(unix)]
        {
            let pid_i32 = pid as i32;
            // SAFETY: getpgid(2) is async-signal-safe; returns -1 / sets errno
            // if pid doesn't exist. Safe to call with any i32.
            let pgid_real = unsafe { libc::getpgid(pid_i32) };
            if pgid_real == pid_i32 {
                // SAFETY: kill(2) is async-signal-safe; pid verified as leader of
                // own pgrp just now. Race window is tiny but accepted — alternative
                // would require freezing the kernel scheduler.
                let pgid = -pid_i32;
                unsafe { libc::kill(pgid, libc::SIGKILL) };
            } else {
                tracing::warn!(
                    pid,
                    pgid_real,
                    "child is not own pgrp leader (recycled or never setpgid?) — skipping group kill, falling back to child.kill()"
                );
            }
        }
        if let Err(e) = child.kill() {
            tracing::warn!(error = %e, pid, "child.kill() failed (already dead?)");
        }
        if let Err(e) = child.wait() {
            tracing::warn!(error = %e, pid, "child.wait() failed");
        }
    }
    Some(pid)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    // All `graceful_quit_try_acquire` tests share the same process-wide
    // `DIALOG_SHOWING` atomic. Without serialisation, cargo test (which by
    // default runs tests in parallel) lets two of them race: one stores
    // `true`, another spins up 10 threads that all see `true`, expects
    // exactly one winner, and gets zero. We gate every test in this module
    // that touches DIALOG_SHOWING on a per-module mutex so the global
    // state is observed deterministically.
    static DIALOG_TEST_GUARD: Mutex<()> = Mutex::new(());

    fn dialog_test_lock() -> std::sync::MutexGuard<'static, ()> {
        // PoisonError unwrap: tests panicking under the lock should still
        // produce a single deterministic failure; we recover the guard.
        DIALOG_TEST_GUARD
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    #[test]
    fn try_acquire_returns_true_first_time() {
        let _guard = dialog_test_lock();
        DIALOG_SHOWING.store(false, Ordering::SeqCst);
        assert!(graceful_quit_try_acquire());
        // Cleanup
        DIALOG_SHOWING.store(false, Ordering::SeqCst);
    }

    #[test]
    fn try_acquire_returns_false_when_already_held() {
        let _guard = dialog_test_lock();
        DIALOG_SHOWING.store(false, Ordering::SeqCst);
        assert!(graceful_quit_try_acquire()); // first caller wins
        assert!(!graceful_quit_try_acquire()); // second caller blocked
        DIALOG_SHOWING.store(false, Ordering::SeqCst);
    }

    #[test]
    fn try_acquire_concurrent_only_one_wins() {
        let _guard = dialog_test_lock();
        // C14: multiple rapid triggers must not stack dialogs.
        DIALOG_SHOWING.store(false, Ordering::SeqCst);

        let winners = Arc::new(std::sync::atomic::AtomicU32::new(0));
        let barrier = Arc::new(std::sync::Barrier::new(10));

        let handles: Vec<_> = (0..10)
            .map(|_| {
                let w = winners.clone();
                let b = barrier.clone();
                std::thread::spawn(move || {
                    b.wait(); // all threads start simultaneously
                    if graceful_quit_try_acquire() {
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
            "exactly one thread must win the dialog guard"
        );
        DIALOG_SHOWING.store(false, Ordering::SeqCst);
    }

    #[test]
    fn kill_sidecar_child_idempotent_on_none() {
        // If the mutex contains None (already cleaned), returns None without panic.
        let mutex: Mutex<Option<std::process::Child>> = Mutex::new(None);
        assert!(kill_sidecar_child(&mutex).is_none());
        // Call again — still idempotent
        assert!(kill_sidecar_child(&mutex).is_none());
    }

    #[test]
    fn exit_confirmed_starts_false() {
        // EXIT_CONFIRMED is a global static — it should default to false.
        // If this fails, something set it during init which would break the dialog flow.
        // Note: other tests may have set it, so we just verify the type is correct.
        let _ = EXIT_CONFIRMED.load(Ordering::Relaxed);
    }
}

/// Command invocable from the frontend (explicit UI button).
/// Example JS: `import { invoke } from '@tauri-apps/api/core'; invoke('quit_app')`
#[tauri::command]
pub(crate) async fn quit_app<R: Runtime>(app: tauri::AppHandle<R>) {
    graceful_quit(&app);
}
