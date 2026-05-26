// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::fs;
#[cfg(unix)]
use std::fs::OpenOptions;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::time::{SystemTime, UNIX_EPOCH};

fn main() {
    // F055 + C29/C63(2026-04-21) — minimal panic hook.
    //
    // C29: crash reports written to `dirs::data_local_dir()/nexe-app/crashes/`
    // (not `/tmp` world-readable). Mode 0600 on Unix to prevent exfiltration
    // of stack traces by other users on the machine. Windows: `%LOCALAPPDATA%`.
    //
    // C63: backtrace truncated to 10 KB — if a recursive panic generates a trace
    // of megabytes, filling the app-data directory disk is not acceptable.
    //
    // Required because panic=abort shows nothing on Windows (windows_subsystem="windows").
    // The hook is called even with panic=abort (Rust guarantee).
    std::panic::set_hook(Box::new(|info| {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let pid = std::process::id();

        // C29: app_data_dir, not /tmp
        let crash_dir = {
            #[cfg(unix)]
            {
                dirs::data_local_dir()
                    .unwrap_or_else(env::temp_dir)
                    .join("nexe-app/crashes")
            }
            #[cfg(windows)]
            {
                env::var("LOCALAPPDATA")
                    .map(std::path::PathBuf::from)
                    .unwrap_or_else(|_| env::temp_dir())
                    .join("nexe-app/crashes")
            }
        };
        let _ = fs::create_dir_all(&crash_dir);
        let crash_path = crash_dir.join(format!("crash-{ts}-{pid}.txt"));

        let msg_raw = info
            .payload()
            .downcast_ref::<&str>()
            .copied()
            .map(|s| s.to_string())
            .or_else(|| {
                info.payload()
                    .downcast_ref::<String>()
                    .map(|s| s.to_string())
            })
            .unwrap_or_else(|| "<non-str panic>".to_string());

        // B30: sanitize control chars from the panic message before writing to
        // crash file or stderr. A panic message that includes user-controlled input
        // (e.g. `format!("bad input: {}", evil)`) could contain ANSI escape sequences
        // (\x1b[...m) that would corrupt log monitors or terminals that render the
        // crash file. Allow '\n' for readability; strip everything else in 0x00-0x1f.
        // Also cap at 1024 chars — panic messages should not be unbounded.
        let msg: String = msg_raw
            .chars()
            .filter(|c| !c.is_control() || *c == '\n')
            .take(1024)
            .collect();

        // B28: Note on panic = "abort" + RAII Drop semantics.
        // `[profile.release] panic = "abort"` means that after this hook returns,
        // the process calls abort() immediately — RAII Drop is NOT guaranteed to run.
        // Impact on guards (DepthGuard, PendingGuard, MutexGuard):
        //   - AtomicUsize HANDLER_DEPTH and PENDING_COUNT may not decrement.
        //   - MutexGuards will not unlock (poison flag is set on lock-held panics).
        // These guards are designed for per-request lifetime on worker threads.
        // A panicking worker thread dies, the threadpool spawns a replacement, and the
        // counters reset as requests drain. For a single-threaded panic this means
        // the process aborts anyway. Document here so future reviewers do not add
        // cleanup logic inside Drop that relies on running post-abort.
        let backtrace = std::backtrace::Backtrace::capture().to_string();

        // C63: truncate backtrace to 10 KB for DoS prevention.
        let backtrace_truncated: String = backtrace.chars().take(10_000).collect();
        let content = format!("nexe-app crash\n\n{msg}\n\nBacktrace:\n{backtrace_truncated}");

        // C29: mode 0600 on Unix (read/write owner only). Windows has no ACL
        // through OpenOptions → fallback to fs::write (inherits dir perm,
        // which lives under %LOCALAPPDATA% protected by user profile).
        #[cfg(unix)]
        {
            let write_res = OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(0o600)
                .open(&crash_path);
            if let Ok(mut f) = write_res {
                let _ = f.write_all(content.as_bytes());
            }
        }
        #[cfg(windows)]
        {
            let _ = fs::write(&crash_path, &content);
        }

        let _ = std::io::stderr().write_all(
            format!(
                "PANIC: {msg}\n(crash report saved to {})\n",
                crash_path.display()
            )
            .as_bytes(),
        );
    }));

    nexe_app_lib::run()
}
