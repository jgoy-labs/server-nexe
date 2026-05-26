//! nexe-app library crate — Tauri v2 desktop shell. Phase 1. CSP fix.
//!
//! Entry point and Builder setup. The logic lives in modules:
//! - [`auth`] — session token UUID v4 + fetch_from_sidecar Bearer proxy
//! - [`catalog`] — F5.3 model catalog Tauri command (remote + embedded fallback)
//! - [`handler`] — plugin:// URI scheme handler + threadpool + reentrancy + queue infra
//! - [`hardware`] — F5.3 hardware detection Tauri command (RAM, OS, disk)
//! - [`integrity`] — SHA-256 plugin integrity, re-hash per-request (C01) + LRU observability
//! - [`lifecycle`] — graceful_quit + quit_app command
//! - [`onboarding_cmd`] — F5.3 first-run detection + completion flag commands
//! - [`rate_limit`] — token bucket per-plugin + LRU cap
//! - [`sidecar`] — state types (SidecarPort/HttpClient/SidecarChild) + path resolvers
//! - [`validate`] — plugin_id + request + path traversal

pub mod auth;
pub mod catalog;
pub mod handler;
pub mod hardware;
pub mod integrity;
pub mod lifecycle;
pub(crate) mod logging;
pub mod onboarding_cmd;
pub mod rate_limit;
pub mod sidecar;
pub mod validate;

// F5.3: re-export command functions under their short names so
// generate_handler! registers them as "get_hardware" etc. (matching
// the isolation.js allowlist and frontend invoke() calls).
use catalog::fetch_catalog;
use hardware::get_hardware;
use onboarding_cmd::{check_first_run, check_partial_install, mark_onboarding_complete, reset_installation};

/// Open an external http/https URL in the system default browser.
///
/// Tauri v2 blocks `target="_blank"` and `window.open()` for external URLs
/// by default. This command calls the OS handler (`open` on macOS, `xdg-open`
/// on Linux) so the system browser receives the URL instead of the webview.
///
/// Only `https://` and `http://` schemes are accepted — all others are
/// silently rejected to prevent scheme-injection attacks.
#[tauri::command]
fn open_external_url(url: String) {
    if !url.starts_with("https://") && !url.starts_with("http://") {
        tracing::warn!(url, "open_external_url: rejected non-http scheme");
        return;
    }
    #[cfg(target_os = "macos")]
    { let _ = std::process::Command::new("open").arg(&url).spawn(); }
    #[cfg(target_os = "linux")]
    { let _ = std::process::Command::new("xdg-open").arg(&url).spawn(); }
    tracing::info!(url, "open_external_url: dispatched to system browser");
}

// Public re-exports for external API and lifecycle/auth compatibility
// (`crate::SidecarPort`, `crate::HttpClient`, `crate::SidecarChild` still work).
pub use auth::{ApiKey, AuthToken};
pub use integrity::compute_plugin_hash;
pub use sidecar::{HttpClient, SidecarChild, SidecarPort};

// Internal re-exports to facilitate use from `mod tests` in lib.rs.
#[cfg(test)]
pub(crate) use handler::{
    content_type_for, finish_with_timing, HANDLER_DEPTH, MAX_HANDLER_DEPTH,
};
#[cfg(test)]
#[allow(unused_imports)]
pub(crate) use integrity::{verified_plugins, verify_plugin_integrity};
#[cfg(test)]
pub(crate) use lifecycle::{graceful_quit_try_acquire, DIALOG_SHOWING};
#[cfg(test)]
pub(crate) use rate_limit::{rate_limiters, RATE_LIMIT_LRU_CAP};
#[cfg(test)]
pub(crate) use validate::{resolve_plugin_path, validate_plugin_id};

use crate::auth::fetch_from_sidecar;
use crate::handler::{
    err_response, extract_plugin_id_from_uri, handler_pool, plugin_protocol_handler,
    try_acquire_pending_slot, MAX_QUEUED, PENDING_COUNT,
};
use crate::lifecycle::{graceful_quit, quit_app, EXIT_CONFIRMED};
use crate::rate_limit::rate_limit_ok_for;
use crate::sidecar::{
    reserve_ephemeral_port, resolve_sidecar_path, restart_try_acquire, verify_port_free,
    RestartGuard, SidecarLogPath, SpawnContext,
};
use crate::validate::validate_request;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};
#[cfg(unix)]
use std::os::unix::process::CommandExt as _;
use std::sync::atomic::Ordering;
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, UriSchemeContext, WindowEvent,
};

// example #[tauri::command] — end-to-end Rust ↔ JS pattern.
// Called from `src/api/commands.js` via `invoke("greet", { name })`.
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {name}! Greeted from Rust.")
}

/// Returns the dynamic sidecar port assigned at startup (or after restart).
/// Frontend uses this to build sidecar URLs instead of a hardcoded constant.
///
/// F5.3.1: lock-free read via `SidecarPort::get` — the underlying `AtomicU16`
/// can be updated by `restart_sidecar` without disturbing concurrent readers.
#[tauri::command]
fn get_sidecar_port(port_state: tauri::State<'_, SidecarPort>) -> u16 {
    port_state.get()
}

/// Spawn the sidecar process with auth token via stdin (F004 R1 fix).
///
/// N1: NEXE_SIDECAR=1 signals server-nexe to NOT kill processes on port conflict.
/// N3: token is UUID v4 session key, not JWT. Written to stdin to avoid
/// /proc/<pid>/environ leak.
fn spawn_sidecar_process(
    sidecar_path: &Path,
    auth_token: &str,
    port: u16,
    sidecar_data_dir: Option<&std::path::Path>,
    api_key: &str,
    stdout_log_path: Option<&std::path::Path>,
) -> Result<std::process::Child, String> {
    // Assegurar subcarpetes sidecar_data_dir existents abans
    // del spawn (logs, data, cache, vectors) — runner.py les espera (BUG-R1-1).
    if let Some(dir) = sidecar_data_dir {
        for sub in &["logs", "data", "cache", "vectors"] {
            let p = dir.join(sub);
            if !p.exists() {
                std::fs::create_dir_all(&p).ok();
            }
        }
    }

    // macOS app bundles launch with a minimal PATH that omits /usr/local/bin
    // and /opt/homebrew/bin, so shutil.which("ollama") fails inside the sidecar
    // even when Ollama is installed. Prepend the standard tool locations so
    // Python can resolve externally-installed binaries (Ollama, ffmpeg, etc.).
    let base_path = std::env::var("PATH").unwrap_or_default();
    let augmented_path = format!("/usr/local/bin:/opt/homebrew/bin:/opt/local/bin:{base_path}");

    let mut cmd = Command::new(sidecar_path);
    cmd.env("PATH", augmented_path)
        .env("NEXE_PORT", port.to_string())
        .env("NEXE_SERVER_PORT", port.to_string())   // BUG-C2: server-nexe alias
        .env("NEXE_HOST", "127.0.0.1")
        .env("NEXE_SIDECAR", "1")
        .env("NEXE_ENV", "production")               // BUG-NB-1: força production
        .env("NEXE_AUTO_INGEST_KNOWLEDGE", "1")
        .env("NEXE_PRIMARY_API_KEY", api_key)        // B1: nom correcte (era NEXE_API_KEY)
        .env("NEXE_TRAY_PID", std::process::id().to_string())   // B3: evita doble tray + watchdog
        .env("NEXE_PARENT_PID", std::process::id().to_string()) // BUG-NC-19: watchdog parent
        .env(
            "NEXE_APPROVED_MODULES",
            "security,memory,rag,embeddings,mlx_module,llama_cpp_module,ollama_module,web_ui_module",
        )
        // BUG-NC-1 + F5.5: web_ui_module enabled to expose /ui/* JSON endpoints
        // (info/backends/sessions/chat). HTML/static routes skipped in sidecar
        // mode by routes.py conditional; Tauri webview serves its own UI.
        // Net env contamination
        .env_remove("NEXE_AUTH_TOKEN")
        .env_remove("NEXE_DEV_MODE")
        .env_remove("NEXE_DEV_MODE_ALLOW_REMOTE")
        .env_remove("PYTHONPATH")
        .env_remove("VIRTUAL_ENV")
        .env_remove("DYLD_LIBRARY_PATH")
        .env_remove("DYLD_FALLBACK_LIBRARY_PATH")
        // Linux portability (FL-L1, 2026-05-22): equivalents Linux del scrub
        // DYLD_* macOS. Si l'usuari té LD_LIBRARY_PATH/LD_PRELOAD/LD_AUDIT al
        // shell que llança l'AppImage, el sidecar Python heretaria injecció
        // de .so arbitràries (vector classic per hooking glibc). Defensiu
        // cross-platform: env_remove és no-op si la var no està set, sense
        // cost a macOS.
        .env_remove("LD_LIBRARY_PATH")
        .env_remove("LD_PRELOAD")
        .env_remove("LD_AUDIT")
        // Tray logs viewer step: capture all sidecar output — including
        // pre-logger crashes (import error, `.so` blocked by Gatekeeper,
        // segfault). Without this, in a production `.app` stdout/stderr go
        // nowhere, and a sidecar dying at the first instant leaves the
        // frontend hung on retry-poll of `/health/ready` with no trace on
        // disk. Observed on the laptop 2026-05-18 (~320s retry-poll, no logs).
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::piped());
    if let Some(log_path) = stdout_log_path {
        // Simple rotation — if the previous log exceeds 10 MB, archive it as
        // `.old`. Avoids unbounded growth across runs without external help.
        if let Ok(meta) = std::fs::metadata(log_path) {
            if meta.len() > 10 * 1024 * 1024 {
                let old = log_path.with_extension("log.old");
                let _ = std::fs::rename(log_path, &old);
            }
        }
        match std::fs::OpenOptions::new().create(true).append(true).open(log_path) {
            Ok(stdout_file) => match stdout_file.try_clone() {
                Ok(stderr_file) => {
                    cmd.stdout(Stdio::from(stdout_file));
                    cmd.stderr(Stdio::from(stderr_file));
                    tracing::info!(path = %log_path.display(), "sidecar stdout/stderr captured to file");
                }
                Err(e) => {
                    tracing::warn!(error = %e, "sidecar log try_clone failed — stderr inherits");
                    cmd.stdout(Stdio::from(stdout_file));
                }
            },
            Err(e) => {
                tracing::warn!(path = %log_path.display(), error = %e, "sidecar log open failed — stdout inherits");
            }
        }
    }
    if let Some(dir) = sidecar_data_dir {
        cmd.env("NEXE_SIDECAR_DIR", dir);
        cmd.env("NEXE_HOME", dir.join("app").to_string_lossy().to_string());        // S1
        cmd.env("NEXE_LOGS_DIR", dir.join("logs").to_string_lossy().to_string());   // BUG-NX-6/NC-4
        cmd.env("NEXE_DATA_DIR", dir.join("data").to_string_lossy().to_string());   // BUG-NX-6
        cmd.env("NEXE_CACHE_DIR", dir.join("cache").to_string_lossy().to_string());
        cmd.env("NEXE_QDRANT_PATH", dir.join("vectors").to_string_lossy().to_string());
        // F5.5 — pin cwd to sidecar app dir. Sense això, el child Python hereta
        // el cwd del Tauri parent (que en producció pot ser qualsevol carpeta
        // segons com s'arrenqui l'app). El `_find_initial_config` del module
        // manager fa `validate_safe_path(config_path, Path.cwd())` i si el cwd
        // és arbitrari, rebutja el path productiu i cau en un fallback que
        // resol mòduls amb paths absoluts erroniant tot el plugin loading.
        // Pinning cwd = NEXE_HOME garanteix paths estables.
        cmd.current_dir(dir.join("app"));
    }
    // F5.6 BUG-NEW-6 — propagate user models dir if ~/models/ exists.
    // mlx_module and llama_cpp_module call get_models_dir() which honours
    // NEXE_STORAGE_PATH first, then NEXE_DATA_DIR/models, then cwd fallback.
    // Without this propagation, a fresh install has no models in the bundle
    // storage and the dropdowns are empty until the user manually copies or
    // symlinks them.
    if let Some(home) = dirs::home_dir() {
        let user_models = home.join("models");
        if user_models.exists() && user_models.is_dir() {
            cmd.env(
                "NEXE_STORAGE_PATH",
                user_models.to_string_lossy().to_string(),
            );
        }
    }
    // F5.6 Bloc 8 — Disable hf_xet COMPLETELY at sidecar spawn. HF Hub
    // environment variables are read at huggingface_hub import time
    // (documented at https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables);
    // setting them post-import inside the worker thread (the old Bloc 1
    // attempt) is silently ignored. The Rust spawn is the only place we
    // can set them BEFORE Python imports HF, so it is.
    //
    // Why disable rather than enable HIGH_PERFORMANCE: the previous F5.4
    // Fase 6d strategy (HIGH_PERFORMANCE for RAM >= 32 GB) caused stalled
    // downloads of model.safetensors on Mac Studio M4 / 128 GB (empíric
    // 2026-05-20). hf_xet deadlocks silently mid-transfer; configs and
    // tokenizers download via httpx fine, but the big safetensors file
    // hangs at 0%. Same family of issues as upstream #800 (GCP) and #446
    // (Windows). Verificat empíricament.
    //
    // Performance trade-off: httpx fallback ~50-100 MB/s vs xet teòric
    // ~200 MB/s — for a 2.5 GB model that's 25-50 s vs 12-25 s. Acceptable
    // for onboarding UX (< 5 min objective) and the only reliable path
    // until hf_xet's macOS ARM64 transfer engine stabilises.
    cmd.env("HF_HUB_DISABLE_XET", "1");
    tracing::info!("hf_xet disabled at sidecar spawn (HF_HUB_DISABLE_XET=1)");
    #[cfg(unix)]
    cmd.process_group(0);
    let mut child = cmd.spawn().map_err(|e| {
        tracing::error!(error = %e, "sidecar spawn failed");
        format!("sidecar spawn: {e}")
    })?;
    if let Some(mut stdin) = child.stdin.take() {
        if let Err(e) = stdin.write_all(format!("{auth_token}\n").as_bytes()) {
            tracing::warn!(error = %e, "sidecar stdin write_all failed");
        }
        drop(stdin);
    }
    Ok(child)
}

/// Poll sidecar health endpoint and navigate to web UI when ready.
///
/// Post-F5.5 revert: the sidecar serves the full UI again, so we navigate
/// the webview directly to `http://127.0.0.1:{port}/?nexe_api_key={key}`.
/// app.js reads the query param on first load, persists it to the sidecar-
/// origin localStorage, and scrubs the URL via `history.replaceState`.
async fn poll_sidecar_health(
    app_handle: tauri::AppHandle,
    port: u16,
    auth_token: String,
    api_key: String,
    client: reqwest::Client,
) {
    // Endpoint real exposat per server-nexe (system.py:246). El previ
    // `/api/v1/system/health` no existia → fallback timeout 30s al primer
    // arrencament.
    let health_url = format!("http://127.0.0.1:{port}/admin/system/health");
    let bearer = format!("Bearer {auth_token}");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut elapsed = 0u32;
    loop {
        if std::time::Instant::now() > deadline {
            tracing::warn!("splash: sidecar health timeout after 30s — navigating anyway");
            break;
        }
        match client
            .get(&health_url)
            .header("Authorization", &bearer)
            .timeout(std::time::Duration::from_millis(500))
            .send()
            .await
        {
            Ok(r) if r.status().is_success() => {
                tracing::info!(port, elapsed_s = elapsed / 2, "splash: sidecar ready");
                break;
            }
            _ => {
                tauri::async_runtime::spawn_blocking(|| {
                    std::thread::sleep(std::time::Duration::from_millis(500));
                })
                .await
                .ok();
                elapsed += 1;
            }
        }
    }
    // F5.3: if this is a first-run session the onboarding wizard is visible and
    // will navigate to the main UI itself (the api_key arrives via the
    // /installer/finalize response, no separate Tauri command needed).
    // Skip auto-navigation so the health-poll does not clobber the wizard mid-flow.
    let first_run = !crate::onboarding_cmd::flag_path(&app_handle).exists();
    if first_run {
        tracing::info!(port, "sidecar ready (first-run) — deferring navigation to onboarding wizard");
        return;
    }

    if let Some(w) = app_handle.get_webview_window("main") {
        // F5.5 revert (2026-05-21): navigate straight to the sidecar HTTP
        // origin. The previous tauri://localhost/ui/index.html target loaded
        // a stale local copy that drifted from the canonical plugin UI; now
        // the sidecar serves the canonical HTML with all server-side
        // substitutions applied (NEXE_VERSION, data-nexe-lang).
        //
        // localStorage handoff: tauri://localhost (splash) and
        // http://127.0.0.1:{port} (UI) are different origins, so the splash's
        // localStorage isn't visible here. We pass the api_key in the query
        // string; app.js reads it on first load, persists it into the
        // sidecar-origin localStorage, and scrubs the query param via
        // history.replaceState. UUIDv4 keys ([0-9a-f-]) are safe in URLs;
        // url-encoding guards against future format changes.
        let encoded_key = percent_encoding::utf8_percent_encode(
            &api_key,
            percent_encoding::NON_ALPHANUMERIC,
        )
        .to_string();
        // The canonical UI is mounted under the `/ui/` prefix by the
        // web_ui_module router (routes.py:106 `APIRouter(prefix="/ui")`).
        // Hitting `/` returns the framework JSON identity payload — which
        // the webview would render as plain text — so always target /ui/.
        let ui_url = format!("http://127.0.0.1:{port}/ui/?nexe_api_key={encoded_key}");
        if let Ok(url) = ui_url.parse() {
            let _ = w.navigate(url);
        } else {
            tracing::warn!(port, "splash: failed to parse sidecar UI URL");
        }
    }
}

/// Obre un fitxer o carpeta amb l'aplicació associada del sistema operatiu.
///
/// macOS: `open <path>` — for `.log` files, macOS launches Console.app by
/// default (integrated auto-tail), matching the original Python tray
/// behaviour (`installer/tray.py:540`). For folders, Finder is used.
fn open_in_system(path: &Path) -> std::io::Result<()> {
    #[cfg(target_os = "macos")]
    let cmd = "open";
    #[cfg(target_os = "linux")]
    let cmd = "xdg-open";
    #[cfg(target_os = "windows")]
    let cmd = "explorer";
    std::process::Command::new(cmd).arg(path).spawn().map(|_| ())
}

/// F5.3.1 — kill the running sidecar, spawn a fresh one on a new ephemeral
/// port, wait for it to become healthy, and emit `sidecar-restarted` with the
/// new port. Returns the new port number to the caller (the onboarding
/// wizard's step 5) so it can navigate the webview accordingly.
///
/// Concurrency: protected by `RESTART_IN_PROGRESS` — a second invocation while
/// one is already in flight returns `Err("RESTART_IN_PROGRESS")` immediately.
///
/// Sequence (2026-05-19):
///   1. Acquire restart guard (atomic swap).
///   2. Kill current sidecar via `kill_sidecar_child` (POST shutdown + grace + SIGKILL).
///   3. Reserve a fresh ephemeral port.
///   4. Spawn the new sidecar with the same context (paths, tokens).
///   5. Update `SidecarChild` and `SidecarPort` state atomically.
///   6. Poll `/admin/system/health` up to 30s until 2xx.
///   7. Emit `sidecar-restarted` Tauri event ONLY after the health probe passes.
#[tauri::command]
async fn restart_sidecar(app: tauri::AppHandle) -> Result<u16, String> {
    use tauri::{Emitter, Manager};

    if !restart_try_acquire() {
        tracing::warn!("restart_sidecar invoked while a restart is already in progress");
        return Err("RESTART_IN_PROGRESS".to_string());
    }
    let _guard = RestartGuard;

    // ── 1. Look up the state the restart needs ────────────────────────────────
    let child_state = app
        .try_state::<SidecarChild>()
        .ok_or_else(|| "SidecarChild state missing".to_string())?;
    let port_state = app
        .try_state::<SidecarPort>()
        .ok_or_else(|| "SidecarPort state missing".to_string())?;
    let spawn_ctx = app
        .try_state::<SpawnContext>()
        .ok_or_else(|| "SpawnContext state missing".to_string())?;
    let auth_token = app
        .try_state::<AuthToken>()
        .ok_or_else(|| "AuthToken state missing".to_string())?
        .0
        .clone();
    let api_key = app
        .try_state::<ApiKey>()
        .ok_or_else(|| "ApiKey state missing".to_string())?
        .0
        .clone();
    let http_client = app
        .try_state::<HttpClient>()
        .ok_or_else(|| "HttpClient state missing".to_string())?
        .0
        .clone();

    let old_port = port_state.get();
    tracing::info!(old_port, "restart_sidecar: killing current sidecar");

    // ── 2. Graceful kill (POST /shutdown + grace + SIGKILL of pgrp) ──────────
    // `kill_sidecar_child` already implements the full graceful sequence; the
    // returned PID (if any) is purely informational here.
    let _killed_pid = crate::lifecycle::kill_sidecar_child(&child_state.0);

    // ── 3. Reserve a fresh ephemeral port ─────────────────────────────────────
    let new_port =
        reserve_ephemeral_port().map_err(|e| format!("restart_sidecar reserve port: {e}"))?;
    verify_port_free(new_port)
        .map_err(|e| format!("restart_sidecar verify port {new_port}: {e}"))?;
    tracing::info!(new_port, "restart_sidecar: spawning fresh sidecar");

    // ── 4. Spawn (blocking call — wrap in spawn_blocking for the async cmd) ──
    let sidecar_path = spawn_ctx.sidecar_path.clone();
    let sidecar_data_dir = spawn_ctx.sidecar_data_dir.clone();
    let stdout_log_path = spawn_ctx.stdout_log_path.clone();
    let auth_token_for_spawn = auth_token.clone();
    let api_key_for_spawn = api_key.clone();
    let spawn_result = tauri::async_runtime::spawn_blocking(move || {
        spawn_sidecar_process(
            &sidecar_path,
            &auth_token_for_spawn,
            new_port,
            sidecar_data_dir.as_deref(),
            &api_key_for_spawn,
            stdout_log_path.as_deref(),
        )
    })
    .await
    .map_err(|e| format!("restart_sidecar spawn task join: {e}"))?;
    let child = spawn_result.map_err(|e| format!("restart_sidecar spawn: {e}"))?;
    let new_pid = child.id();

    // ── 5. Atomic state update — child first (under Mutex), then port ─────────
    {
        let mut guard = child_state
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        *guard = Some(child);
    }
    port_state.set(new_port);
    tracing::info!(new_pid, new_port, "restart_sidecar: new sidecar registered");

    // ── 6. Health poll (30s max, 500ms interval) ──────────────────────────────
    let health_url = format!("http://127.0.0.1:{new_port}/admin/system/health");
    let bearer = format!("Bearer {auth_token}");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut healthy = false;
    while std::time::Instant::now() < deadline {
        match http_client
            .get(&health_url)
            .header("Authorization", &bearer)
            .timeout(std::time::Duration::from_millis(500))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                healthy = true;
                break;
            }
            _ => {
                // Pattern aligned with `poll_sidecar_health` for consistency;
                // tokio is not a direct dependency. The blocking pool overhead
                // is acceptable (60 iter max, 500ms each = bounded).
                tauri::async_runtime::spawn_blocking(|| {
                    std::thread::sleep(std::time::Duration::from_millis(500));
                })
                .await
                .ok();
            }
        }
    }
    if !healthy {
        // F5.5 G12: revert port to the old value. The new sidecar is dead and
        // the old one was already killed, so neither is serving. Reverting
        // gives the frontend a clear "connection refused" on old_port rather
        // than a silent hang on new_port that has no listener.
        port_state.set(old_port);
        tracing::warn!(
            old_port,
            new_port,
            "restart_sidecar: new sidecar unhealthy — reverting port_state to old_port"
        );
        return Err("restart_sidecar: new sidecar did not become healthy within 30s".to_string());
    }
    tracing::info!(new_port, "restart_sidecar: new sidecar healthy");

    // ── 7. Emit event AFTER health passes so the frontend never targets a port
    //      that is still booting. ──────────────────────────────────────────────
    let _ = app.emit("sidecar-restarted", new_port);

    Ok(new_port)
}

fn setup_services(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    app.manage(AuthToken::generate());
    app.manage(ApiKey::generate());
    tracing::info!("auth token + api key generated (uuid v4, 128 bits entropy each)");

    let sidecar_path = resolve_sidecar_path(app.handle()).map_err(|e| {
        tracing::error!(error = %e, "could not resolve the sidecar path");
        e
    })?;
    let auth_token = app.state::<AuthToken>().0.clone();
    let api_key = app.state::<ApiKey>().0.clone();

    let sidecar_port = reserve_ephemeral_port().map_err(|e| {
        tracing::error!(error = %e, "could not reserve ephemeral port");
        e
    })?;
    verify_port_free(sidecar_port).map_err(|e| {
        tracing::error!(error = %e, port = sidecar_port, "port taken before spawn");
        e
    })?;
    tracing::info!(sidecar = %sidecar_path.display(), port = sidecar_port, "spawning sidecar");

    // Dev: target/sidecar/ is used directly (launcher finds venv via $(dirname $0)).
    // Release: extract sidecar-bundle.tar.gz to app_data_dir/sidecar/ and pass the
    // path via NEXE_SIDECAR_DIR so the launcher finds venv/ and app/ there.
    #[cfg(debug_assertions)]
    let sidecar_data_dir: Option<std::path::PathBuf> = None;
    #[cfg(not(debug_assertions))]
    let sidecar_data_dir: Option<std::path::PathBuf> = Some(
        crate::sidecar::ensure_sidecar_extracted(app.handle()).map_err(|e| {
            tracing::error!(error = %e, "sidecar bundle extraction failed");
            e
        })?,
    );

    // Pas 0: si tenim sidecar_data_dir (release), capturem stdout/stderr a
    // <data_dir>/logs/sidecar-stdout.log perquè el tray pugui obrir-lo amb
    // Console.app (macOS associa `.log` per defecte) i veure pre-logger crashes.
    let sidecar_stdout_log: Option<std::path::PathBuf> = sidecar_data_dir
        .as_ref()
        .map(|d| d.join("logs").join("sidecar-stdout.log"));

    let child = spawn_sidecar_process(
        &sidecar_path,
        &auth_token,
        sidecar_port,
        sidecar_data_dir.as_deref(),
        &api_key,
        sidecar_stdout_log.as_deref(),
    )?;
    let pid = child.id();
    app.manage(SidecarChild(Mutex::new(Some(child))));
    app.manage(SidecarPort::new(sidecar_port));
    // F5.3.1: persist the spawn context so `restart_sidecar` can re-invoke
    // `spawn_sidecar_process` with the same paths the initial setup used.
    app.manage(SpawnContext {
        sidecar_path: sidecar_path.clone(),
        sidecar_data_dir: sidecar_data_dir.clone(),
        stdout_log_path: sidecar_stdout_log.clone(),
    });
    if let Some(path) = sidecar_stdout_log {
        app.manage(SidecarLogPath(path));
    }
    tracing::info!(pid, port = sidecar_port, "sidecar spawned");

    // F3.1 BUG-NA-1 (SSRF): disable HTTP redirects on the shared reqwest client.
    // The webview proxies requests through this client to the local sidecar; an
    // attacker that controls a sidecar response (e.g. via a malicious plugin)
    // could otherwise redirect the bearer token to an arbitrary host. Local-only
    // traffic has no legitimate need for cross-host redirects.
    let http_client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|e| {
            tracing::error!(error = %e, "reqwest::Client::builder failed");
            format!("reqwest builder: {e}")
        })?;
    let health_client = http_client.clone();
    app.manage(HttpClient(http_client));
    tracing::info!("shared reqwest::Client registered (timeout 30s)");

    let app_handle = app.handle().clone();
    tauri::async_runtime::spawn(poll_sidecar_health(
        app_handle, sidecar_port, auth_token, api_key, health_client,
    ));

    Ok(())
}

/// Builds the tray menu and registers event handlers.
/// Extracted from run() (Dev Session 2026-05-08) to reduce CCN of the root function.
fn build_tray_menu(app: &mut tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show nexe-app", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "Hide nexe-app", true, None::<&str>)?;
    let sep_logs = PredefinedMenuItem::separator(app)?;
    // Pas 0 (tray logs viewer) — recupera el comportament del Python tray original
    // (installer/tray.py:540 _open_logs) que obria el server.log amb Console.app.
    let open_log = MenuItem::with_id(app, "open_sidecar_log", "Open sidecar log", true, None::<&str>)?;
    let open_logs_dir = MenuItem::with_id(app, "open_logs_folder", "Open logs folder", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let uninstall = MenuItem::with_id(app, "uninstall", "Uninstall…", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &hide, &sep_logs, &open_log, &open_logs_dir, &separator, &uninstall, &quit])?;

    let tray_icon = tauri::include_image!("icons/tray.png");
    TrayIconBuilder::with_id("main")
        .menu(&menu)
        .tooltip("nexe-app")
        .icon(tray_icon)
        .icon_as_template(false)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "hide" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            "open_sidecar_log" => {
                // macOS: `open <file.log>` → Console.app per defecte (auto-tail).
                // Linux/Windows: file manager o associated viewer.
                if let Some(state) = app.try_state::<SidecarLogPath>() {
                    let path = state.0.clone();
                    if !path.exists() {
                        // Fall back to the directory if the log has not been
                        // generated yet (sidecar never started or crashed at
                        // the first instant without writing).
                        if let Some(parent) = path.parent() {
                            let _ = open_in_system(parent);
                        }
                    } else {
                        let _ = open_in_system(&path);
                    }
                } else {
                    tracing::warn!("open_sidecar_log: SidecarLogPath state not registered (dev mode?)");
                }
            }
            "open_logs_folder" => {
                if let Some(state) = app.try_state::<SidecarLogPath>() {
                    if let Some(parent) = state.0.parent() {
                        let _ = open_in_system(parent);
                    }
                }
            }
            "uninstall" => {
                tracing::info!("uninstall from tray");
                let app = app.clone();
                tauri::async_runtime::spawn_blocking(move || {
                    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
                    let confirmed = app
                        .dialog()
                        .message("This will remove all data, downloaded models, and settings. You can reinstall by opening the app again.\n\nAixò esborrarà totes les dades, models descarregats i configuració. Pots reinstal·lar obrint l'app de nou.")
                        .title("Uninstall nexe-app?")
                        .kind(MessageDialogKind::Warning)
                        .buttons(MessageDialogButtons::OkCancel)
                        .blocking_show();
                    if confirmed {
                        crate::onboarding_cmd::full_uninstall(&app);
                        tracing::info!("uninstall complete — exiting");
                        app.exit(0);
                    }
                });
            }
            "quit" => {
                // S05 F009/F041: tray Quit → centralized graceful_quit.
                // IMPORTANT: show main window BEFORE the dialog.
                // Without a visible window, the MessageDialog has no parent and
                // does not render in Windows WebView2 (silent fail runtime bug 2026-04-19).
                tracing::info!("quit from tray");
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                graceful_quit(app);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // ADR-0017 (2026-04-22) — single logger pipeline. `logging::init()` configures
    // `tracing-subscriber` with stdout + file rolling daily layers
    // (`data_local_dir()/com.nexe.app/logs/`). No direct `log::set_logger` here:
    // `tracing-subscriber` with the default `tracing-log` feature installs
    // a global `LogTracer` automatically, redirecting `log::*` (internal tauri,
    // third-party deps) → `tracing::*`. Replaces `tauri-plugin-log` (bug #2
    // real Phase 0 — `SetLoggerError` conflict documented in the runtime broken
    // report 2026-04-22).
    crate::logging::init();

    tauri::Builder::default()
        // S09 F019 — single-instance FIRST (prerequisite for other plugins that may be sensitive
        // to multi-launch). When the user opens a second instance, show the existing window.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            tracing::info!("second instance launch — focusing existing window");
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        // S09 F019 — dialog (ask/confirm/message/open/save). Unlocks F042 (S05).
        .plugin(tauri_plugin_dialog::init())
        // ADR-0017 (2026-04-22): `tauri-plugin-log` removed. Unified logging
        // via `tracing-subscriber` + `tracing-appender` (rolling daily file at
        // `data_local_dir()/com.nexe.app/logs/`). Initialized by
        // `logging::init()` above, before the Builder.
        //
        // B9 Sprint 0.18 (2026-04-21): `tauri_plugin_store` +
        // `tauri_plugin_notification` already removed in that sprint.
        //
        // F3.1 BUG-NA-6 (2026-05-18): tauri-plugin-deep-link removed. The plugin
        // exposed an unsanitised `nexe://` URL handler that a hostile web page
        // could weaponise (the OAuth callback hook was never wired). If we
        // need OS-level deep links again we will reintroduce them with a
        // sanitised handler from scratch, not the default plugin.
        // S03 F004 + C06 (2026-04-21): async handler via bounded threadpool
        // (8 workers) with pre-queue validation + rate-limit + bounded
        // queue. Reject fraudulent requests before enqueuing → DoS protection.
        .register_asynchronous_uri_scheme_protocol(
            "plugin",
            |ctx: UriSchemeContext<'_, _>, request, responder| {
                let app = ctx.app_handle().clone();

                // C06:   PRE-QUEUE validation + rate-limit + bounded.
                // Without this, rate-limit was applied INSIDE the worker (too late);
                // a pre-filter flood could fill the threadpool mpsc queue
                // without bound → OOM before any 429 is processed.
                let method = request.method().as_str().to_string();
                let uri_str = request.uri().to_string();

                if let Err(status) = validate_request(&method, request.uri()) {
                    responder.respond(err_response(status, b"bad request"));
                    return;
                }
                let plugin_id = match extract_plugin_id_from_uri(&uri_str) {
                    Some(id) => id,
                    None => {
                        responder.respond(err_response(400, b"invalid plugin path"));
                        return;
                    }
                };
                if !rate_limit_ok_for(&plugin_id) {
                    responder.respond(err_response(429, b"too many requests"));
                    return;
                }

                // B3 Sprint 0.18 F7-RT1 refactor (2026-04-22): the CAS logic
                // lives in `try_acquire_pending_slot()` so the B3 test can call
                // the SAME helper as the production code (no replication in test).
                // If it returns `None`, queue full → 503. If it returns `Some(guard)`,
                // the guard lives until Drop at the end of the worker closure (RAII decrement
                // including panic, unwind mode; in abort release mode the whole process
                // crashes and the counter is irrelevant).
                let guard = match try_acquire_pending_slot() {
                    Some(g) => g,
                    None => {
                        tracing::warn!(
                            pending = PENDING_COUNT.load(Ordering::Acquire),
                            max = MAX_QUEUED,
                            "plugin:// queue full — rejecting 503"
                        );
                        responder.respond(err_response(503, b"service unavailable (queue full)"));
                        return;
                    }
                };

                handler_pool().execute(move || {
                    // The guard lives throughout the worker's work. On Drop
                    // (natural end or panic unwind) decrements PENDING_COUNT.
                    let _guard = guard;

                    let response = plugin_protocol_handler(&app, request);
                    responder.respond(response);
                });
            },
        )
        .setup(|app| {
            setup_services(app)?;
            build_tray_menu(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Unification 2026-04-19 (Jordi): X, Alt+F4, tray Quit all show
            // the same "are you sure?" dialog. X no longer does silent hide.
            // To hide without closing, use the "Hide" option in the tray menu.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                graceful_quit(window.app_handle());
            }
        })
        // S05 F043 + security C25: registered commands.
        // Security C25 (2026-04-21): `fetch_from_sidecar` injects the Bearer token
        // on the Rust side (never exposed to the main webview). `get_auth_token` removed
        // security audit: exposed the raw token via XSS.
        .invoke_handler(tauri::generate_handler![
            greet,
            quit_app,
            fetch_from_sidecar,
            get_sidecar_port,
            // F5.3 onboarding commands — short names match isolation.js allowlist + frontend invoke()
            get_hardware,
            fetch_catalog,
            check_first_run,
            mark_onboarding_complete,
            // partial install detection + reset (Step 1 banner)
            check_partial_install,
            reset_installation,
            // open external URLs in system browser (target="_blank" workaround)
            open_external_url,
            // F5.3.1 — restart sidecar to pick up post-wizard onboarding state.
            restart_sidecar
        ])
        // F049: unwrap_or_else — clear message + exit(1) without panic
        .build(tauri::generate_context!())
        .unwrap_or_else(|e| {
            eprintln!("[nexe-app] fatal: failed to build app: {e}");
            std::process::exit(1);
        })
        .run(|_app_handle, event| {
            // S05 F009: ExitRequested → centralized graceful_quit.
            // CRITICAL: api.prevent_exit() prevents Tauri from executing app.exit(0) automatically
            // while we wait for the user in the confirmation dialog. Only graceful_quit
            // (via dialog callback) decides if we really exit.
            //
            // EXIT_CONFIRMED flag: when graceful_quit callback has confirmed exit and
            // calls app.exit(0), Tauri fires ExitRequested again. To avoid
            // vicious cycle (dialog inside dialog) we let it pass without prevent_exit.
            if let tauri::RunEvent::ExitRequested { api, .. } = &event {
                if EXIT_CONFIRMED.load(Ordering::Relaxed) {
                    tracing::info!("ExitRequested post-confirm — letting Tauri exit");
                    return;
                }
                tracing::info!("ExitRequested — prevent_exit + graceful_quit");
                api.prevent_exit();
                graceful_quit(_app_handle);
            }

            // macOS dock reopen — restores hidden window on dock click
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen {
                has_visible_windows,
                ..
            } = &event
            {
                if !has_visible_windows {
                    if let Some(w) = _app_handle.get_webview_window("main") {
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                }
            }
        });
}

// unit tests for the resolver (no Tauri runtime needed)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::handler::handler_pool;
    use std::fs;
    use std::io::Read;
    use std::path::{Path, PathBuf};

    fn mktemp_root(test_name: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!(
            "nexe-app-test-{}-{}",
            test_name,
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn mk_plugin(root: &Path, id: &str, file_rel: &str, content: &str) {
        let ui = root.join(id).join("ui");
        fs::create_dir_all(&ui).unwrap();
        let file = ui.join(file_rel);
        if let Some(parent) = file.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(&file, content).unwrap();
    }

    // F002 and F003 tests (resolve_sidecar_path_* and kill_sidecar_child) have
    // been moved to `sidecar.rs` (mod tests) — Dev Session 2026-05-08.

    // F3.1 BUG-9/NA-4/NB-26 escape_js_string defensive coverage was removed
    // with the F5.5 revert: the api_key now travels as a URL query param
    // (percent-encoded), not as an inlined JS string literal, so the helper
    // is no longer wired into any production path. If a webview script-
    // injection path returns, re-introduce the helper together with the full
    // test suite.

    #[test]
    fn content_type_html() {
        assert_eq!(content_type_for("index.html"), "text/html; charset=utf-8");
    }

    #[test]
    fn content_type_css() {
        assert_eq!(content_type_for("style.css"), "text/css; charset=utf-8");
    }

    #[test]
    fn content_type_js() {
        assert_eq!(
            content_type_for("app.js"),
            "application/javascript; charset=utf-8"
        );
    }

    #[test]
    fn content_type_unknown_fallback() {
        assert_eq!(content_type_for("file.xyz"), "application/octet-stream");
    }

    // new formats
    #[test]
    fn content_type_webp() {
        assert_eq!(content_type_for("logo.webp"), "image/webp");
    }

    #[test]
    fn content_type_woff2() {
        assert_eq!(content_type_for("font.woff2"), "font/woff2");
    }

    #[test]
    fn content_type_wasm() {
        assert_eq!(content_type_for("mod.wasm"), "application/wasm");
    }

    #[test]
    fn content_type_case_insensitive() {
        // MIME sniffing vuln: .HTML must not fall back to octet-stream
        assert_eq!(content_type_for("INDEX.HTML"), "text/html; charset=utf-8");
    }

    // validate_plugin_id
    #[test]
    fn plugin_id_valid_alphanumeric() {
        assert!(validate_plugin_id("rag"));
        assert!(validate_plugin_id("my-plugin"));
        assert!(validate_plugin_id("plugin_123"));
        assert!(validate_plugin_id("a1"));
    }

    #[test]
    fn plugin_id_rejects_path_traversal() {
        assert!(!validate_plugin_id("../etc/passwd"));
        assert!(!validate_plugin_id(".."));
        assert!(!validate_plugin_id("plug/in"));
    }

    #[test]
    fn plugin_id_rejects_special_chars() {
        assert!(!validate_plugin_id("<script>"));
        assert!(!validate_plugin_id("plug in"));
        assert!(!validate_plugin_id("plug.in"));
        assert!(!validate_plugin_id("plug:in"));
    }

    #[test]
    fn plugin_id_rejects_too_short_or_long() {
        assert!(!validate_plugin_id(""));
        assert!(!validate_plugin_id("a")); // 1 char, below minimum
        let long = "a".repeat(65);
        assert!(!validate_plugin_id(&long));
        let max = "a".repeat(64);
        assert!(validate_plugin_id(&max));
    }

    // S08 F058 — Windows reserved device names (cross-platform, no cfg)
    #[test]
    fn plugin_id_rejects_windows_reserved_names() {
        // DOS device names — Windows does not allow creating them as directories.
        assert!(!validate_plugin_id("con"));
        assert!(!validate_plugin_id("prn"));
        assert!(!validate_plugin_id("aux"));
        assert!(!validate_plugin_id("nul"));
        // COM1-9
        for n in 1..=9 {
            assert!(
                !validate_plugin_id(&format!("com{n}")),
                "com{n} must be reserved"
            );
            assert!(
                !validate_plugin_id(&format!("lpt{n}")),
                "lpt{n} must be reserved"
            );
        }
    }

    // S08 F058 — names that merely CONTAIN reserved names are still valid
    #[test]
    fn plugin_id_accepts_names_containing_reserved() {
        // "con" alone is reserved, but "con-plugin" or "my-con" are valid.
        assert!(validate_plugin_id("con-plugin"));
        assert!(validate_plugin_id("my-con"));
        assert!(validate_plugin_id("prn123"));
        assert!(validate_plugin_id("com10")); // > 9 is not reserved
        assert!(validate_plugin_id("com0")); // 0 is not reserved
        assert!(validate_plugin_id("lpt0"));
    }

    // S08 F057/F059/F060 — Windows-specific protections (CI Windows only).
    // In the current CI (macOS+Linux+Windows) these tests only run on Windows.
    #[cfg(windows)]
    #[test]
    fn unc_prefix_consistent_resolution() {
        // Windows UNC prefix `\\?\C:\...` — canonicalize may add the prefix.
        // We want to verify that starts_with comparison still works correctly.
        let root = mktemp_root("unc");
        mk_plugin(&root, "rag", "index.html", "<h1>ok</h1>");
        let res = resolve_plugin_path(&root, "rag", "/index.html");
        assert!(res.is_ok(), "resolve with UNC path failed: {:?}", res);
    }

    // S08 F060 — APFS/NTFS case-insensitive protection (validate_plugin_id already covers it
    // by rejecting uppercase, but we add an explicit test for Windows NTFS).
    #[cfg(windows)]
    #[test]
    fn ntfs_case_insensitive_protection() {
        // On Windows NTFS it is case-insensitive by default.
        // validate_plugin_id rejects uppercase, so `plugin://RAG/...` never reaches
        // resolve with "RAG". Cross-platform regression.
        assert!(!validate_plugin_id("RAG"));
        assert!(!validate_plugin_id("Rag"));
        let root = mktemp_root("ntfs_case");
        mk_plugin(&root, "rag", "index.html", "ok");
        // Attempting to open with uppercase id → 400 bad request (validate_plugin_id fail)
        assert_eq!(resolve_plugin_path(&root, "RAG", "/index.html"), Err(400));
    }

    // S08 F059 — MAX_PATH (260 chars) Windows must not panic or crash.
    // A path of >260 chars on Windows returns err from canonicalize → 404 or 400.
    #[cfg(windows)]
    #[test]
    fn max_path_windows_does_not_panic() {
        let root = mktemp_root("maxpath");
        // max plugin_id (64) + very long path
        let long_path = format!("/{}.html", "a".repeat(300));
        let res = resolve_plugin_path(&root, "plug", &long_path);
        // Must return Err (404 or 400), never panic
        assert!(
            res.is_err(),
            "very long path must return Err, not panic"
        );
    }

    // APFS case-insensitive cross-platform bug protection
    #[test]
    fn plugin_id_uppercase_rejected() {
        assert!(!validate_plugin_id("RAG"));
        assert!(!validate_plugin_id("Rag"));
        assert!(!validate_plugin_id("rAg"));
        assert!(!validate_plugin_id("Plugin-123"));
    }

    #[test]
    fn resolve_empty_plugin_id_rejects_400() {
        let root = mktemp_root("empty");
        assert_eq!(resolve_plugin_path(&root, "", "index.html"), Err(400));
    }

    #[test]
    fn resolve_invalid_plugin_id_rejects_400() {
        let root = mktemp_root("invalid_id");
        // disallowed character
        assert_eq!(resolve_plugin_path(&root, "a.b", "index.html"), Err(400));
        // traversal in the id
        assert_eq!(resolve_plugin_path(&root, "../etc", "passwd"), Err(400));
    }

    #[test]
    fn resolve_plugin_not_found_returns_404() {
        let root = mktemp_root("notfound");
        assert_eq!(
            resolve_plugin_path(&root, "inexistent", "index.html"),
            Err(404)
        );
    }

    #[test]
    fn resolve_valid_path_ok() {
        let root = mktemp_root("valid");
        mk_plugin(&root, "rag", "index.html", "<h1>ok</h1>");
        let res = resolve_plugin_path(&root, "rag", "/index.html");
        assert!(res.is_ok(), "expected Ok, got {:?}", res);
    }

    #[test]
    fn resolve_traversal_to_parent_rejected() {
        let root = mktemp_root("traversal");
        mk_plugin(&root, "rag", "index.html", "<h1>rag</h1>");
        // File outside the rag/ui scope
        let _ = fs::write(root.join("secret.txt"), "SECRET");
        // Attack: escape with ../../secret.txt (relative to rag/ui → goes up to plugins_root)
        let res = resolve_plugin_path(&root, "rag", "/../../secret.txt");
        assert!(res.is_err(), "traversal allowed: {:?}", res);
    }

    #[test]
    fn resolve_cross_plugin_rejected() {
        let root = mktemp_root("cross");
        mk_plugin(&root, "rag", "index.html", "<h1>rag</h1>");
        mk_plugin(&root, "altre", "secret.html", "SECRET");
        // From rag trying to read altre/ui/secret.html
        let res = resolve_plugin_path(&root, "rag", "/../../altre/ui/secret.html");
        assert!(res.is_err(), "cross-plugin access allowed: {:?}", res);
    }

    // percent-decoding of paths
    #[test]
    fn resolve_percent_encoded_path_ok() {
        let root = mktemp_root("percent");
        mk_plugin(&root, "rag", "my file.html", "ok");
        let res = resolve_plugin_path(&root, "rag", "/my%20file.html");
        assert!(res.is_ok(), "percent-encoded path failed: {:?}", res);
    }

    #[test]
    fn resolve_percent_encoded_unicode_ok() {
        let root = mktemp_root("percent_utf8");
        mk_plugin(&root, "rag", "fòto.png", "ok");
        // ò = U+00F2 = UTF-8 %C3%B2
        let res = resolve_plugin_path(&root, "rag", "/f%C3%B2to.png");
        assert!(res.is_ok(), "UTF-8 percent-encoded failed: {:?}", res);
    }

    // directory-as-file bug regression test
    #[test]
    fn resolve_directory_rejected() {
        let root = mktemp_root("dir_reject");
        mk_plugin(&root, "rag", "index.html", "ok");
        std::fs::create_dir_all(root.join("rag/ui/subdir")).unwrap();
        // Request to directory must be 404, not Ok
        assert_eq!(resolve_plugin_path(&root, "rag", "/subdir"), Err(404));
    }

    // symlink escape (Unix-only)
    #[cfg(unix)]
    #[test]
    fn resolve_symlink_escape_rejected() {
        use std::os::unix::fs::symlink;
        let root = mktemp_root("symlink_escape");
        mk_plugin(&root, "rag", "index.html", "ok");
        // Secret file outside the rag/ui/ scope
        std::fs::write(root.join("secret.txt"), "SECRET").unwrap();
        // Symlink INSIDE ui/ pointing OUTSIDE (to the secret)
        let _ = symlink(root.join("secret.txt"), root.join("rag/ui/evil.html"));
        let res = resolve_plugin_path(&root, "rag", "/evil.html");
        assert!(res.is_err(), "symlink escape allowed: {:?}", res);
    }

    // empty path and slash alone
    #[test]
    fn resolve_empty_path_is_directory_rejected() {
        let root = mktemp_root("empty_path");
        mk_plugin(&root, "rag", "index.html", "ok");
        // "" and "/" resolve to the ui/ directory → must be 404 (is_file check)
        assert_eq!(resolve_plugin_path(&root, "rag", ""), Err(404));
        assert_eq!(resolve_plugin_path(&root, "rag", "/"), Err(404));
    }

    // null byte in the path
    #[test]
    fn resolve_null_byte_path_rejected() {
        let root = mktemp_root("null_byte");
        mk_plugin(&root, "rag", "index.html", "ok");
        let res = resolve_plugin_path(&root, "rag", "/index.html\0evil");
        assert!(res.is_err(), "null byte allowed: {:?}", res);
    }

    // rate limiter resets per window
    #[test]
    fn rate_limit_per_plugin_allows_under_threshold() {
        // rate_limit_ok_for(plugin) returns true under limit.
        // We do not test exact rejection (shared global state).
        assert!(rate_limit_ok_for("test_a"));
        assert!(rate_limit_ok_for("test_a"));
    }

    #[test]
    fn rate_limit_per_plugin_isolated_between_plugins() {
        // Plugin A and plugin B have independent counters.
        for _ in 0..500 {
            let _ = rate_limit_ok_for("isolated_a");
        }
        // B starts at zero, must not be affected by A's consumption
        assert!(rate_limit_ok_for("isolated_b"));
    }

    // Sprint 0.14 #T9 — 4 new tests for validate_request
    #[test]
    fn validate_request_get_ok() {
        let uri: tauri::http::Uri = "plugin://rag/index.html".parse().unwrap();
        assert!(validate_request("GET", &uri).is_ok());
    }

    #[test]
    fn validate_request_head_ok() {
        let uri: tauri::http::Uri = "plugin://rag/index.html".parse().unwrap();
        assert!(validate_request("HEAD", &uri).is_ok());
    }

    #[test]
    fn validate_request_post_rejected_405() {
        let uri: tauri::http::Uri = "plugin://rag/index.html".parse().unwrap();
        assert_eq!(validate_request("POST", &uri), Err(405));
        assert_eq!(validate_request("OPTIONS", &uri), Err(405));
        assert_eq!(validate_request("PUT", &uri), Err(405));
        assert_eq!(validate_request("DELETE", &uri), Err(405));
    }

    // S04 F036: query strings are NOT rejected (JS frameworks use ?v=123 cache-bust).
    #[test]
    fn validate_request_accepts_query_string() {
        let uri: tauri::http::Uri = "plugin://rag/x.html?v=123".parse().unwrap();
        assert_eq!(validate_request("GET", &uri), Ok(()));
        let uri: tauri::http::Uri = "plugin://rag/x.html?screen=settings&id=42".parse().unwrap();
        assert_eq!(validate_request("GET", &uri), Ok(()));
    }

    // S04 F036: explicit port is still rejected (surface reduction).
    #[test]
    fn validate_request_rejects_explicit_port() {
        let uri: tauri::http::Uri = "plugin://rag:80/x.html".parse().unwrap();
        assert_eq!(validate_request("GET", &uri), Err(400));
    }

    // Large file regression — the resolver accepts, the handler rejects via cap
    #[test]
    fn resolve_accepts_large_file_but_handler_caps() {
        let root = mktemp_root("large");
        let ui = root.join("rag/ui");
        std::fs::create_dir_all(&ui).unwrap();
        // 11MB file → resolver ok, handler 413
        std::fs::write(ui.join("big.bin"), vec![0u8; 11 * 1024 * 1024]).unwrap();
        let res = resolve_plugin_path(&root, "rag", "/big.bin");
        assert!(res.is_ok(), "resolver must ok (size check is in handler)");
        let meta = std::fs::metadata(res.unwrap()).unwrap();
        assert!(meta.len() > 10 * 1024 * 1024, "file must be >10MB");
    }

    // Sprint 0.15 #4 — Plugin integrity tests (ADR-0014 active)

    fn mk_plugin_with_manifest(root: &Path, id: &str, hash: &str) {
        mk_plugin(root, id, "index.html", "hello");
        let manifest = format!(
            "[plugin]\nid = \"{}\"\nversion = \"0.1.0\"\n\n[integrity]\nsha256 = \"{}\"\n",
            id, hash
        );
        fs::write(root.join(id).join("manifest.toml"), manifest).unwrap();
    }

    #[test]
    fn compute_hash_deterministic() {
        let root = mktemp_root("hash_det");
        mk_plugin_with_manifest(&root, "rag", "placeholder");
        let h1 = compute_plugin_hash(&root.join("rag")).unwrap();
        let h2 = compute_plugin_hash(&root.join("rag")).unwrap();
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64, "sha256 hex = 64 chars");
    }

    #[test]
    fn compute_hash_ignores_integrity_section() {
        // The hash MUST NOT depend on the integrity.sha256 field (circularity).
        let root = mktemp_root("hash_canon");
        mk_plugin_with_manifest(&root, "rag", "aaaaaaaaaaaaaaaa");
        let h1 = compute_plugin_hash(&root.join("rag")).unwrap();
        mk_plugin_with_manifest(&root, "rag", "bbbbbbbbbbbbbbbb");
        let h2 = compute_plugin_hash(&root.join("rag")).unwrap();
        assert_eq!(h1, h2, "change to [integrity] must not affect the hash");
    }

    #[test]
    fn compute_hash_changes_when_content_changes() {
        let root = mktemp_root("hash_diff");
        mk_plugin_with_manifest(&root, "rag", "x");
        let h1 = compute_plugin_hash(&root.join("rag")).unwrap();
        // Modify one byte of the content
        fs::write(root.join("rag/ui/index.html"), "hello!").unwrap();
        let h2 = compute_plugin_hash(&root.join("rag")).unwrap();
        assert_ne!(h1, h2, "content change must change the hash");
    }

    #[test]
    fn verify_integrity_valid_passes() {
        let root = mktemp_root("verify_ok");
        mk_plugin_with_manifest(&root, "pluga", "placeholder");
        let actual = compute_plugin_hash(&root.join("pluga")).unwrap();
        mk_plugin_with_manifest(&root, "pluga", &actual);
        let res = verify_plugin_integrity("pluga", &root);
        assert!(res.is_ok(), "correct hash must pass: {:?}", res);
    }

    // The verify_plugin_integrity tests expecting Err(403) require STRICT_INTEGRITY=true
    // (release only). In debug, the function returns Ok(()) to avoid friction each-edit (F024).
    #[cfg(not(debug_assertions))]
    #[test]
    fn verify_integrity_mismatch_rejected() {
        let root = mktemp_root("verify_mismatch");
        // different plugin id to avoid cache collision with other tests
        mk_plugin_with_manifest(
            &root,
            "plugb",
            "0000000000000000000000000000000000000000000000000000000000000000",
        );
        let res = verify_plugin_integrity("plugb", &root);
        assert_eq!(res, Err(403), "incorrect hash must return 403");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn verify_integrity_no_manifest_rejected() {
        let root = mktemp_root("verify_nomanifest");
        mk_plugin(&root, "plugc", "index.html", "hello");
        // without manifest.toml
        let res = verify_plugin_integrity("plugc", &root);
        assert_eq!(res, Err(403), "plugin without manifest must fail");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn verify_integrity_empty_hash_rejected() {
        let root = mktemp_root("verify_emptyhash");
        mk_plugin_with_manifest(&root, "plugd", "");
        let res = verify_plugin_integrity("plugd", &root);
        assert_eq!(res, Err(403), "empty hash must fail");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn verify_integrity_short_hash_rejected() {
        let root = mktemp_root("verify_shorthash");
        mk_plugin_with_manifest(&root, "pluge", "abc123"); // < 64 chars
        let res = verify_plugin_integrity("pluge", &root);
        assert_eq!(res, Err(403), "hash with incorrect length must fail");
    }

    #[test]
    fn compute_hash_handles_subdirs() {
        let root = mktemp_root("hash_subdirs");
        mk_plugin(&root, "rag", "index.html", "root");
        mk_plugin(&root, "rag", "sub/nested.css", "body{}");
        let manifest = "[plugin]\nid = \"rag\"\n[integrity]\nsha256 = \"x\"\n";
        fs::write(root.join("rag/manifest.toml"), manifest).unwrap();
        let h = compute_plugin_hash(&root.join("rag")).unwrap();
        assert_eq!(h.len(), 64);
    }

    // S02 F003 — read-with-cap pattern (no TOCTOU metadata→read).
    // Validates that File::open + take(MAX+1) + read_to_end truncates to MAX+1 bytes
    // regardless of the actual file size.
    #[test]
    fn read_with_cap_truncates_at_limit_plus_one() {
        use std::io::Write;
        let root = mktemp_root("read_cap");
        fs::create_dir_all(&root).unwrap();
        let file_path = root.join("big.bin");
        let mut f = fs::File::create(&file_path).unwrap();
        // Writes 1MB + 100 bytes — larger than the test cap (1KB).
        let chunk = vec![0u8; 1024];
        for _ in 0..1024 {
            f.write_all(&chunk).unwrap();
        }
        f.write_all(&[0u8; 100]).unwrap();
        drop(f);

        const CAP: u64 = 1024;
        let open = fs::File::open(&file_path).unwrap();
        let mut buf = Vec::new();
        let n = open.take(CAP + 1).read_to_end(&mut buf).unwrap() as u64;
        assert_eq!(
            n,
            CAP + 1,
            "take(CAP+1) must read exactly CAP+1 bytes"
        );
        assert!(n > CAP, "handler detectaria oversize");
    }

    // C01 (2026-04-21) — TOCTOU edit in-place of an existing file
    // without mutating the parent directory's mtime. This is exactly the
    // vector the old algorithm (CacheEntry { mtime }) allowed:
    // APFS/NTFS/POSIX do NOT update dir mtime on in-place write, so
    // the cache hit kept serving the verified verdict. The fix
    // re-computes the hash on every request.
    //
    // Release-only: in debug STRICT_INTEGRITY=false and verify returns Ok(())
    // (F024 friction-each-edit mitigation).
    #[cfg(not(debug_assertions))]
    #[test]
    fn toctou_edit_in_place_detected() {
        let root = mktemp_root("toctou_inplace");
        // Setup: plugin with manifest consistent with initial content.
        mk_plugin(&root, "plugx", "index.html", "original content");
        let hash = compute_plugin_hash(&root.join("plugx")).unwrap();
        mk_plugin_with_manifest(&root, "plugx", &hash);
        // We rewrite the same initial content because
        // `mk_plugin_with_manifest` overwrites `ui/index.html` with "hello".
        fs::write(root.join("plugx/ui/index.html"), "original content").unwrap();
        // We recompute the hash with real content and update it in the manifest
        // to ensure consistency (mk_plugin_with_manifest should keep it
        // but we do it explicitly to harden the test against future refactors).
        let hash = compute_plugin_hash(&root.join("plugx")).unwrap();
        mk_plugin_with_manifest(&root, "plugx", &hash);
        fs::write(root.join("plugx/ui/index.html"), "original content").unwrap();

        // First verify OK → cache populated with known_hash.
        assert_eq!(
            verify_plugin_integrity("plugx", &root),
            Ok(()),
            "baseline verify must pass"
        );

        // Edit in-place without adding/deleting/renaming entries → parent dir mtime
        // remains invariant on most FS (APFS empirically).
        // No sleep changes this; we wait for robustness clock resolution.
        std::thread::sleep(std::time::Duration::from_millis(10));
        fs::write(
            root.join("plugx/ui/index.html"),
            "<script>MALICIOUS</script>",
        )
        .unwrap();

        // ✅ If the old algorithm (cache by dir mtime) were used, this would give
        // Ok(()) falsely. The C01 fix requires 403 for hash mismatch.
        assert_eq!(
            verify_plugin_integrity("plugx", &root),
            Err(403),
            "in-place edit of an existing file must be detected (C01 TOCTOU)"
        );
    }

    // B5 Sprint 0.18 (2026-04-21) — TOCTOU verify→serve atomic snapshot.
    //
    // Security PoC (70.5% reproducible hit-rate): the handler did
    // verify_plugin_integrity (one FS read) + File::open + read_to_end
    // (second read). Between the two, a local attacker with write access to
    // plugins-dev/<id>/ could replace content and the serve returned bytes
    // different from what the hash had just verified.
    //
    // Fix: verify_and_load_plugin_asset does verify + load in ONE atomic snapshot
    // (opens all fds BEFORE any read, hashes from the snapshot,
    // returns the bytes of the requested file FROM THE SAME snapshot).
    //
    // Security invariant: if Ok(bytes), the bytes correspond to the hash that has
    // passed verification. No Ok with bytes different from the manifest.
    //
    // Release-only (STRICT_INTEGRITY=true).
    #[cfg(not(debug_assertions))]
    #[test]
    fn b5_verify_and_load_atomic_snapshot_no_bypass() {
        use std::sync::atomic::{AtomicBool, Ordering};
        use std::sync::Arc;

        let root = mktemp_root("b5_atomic_snapshot");

        // Setup: plugin with benign content and hash consistent with manifest.
        mk_plugin(&root, "target", "index.html", "benign_content");
        let h = crate::integrity::compute_plugin_hash(&root.join("target")).unwrap();
        mk_plugin_with_manifest(&root, "target", &h);
        fs::write(root.join("target/ui/index.html"), "benign_content").unwrap();
        let h = crate::integrity::compute_plugin_hash(&root.join("target")).unwrap();
        mk_plugin_with_manifest(&root, "target", &h);
        fs::write(root.join("target/ui/index.html"), "benign_content").unwrap();

        // Baseline: verify_and_load returns correct bytes without attacker.
        let baseline =
            crate::integrity::verify_and_load_plugin_asset("target", &root, "ui/index.html")
                .unwrap();
        assert_eq!(baseline, b"benign_content");

        // Attacker thread: spin-write alternating between benign and "MAL" (short
        // malicious content to speed up writes) to the same file. With
        // the old algorithm, a window between verify and serve allowed the
        // serve to read "MAL" while the hash had seen "benign_content".
        let attacker_stop = Arc::new(AtomicBool::new(false));
        let stop_flag = attacker_stop.clone();
        let target_file = root.join("target/ui/index.html");
        let attacker = std::thread::spawn(move || {
            let mut toggle = false;
            while !stop_flag.load(Ordering::Relaxed) {
                let content: &[u8] = if toggle { b"benign_content" } else { b"MAL" };
                let _ = fs::write(&target_file, content);
                toggle = !toggle;
                std::thread::yield_now();
            }
        });

        // Victim: 500 requests to verify_and_load. We count:
        //   - Ok with bytes == "benign_content" → OK (hash match, snapshot consistent)
        //   - Ok with bytes != "benign_content" → BYPASS ❌ (invariant broken)
        //   - Err(403) → OK (hash mismatch detected)
        //   - Err(other) → acceptable (race I/O at open)
        let mut ok_benign = 0;
        let mut ok_bypass = 0;
        let mut err_403 = 0;
        let mut err_other = 0;
        for _ in 0..500 {
            match crate::integrity::verify_and_load_plugin_asset("target", &root, "ui/index.html") {
                Ok(bytes) if bytes == b"benign_content" => ok_benign += 1,
                Ok(_) => ok_bypass += 1,
                Err(403) => err_403 += 1,
                Err(_) => err_other += 1,
            }
        }

        attacker_stop.store(true, Ordering::Relaxed);
        let _ = attacker.join();

        eprintln!(
            "B5 stats: ok_benign={} ok_bypass={} err_403={} err_other={}",
            ok_benign, ok_bypass, err_403, err_other
        );

        // Key invariant: ZERO serves with bytes that do not correspond to the verified hash.
        // With the old algorithm, ok_bypass ≈ 70% of 500 = ~350.
        // With the atomic snapshot it must be 0.
        assert_eq!(
            ok_bypass, 0,
            "B5 BYPASS: {} serves retornen bytes diferents del que el hash va verificar",
            ok_bypass
        );

        // Sanity: the test must actually exercise the race (some 403s expected
        // if the attacker captured the snapshot with "MAL"). If all were
        // ok_benign, the test would not really exercise the vector.
        assert!(
            err_403 + ok_benign > 0,
            "test didn't exercise any real request"
        );
    }

    // B5 + B6: verifies that the function rejects plugins with files > MAX_HASH_FILE_BYTES.
    #[cfg(not(debug_assertions))]
    #[test]
    fn b6_hash_per_file_cap_enforced() {
        let root = mktemp_root("b6_per_file_cap");
        mk_plugin(&root, "huge", "index.html", "small");
        // Writes a file > 10 MB (MAX_HASH_FILE_BYTES)
        let big_path = root.join("huge/ui/big.bin");
        let big = vec![0u8; (crate::integrity::MAX_HASH_FILE_BYTES as usize) + 10];
        fs::write(&big_path, &big).unwrap();
        mk_plugin_with_manifest(&root, "huge", "x");

        // verify_and_load_plugin_asset must return 413 for large file
        let res = crate::integrity::verify_and_load_plugin_asset("huge", &root, "ui/index.html");
        assert_eq!(
            res,
            Err(413),
            "file > MAX_HASH_FILE_BYTES must return 413"
        );
    }

    // B6 F7-RT1 gap fix (Sprint 0.18, 2026-04-22): plugin with all files
    // individually within the per-file cap, but with aggregate sum >
    // MAX_HASH_TOTAL_BYTES (50 MB), must return Err(413). OOM prevention
    // via "thousand small files" that cumulatively saturate RAM.
    //
    // Red team F7-RT1 reported: the total cap was IMPLEMENTED in the code
    // (verify_and_load_plugin_asset returns Err(413) if total_bytes_read
    // > MAX_HASH_TOTAL_BYTES) but WITHOUT a regression test. If someone
    // removes the total check, no test catches the regression.
    //
    // Test strategy: 6 files × 9 MB each = 54 MB total,
    // exceeding MAX_HASH_TOTAL_BYTES (50 MB) while keeping each file
    // individually below MAX_HASH_FILE_BYTES (10 MB) → only the total cap can catch it.
    #[cfg(not(debug_assertions))]
    #[test]
    fn b6_hash_total_cap_enforced() {
        let root = mktemp_root("b6_total_cap");
        mk_plugin(&root, "multibig", "index.html", "small");

        // 6 files × 9 MB = 54 MB > MAX_HASH_TOTAL_BYTES (50 MB),
        // each file individually < MAX_HASH_FILE_BYTES (10 MB).
        let per_file_size = 9 * 1024 * 1024; // 9 MB
        for i in 0..6 {
            let path = root.join(format!("multibig/ui/chunk_{i}.bin"));
            fs::write(&path, vec![0u8; per_file_size]).unwrap();
        }
        mk_plugin_with_manifest(&root, "multibig", "x");

        // Must return 413 (total cap exceeded) — even though no individual file
        // exceeds it. If someone removes the MAX_HASH_TOTAL_BYTES check from
        // verify_and_load_plugin_asset, this test fails.
        let res =
            crate::integrity::verify_and_load_plugin_asset("multibig", &root, "ui/index.html");
        assert_eq!(
            res,
            Err(413),
            "6 files × 9MB = 54MB > MAX_HASH_TOTAL_BYTES must return 413"
        );
    }

    // S13 F052 — reentrancy depth guard: HANDLER_DEPTH increments/decrements correctly
    // via DepthGuard (RAII). Depth does not grow without bound.
    #[test]
    fn reentrancy_depth_tracked_and_reset() {
        // Baseline: depth 0 at start
        HANDLER_DEPTH.with(|d| d.set(0));
        assert_eq!(HANDLER_DEPTH.with(|d| d.get()), 0);

        // Simulate handler entry (without calling the whole fn):
        struct DepthGuard;
        impl Drop for DepthGuard {
            fn drop(&mut self) {
                HANDLER_DEPTH.with(|d| d.set(d.get().saturating_sub(1)));
            }
        }
        {
            HANDLER_DEPTH.with(|d| d.set(d.get() + 1));
            let _g = DepthGuard;
            assert_eq!(HANDLER_DEPTH.with(|d| d.get()), 1);
            // Nested (reentrant)
            {
                HANDLER_DEPTH.with(|d| d.set(d.get() + 1));
                let _g2 = DepthGuard;
                assert_eq!(HANDLER_DEPTH.with(|d| d.get()), 2);
            }
            // After inner drop
            assert_eq!(HANDLER_DEPTH.with(|d| d.get()), 1);
        }
        // After outer drop: back to 0
        assert_eq!(HANDLER_DEPTH.with(|d| d.get()), 0);
    }

    #[test]
    fn reentrancy_max_depth_limit() {
        // MAX_HANDLER_DEPTH = 4 → requests with depth >= 4 are rejected with 429.
        // Here we only verify the value; the rejection logic is in the handler.
        assert_eq!(MAX_HANDLER_DEPTH, 4, "MAX_HANDLER_DEPTH constant check");
    }

    // S10 F013/F020 — AuthToken generates UUID v4 (128 bits) unique per launch.
    #[test]
    fn auth_token_generate_is_uuid_v4() {
        let t = AuthToken::generate();
        // UUID v4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx (36 chars incl. hyphens)
        assert_eq!(t.0.len(), 36);
        assert_eq!(t.0.chars().filter(|&c| c == '-').count(), 4);
        // Version digit at pos 14: '4' for UUID v4
        assert_eq!(t.0.chars().nth(14).unwrap(), '4');
    }

    #[test]
    fn auth_token_each_generate_is_distinct() {
        // Two consecutive generations must produce different tokens
        // (128 bits entropy — collisions statistically impossible).
        let a = AuthToken::generate();
        let b = AuthToken::generate();
        assert_ne!(a.0, b.0, "tokens must be unique per launch");
    }

    // S03 F029 — LRU cap bounded (RATE_LIMITERS does not grow without bound)
    #[test]
    fn rate_limiter_lru_bounded() {
        // Insert 600 different IDs (> RATE_LIMIT_LRU_CAP = 500)
        for i in 0..600 {
            let id = format!("plugin{:04}", i);
            let _ = rate_limit_ok_for(&id);
        }
        let guard = rate_limiters().lock().unwrap();
        assert!(
            guard.len() <= RATE_LIMIT_LRU_CAP,
            "LRU cap not respected: {} > {}",
            guard.len(),
            RATE_LIMIT_LRU_CAP
        );
    }

    // S03 F004 — handler_pool bounded (no 1-thread-per-request).
    #[test]
    fn handler_pool_bounded() {
        let pool = handler_pool();
        // Exhaust the pool with 8+N blocking jobs
        let counter = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(9));
        for _ in 0..8 {
            let c = counter.clone();
            let b = barrier.clone();
            pool.execute(move || {
                c.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                b.wait(); // blocks until all 8 + main are present
            });
        }
        // Give time for all 8 workers to reach the barrier
        std::thread::sleep(std::time::Duration::from_millis(50));
        // Pool has exactly 8 active workers — no more can run until these finish
        assert_eq!(pool.active_count(), 8);
        assert_eq!(
            pool.max_count(),
            8,
            "pool max 8 threads (prevents thread-bomb)"
        );
        barrier.wait(); // unblocks all workers
        pool.join();
    }

    // S03 F005/F006 — re-check pattern prevents inconsistent overwrites in races
    #[cfg(not(debug_assertions))]
    #[test]
    fn concurrent_verify_determinism() {
        use std::sync::Arc;
        let root = Arc::new(mktemp_root("concurrent_verify"));
        let hash = {
            let tmp = root.clone();
            mk_plugin(&tmp, "plugc", "index.html", "hello");
            let manifest = format!(
                "[plugin]\nid = \"plugc\"\nversion = \"0.1.0\"\n\n[integrity]\nsha256 = \"{}\"\n",
                "0".repeat(64)
            );
            fs::write(tmp.join("plugc/manifest.toml"), manifest).unwrap();
            let actual = compute_plugin_hash(&tmp.join("plugc")).unwrap();
            mk_plugin_with_manifest(&tmp, "plugc", &actual);
            actual
        };
        // 10 threads verifying concurrently → all must return Ok(())
        let mut handles = vec![];
        for _ in 0..10 {
            let r = root.clone();
            handles.push(std::thread::spawn(move || {
                verify_plugin_integrity("plugc", &r)
            }));
        }
        for h in handles {
            assert_eq!(h.join().unwrap(), Ok(()), "concurrent verify inconsistent");
        }
        // Cache contains ONE consistent entry (observability-only, C01).
        let guard = verified_plugins().lock().unwrap();
        let entry = guard.peek("plugc").expect("expected cache hit");
        // Sanity: the cached known_hash matches the real hash.
        assert_eq!(
            entry.known_hash, hash,
            "cache observability: known_hash must match the real hash"
        );
    }

    // S02 F007 — errors are NOT persisted in the cache (auto-recovery).
    #[cfg(not(debug_assertions))]
    #[test]
    fn cache_does_not_persist_errors() {
        let root = mktemp_root("no_err_cache");
        // First request: manifest with incorrect hash → Err(403)
        mk_plugin_with_manifest(&root, "plugr", "0".repeat(64).as_str());
        assert_eq!(verify_plugin_integrity("plugr", &root), Err(403));

        // Fix the manifest with the correct hash
        std::thread::sleep(std::time::Duration::from_millis(10));
        let correct = compute_plugin_hash(&root.join("plugr")).unwrap();
        mk_plugin_with_manifest(&root, "plugr", &correct);
        // Second request must PASS — the error has NOT been cached.
        assert_eq!(
            verify_plugin_integrity("plugr", &root),
            Ok(()),
            "transient error must not be persisted in the cache"
        );
    }

    // ─────────────────────────────────────────────────────────────────
    // C06 / C14 / C30 (2026-04-21) — regression tests
    // ─────────────────────────────────────────────────────────────────

    // C06 — extract_plugin_id_from_uri pure function (pre-queue).
    #[test]
    fn extract_plugin_id_basic() {
        assert_eq!(
            extract_plugin_id_from_uri("plugin://rag/index.html"),
            Some("rag".to_string())
        );
        assert_eq!(
            extract_plugin_id_from_uri("plugin://my-plugin/assets/app.js"),
            Some("my-plugin".to_string())
        );
        // without trailing path
        assert_eq!(
            extract_plugin_id_from_uri("plugin://rag"),
            Some("rag".to_string())
        );
    }

    #[test]
    fn extract_plugin_id_rejects_missing_host() {
        // plugin:/// — path without host
        assert_eq!(extract_plugin_id_from_uri("plugin:///foo"), None);
        // different scheme
        assert_eq!(extract_plugin_id_from_uri("https://rag/foo"), None);
        // string random
        assert_eq!(extract_plugin_id_from_uri(""), None);
        assert_eq!(extract_plugin_id_from_uri("plugin"), None);
    }

    // ─────────────────────────────────────────────────────────────────
    // C06 legacy tests (`max_queued_constant_sanity`,
    // `handler_pool_queue_count_accessible`) removed at F5 Sprint 0.18
    // (2026-04-21). Both were theatre:
    //   - `max_queued_constant_sanity` only verified `MAX_QUEUED == 256`
    //     literally (no real behavior).
    //   - `handler_pool_queue_count_accessible` asserted `usize < usize::MAX`
    //     (tautology) and enqueued a trivial job that did not touch MAX_QUEUED.
    // Both have been subsumed by `b3_queue_bound_atomic_race` (F4a, further
    // down in this file) which exercises the real CAS with N = MAX_QUEUED+100
    // concurrent threads and verifies the 4 invariants of the B3 fix.
    // ─────────────────────────────────────────────────────────────────

    // ─────────────────────────────────────────────────────────────────
    // C14 F5 Sprint 0.18 (2026-04-21) — dialog guard real mutation test.
    //
    // The old `dialog_showing_guard_semantics` (removed) only exercised
    // `AtomicBool::swap` from stdlib. If someone removed the swap from `graceful_quit`
    // the test kept passing (verified by mutation testing: removing the
    // guard from `graceful_quit` → test ok).
    //
    // Fix: extracted `graceful_quit_try_acquire()` in `lifecycle.rs` as a
    // pure helper (returns `!DIALOG_SHOWING.swap(true, AcqRel)`). `graceful_quit`
    // now calls `if !graceful_quit_try_acquire() { return; }`. This test
    // launches N threads in parallel via `Barrier` and asserts that only ONE
    // thread returns `true`.
    //
    // Mutation testing (F7-RT1 verification 2026-04-22):
    //   - If someone replaces `swap(true, AcqRel)` with unconditional `store(true)`
    //     (always-true return) → test fails `acquired != 1` (256 true returns).
    //   - If someone replaces with a separate racy `load+store` pattern → the test
    //     does NOT catch it reliably (F7-RT1 confirmed: 10/10 passes with racy
    //     pattern on macOS M4 + 256 threads + Barrier). This limitation is
    //     inherent to observable contention without a formal model-checker
    //     (e.g. `loom`) that explores all possible interleavings.
    //
    //   To catch subtle load+store mutations: future options (Sprint 0.19+):
    //     1. Integrate `loom` with `lifecycle` code for model-checking
    //     2. Increase N to 10000+ threads (high CI cost, reliability not guaranteed)
    //     3. Add `cargo-mutants` fuzzing test that marks load+store
    //        as an uncaught variant and documents it
    //
    // Debug + release: the test is deterministic for the "correct" pattern (an
    // atomic CAS never lets > 1 thread win), does not depend on timing for false
    // positives. Hence no `cfg(not(debug_assertions))` — coverage in both
    // configurations.
    // ─────────────────────────────────────────────────────────────────
    #[test]
    fn t1_dialog_guard_only_one_acquires_under_concurrency() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::{Arc, Barrier};
        use std::thread;

        // Reset — other lifecycle tests may have left it true.
        DIALOG_SHOWING.store(false, Ordering::Release);

        // N threads competing for the same guard. MAX_QUEUED+ is sufficient to
        // force contention pressure under any realistic scheduler (macOS M4
        // has no deterministic scheduler under massive spawn). A correct CAS
        // only allows ONE acquire; any mutation (simple store, always-true branch,
        // etc.) causes > 1 thread to win.
        let n = 256;
        let barrier = Arc::new(Barrier::new(n));
        let acquired = Arc::new(AtomicUsize::new(0));

        let mut handles = Vec::with_capacity(n);
        for _ in 0..n {
            let b = barrier.clone();
            let a = acquired.clone();
            handles.push(thread::spawn(move || {
                // Synchronize the start of all threads at the same instant
                // to maximize real contention on the swap() CAS.
                b.wait();
                if graceful_quit_try_acquire() {
                    a.fetch_add(1, Ordering::Relaxed);
                }
            }));
        }
        for h in handles {
            h.join().unwrap();
        }

        let acquired_n = acquired.load(Ordering::Relaxed);
        assert_eq!(
            acquired_n, 1,
            "C14 guard violated: {acquired_n} threads acquired the dialog guard simultaneously \
            (expected exactly 1). If > 1, swap(true, AcqRel) has been replaced by a \
            non-atomic operation or the CAS is broken. If 0, graceful_quit_try_acquire \
            always returns false (guard permanently blocked)."
        );

        // Release to allow other tests.
        DIALOG_SHOWING.store(false, Ordering::Release);
    }

    // C30 — rate_limit_ok_for does not alloc per request: the cache must only
    // contain ONE entry for the same plugin even if called N times.
    // We cannot observe allocs directly (Rust has no counter) but we can
    // verify that `contains(id)` stays true after 1000 calls
    // (not evicted or duplicated).
    #[test]
    fn rate_limit_no_duplicate_entry_same_id() {
        let id = "c30_stable_id_unique_xyz";
        for _ in 0..1000 {
            let _ = rate_limit_ok_for(id);
        }
        let guard = rate_limiters().lock().unwrap();
        // Exactly 1 entry for our id (no duplication from repeated alloc).
        assert!(
            guard.contains(id),
            "rate_limiter must maintain a unique entry for the same id"
        );
    }

    // C41 — finish_with_timing does not panic if started is in the past relative to target
    // (unlikely but defends against monotonic clock drift on hibernate).
    #[test]
    fn finish_with_timing_no_panic_on_past_target() {
        use std::thread::sleep;
        use std::time::{Duration, Instant};
        // Simulate started well in the past so elapsed > TARGET (50ms).
        let started = Instant::now() - Duration::from_millis(200);
        // Must return immediately without panic (checked_sub = None → no sleep).
        // The test only verifies that it does NOT panic.
        let resp = err_response(200, b"ok");
        let _ = finish_with_timing(resp, started);
        sleep(Duration::from_millis(1));
    }

    // C51 — content_type case sanity (headers test already covered in other tests).
    #[test]
    fn content_type_modern_formats_sanity() {
        // Re-verify that critical modern extensions are still mapped.
        assert_eq!(content_type_for("x.woff2"), "font/woff2");
        assert_eq!(content_type_for("x.avif"), "image/avif");
        assert_eq!(content_type_for("x.wasm"), "application/wasm");
    }

    // B3 test (b3_queue_bound_atomic_race) has been moved to `handler.rs` (mod tests)
    // — Dev Session 2026-05-08. PENDING_COUNT and try_acquire_pending_slot live in handler.

    // ─────────────────────────────────────────────────────────────────
    // Z3 Sprint 0.18 (2026-04-21) — err_response defensive headers
    // ─────────────────────────────────────────────────────────────────
    //
    // Security review (Z3/B5): err_response emitted errors 400/403/404/
    // 413/429/503 WITHOUT defensive headers. Fix adds Content-Type, nosniff,
    // Cache-Control, CSP (default-src 'none'; frame-ancestors 'none'),
    // Permissions-Policy, Referrer-Policy, X-Frame-Options DENY, ACAO null.
    //
    // Mutation: if someone removes the headers from err_response, these tests fail.

    #[test]
    fn err_response_has_security_headers() {
        let resp = err_response(404, b"not found");
        let headers = resp.headers();

        assert!(
            headers.get("Content-Type").is_some(),
            "Content-Type header required"
        );
        assert_eq!(
            headers.get("X-Content-Type-Options").unwrap(),
            "nosniff",
            "X-Content-Type-Options nosniff required"
        );
        assert_eq!(
            headers.get("Cache-Control").unwrap(),
            "no-store",
            "Cache-Control no-store required (error responses must not be cached)"
        );
        assert_eq!(
            headers.get("Content-Security-Policy").unwrap(),
            "default-src 'none'; frame-ancestors 'none'",
            "CSP default-src 'none' + frame-ancestors 'none' required on errors"
        );
        assert!(
            headers.get("Permissions-Policy").is_some(),
            "Permissions-Policy required"
        );
        assert_eq!(
            headers.get("Referrer-Policy").unwrap(),
            "no-referrer",
            "Referrer-Policy no-referrer required"
        );
        assert_eq!(
            headers.get("X-Frame-Options").unwrap(),
            "DENY",
            "X-Frame-Options DENY required (block framing of errors)"
        );
        assert_eq!(
            headers.get("Access-Control-Allow-Origin").unwrap(),
            "null",
            "ACAO null required"
        );
    }

    #[test]
    fn err_response_different_status_same_headers() {
        // All status codes that err_response can emit from the handler
        // must have the same defensive headers.
        for status in [400_u16, 403, 404, 405, 413, 429, 500, 503] {
            let resp = err_response(status, b"err");
            assert_eq!(resp.status().as_u16(), status, "status code mismatch");
            let h = resp.headers();
            assert!(
                h.get("X-Content-Type-Options").is_some(),
                "missing nosniff for status {status}"
            );
            assert!(
                h.get("Content-Security-Policy").is_some(),
                "missing CSP for status {status}"
            );
            assert!(
                h.get("X-Frame-Options").is_some(),
                "missing X-Frame-Options for status {status}"
            );
            assert!(
                h.get("Cache-Control").is_some(),
                "missing Cache-Control for status {status}"
            );
        }
    }

    #[test]
    fn err_response_preserves_body_bytes() {
        // Regression: headers must not corrupt the body — the caller
        // trusts that the payload is transmitted intact.
        let body: &[u8] = b"bad request";
        let resp = err_response(400, body);
        assert_eq!(resp.body().as_slice(), body);
    }

    // ─────────────────────────────────────────────────────────────────
    // Per-file integrity (ADR-0014 v2) — TDD tests written before implementation.
    // All tests below will FAIL until the new functions are implemented.
    // TDD plan (ADR-0014 v2).
    // ─────────────────────────────────────────────────────────────────

    #[test]
    fn per_file_compute_file_hash_is_sha256_hex() {
        use crate::integrity::compute_file_hash;
        let h = compute_file_hash(b"hello");
        assert_eq!(h.len(), 64, "sha256 hex must be 64 chars");
        assert_eq!(h, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
    }

    #[test]
    fn per_file_manifest_hash_excludes_itself() {
        use crate::integrity::compute_manifest_hash;
        let m1 = "[plugin]\nid=\"x\"\n[integrity]\nmanifest_sha256 = \"IGNORE_ME\"\n[integrity.files]\n\"a.html\" = \"abc\"\n";
        let m2 = "[plugin]\nid=\"x\"\n[integrity]\nmanifest_sha256 = \"DIFFERENT\"\n[integrity.files]\n\"a.html\" = \"abc\"\n";
        let h1 = compute_manifest_hash(m1).unwrap();
        let h2 = compute_manifest_hash(m2).unwrap();
        assert_eq!(h1, h2, "manifest_sha256 field must be excluded from its own hash");
    }

    #[test]
    fn per_file_manifest_hash_changes_when_files_change() {
        use crate::integrity::compute_manifest_hash;
        let m1 = "[plugin]\nid=\"x\"\n[integrity]\nmanifest_sha256=\"x\"\n[integrity.files]\n\"a.html\" = \"hash1\"\n";
        let m2 = "[plugin]\nid=\"x\"\n[integrity]\nmanifest_sha256=\"x\"\n[integrity.files]\n\"a.html\" = \"hash2\"\n";
        let h1 = compute_manifest_hash(m1).unwrap();
        let h2 = compute_manifest_hash(m2).unwrap();
        assert_ne!(h1, h2, "different file hashes must produce different manifest hash");
    }

    #[test]
    fn per_file_detect_format_new() {
        use crate::integrity::{detect_integrity_format, IntegrityFormat};
        let m = "[integrity]\nmanifest_sha256 = \"abc\"\n[integrity.files]\n\"x.html\" = \"def\"\n";
        assert!(matches!(detect_integrity_format(m), IntegrityFormat::PerFile(_)));
    }

    #[test]
    fn per_file_detect_format_legacy() {
        use crate::integrity::{detect_integrity_format, IntegrityFormat};
        let m = "[integrity]\nsha256 = \"abc123\"\n";
        match detect_integrity_format(m) {
            IntegrityFormat::DirectoryHash(h) => assert_eq!(h, "abc123"),
            _ => panic!("expected DirectoryHash"),
        }
    }

    #[test]
    fn per_file_manifest_hash_deterministic_key_order() {
        use crate::integrity::compute_manifest_hash;
        let m1 = "[integrity]\nmanifest_sha256=\"x\"\n[integrity.files]\n\"z.html\" = \"hz\"\n\"a.html\" = \"ha\"\n";
        let m2 = "[integrity]\nmanifest_sha256=\"x\"\n[integrity.files]\n\"a.html\" = \"ha\"\n\"z.html\" = \"hz\"\n";
        let h1 = compute_manifest_hash(m1).unwrap();
        let h2 = compute_manifest_hash(m2).unwrap();
        assert_eq!(h1, h2, "key order in manifest must not affect hash");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_verify_manifest_integrity_valid_passes() {
        use crate::integrity::{verify_manifest_integrity, write_per_file_manifest};
        let root = mktemp_root("perfile_manifest_ok");
        mk_plugin(&root, "plug", "index.html", "hello"); // creates root/plug/ui/index.html
        write_per_file_manifest(&root, "plug").unwrap();
        let result = verify_manifest_integrity(&root.join("plug"));
        assert!(result.is_ok(), "valid manifest must pass: {:?}", result);
        let files = result.unwrap();
        // mk_plugin creates root/plug/ui/index.html — rel_path is "ui/index.html"
        assert!(files.contains_key("ui/index.html"), "ui/index.html must be in files map");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_verify_manifest_integrity_tampered_rejected() {
        use crate::integrity::{verify_manifest_integrity, write_per_file_manifest};
        let root = mktemp_root("perfile_manifest_tampered");
        mk_plugin(&root, "plug", "index.html", "hello");
        write_per_file_manifest(&root, "plug").unwrap();
        // Corrupt manifest_sha256
        let manifest_path = root.join("plug/manifest.toml");
        let content = fs::read_to_string(&manifest_path).unwrap();
        let corrupted = content.replace(
            content.lines().find(|l| l.contains("manifest_sha256")).unwrap_or(""),
            "manifest_sha256 = \"0000000000000000000000000000000000000000000000000000000000000000\"",
        );
        fs::write(&manifest_path, corrupted).unwrap();
        assert_eq!(verify_manifest_integrity(&root.join("plug")), Err(403),
            "tampered manifest_sha256 must be rejected");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_verify_and_load_valid() {
        use crate::integrity::write_per_file_manifest;
        let root = mktemp_root("perfile_load_valid");
        mk_plugin(&root, "plug", "index.html", "<h1>hello</h1>"); // creates ui/index.html
        write_per_file_manifest(&root, "plug").unwrap();
        let bytes = crate::integrity::verify_and_load_plugin_asset("plug", &root, "ui/index.html").unwrap();
        assert_eq!(bytes, b"<h1>hello</h1>", "must return the correct bytes");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_verify_and_load_modified_file_rejected() {
        use crate::integrity::write_per_file_manifest;
        let root = mktemp_root("perfile_load_modified");
        mk_plugin(&root, "plug", "index.html", "original"); // creates ui/index.html
        write_per_file_manifest(&root, "plug").unwrap();
        // Modify file after manifest was written
        fs::write(root.join("plug/ui/index.html"), "MODIFIED").unwrap();
        let result = crate::integrity::verify_and_load_plugin_asset("plug", &root, "ui/index.html");
        assert_eq!(result, Err(403), "modified file must be rejected with 403");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_verify_and_load_file_not_in_manifest_is_404() {
        use crate::integrity::write_per_file_manifest;
        let root = mktemp_root("perfile_not_in_manifest");
        mk_plugin(&root, "plug", "index.html", "hello"); // creates ui/index.html
        write_per_file_manifest(&root, "plug").unwrap();
        // Request a file that is not in the manifest
        let result = crate::integrity::verify_and_load_plugin_asset("plug", &root, "ui/missing.html");
        assert_eq!(result, Err(404), "file not in manifest must be 404");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_legacy_format_still_works() {
        // manifest with [integrity].sha256 (old directory-hash format) must still work
        let root = mktemp_root("perfile_legacy_compat");
        mk_plugin_with_manifest(&root, "plug", "placeholder");
        let actual = compute_plugin_hash(&root.join("plug")).unwrap();
        mk_plugin_with_manifest(&root, "plug", &actual);
        let result = crate::integrity::verify_and_load_plugin_asset("plug", &root, "ui/index.html");
        assert!(result.is_ok(), "legacy directory-hash format must still work: {:?}", result);
        assert_eq!(result.unwrap(), b"hello");
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn per_file_toctou_race_zero_bypass() {
        use crate::integrity::write_per_file_manifest;
        use std::sync::atomic::{AtomicBool, Ordering};
        use std::sync::Arc;

        let root = mktemp_root("perfile_toctou_race");
        mk_plugin(&root, "plug", "index.html", "benign_content"); // creates ui/index.html
        write_per_file_manifest(&root, "plug").unwrap();

        // Baseline verify
        let baseline = crate::integrity::verify_and_load_plugin_asset("plug", &root, "ui/index.html").unwrap();
        assert_eq!(baseline, b"benign_content");

        // Attacker thread: alternate between benign and MAL
        let stop = Arc::new(AtomicBool::new(false));
        let stop_flag = stop.clone();
        let target = root.join("plug/ui/index.html");
        let attacker = std::thread::spawn(move || {
            let mut toggle = false;
            while !stop_flag.load(Ordering::Relaxed) {
                let content: &[u8] = if toggle { b"benign_content" } else { b"MAL" };
                let _ = fs::write(&target, content);
                toggle = !toggle;
                std::thread::yield_now();
            }
        });

        let mut ok_benign = 0u32;
        let mut ok_bypass = 0u32;
        let mut err_403 = 0u32;
        let mut err_other = 0u32;
        for _ in 0..500 {
            match crate::integrity::verify_and_load_plugin_asset("plug", &root, "ui/index.html") {
                Ok(b) if b == b"benign_content" => ok_benign += 1,
                Ok(_) => ok_bypass += 1,
                Err(403) => err_403 += 1,
                Err(_) => err_other += 1,
            }
        }

        stop.store(true, Ordering::Relaxed);
        let _ = attacker.join();

        eprintln!("per-file B5 stats: ok_benign={ok_benign} ok_bypass={ok_bypass} err_403={err_403} err_other={err_other}");
        assert_eq!(ok_bypass, 0, "B5 per-file BYPASS: {ok_bypass} serves returned bytes different from what the hash verified");
        assert!(err_403 + ok_benign > 0, "test did not exercise any real request");
    }
}
