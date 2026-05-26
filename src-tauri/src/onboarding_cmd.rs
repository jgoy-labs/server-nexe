//! F5.3: Onboarding state commands.
//!
//! `check_first_run`          — returns true when the wizard has not been completed.
//! `mark_onboarding_complete` — writes the completion flag to the app config dir.
//!
//! Detection is file-based (not localStorage) so it survives browser storage clears
//! and is consistent across WebView restarts.

use tauri::{AppHandle, Manager};

/// Return `true` when the onboarding wizard has not yet been completed.
///
/// Called via `invoke("check_first_run")` at frontend boot.
/// The flag file lives at `<app_config_dir>/onboarding_complete`.
#[tauri::command]
pub fn check_first_run(app: AppHandle) -> bool {
    let flag = app
        .path()
        .app_config_dir()
        .unwrap_or_default()
        .join("onboarding_complete");
    !flag.exists()
}

/// Return `true` when a previous partial installation is detected:
/// the sidecar bundle was extracted (`.extracted` marker exists) but
/// the wizard was never completed (`onboarding_complete` absent).
///
/// Called via `invoke("check_partial_install")` from Step 1 to decide
/// whether to show the "Reset installation…" banner.
#[tauri::command]
pub fn check_partial_install(app: AppHandle) -> bool {
    let data_dir = app.path().app_data_dir().unwrap_or_default();
    let extracted = data_dir.join("sidecar").join(".extracted");
    extracted.exists() && !flag_path(&app).exists()
}

/// Clear all installation state so the next launch re-extracts the
/// sidecar bundle and re-runs the wizard from scratch.
///
/// Removes:
///   - `<app_config_dir>/onboarding_complete`
///   - `<app_data_dir>/sidecar/data/onboarding_state.json`
///   - `<app_data_dir>/sidecar/.extracted`
///
/// Called via `invoke("reset_installation")` when the user confirms
/// the "Reset installation…" action in Step 1. The frontend reloads
/// the page after this call; step0-splash re-extracts the bundle.
/// Errors are silently ignored — worst case the wizard shows again.
#[tauri::command]
pub fn reset_installation(app: AppHandle) {
    reset_installation_inner(&app, false);
}

/// Full uninstall: removes onboarding state, extracted bundle, downloaded
/// models, AND WebKit localStorage so the wizard starts fresh on next launch.
/// Called from the tray "Uninstall" menu item.
pub fn full_uninstall(app: &AppHandle) {
    reset_installation_inner(app, true);
}

fn reset_installation_inner(app: &AppHandle, full: bool) {
    let config_dir = app.path().app_config_dir().unwrap_or_default();
    let data_dir = app.path().app_data_dir().unwrap_or_default();
    let _ = std::fs::remove_file(config_dir.join("onboarding_complete"));
    let _ = std::fs::remove_file(
        data_dir
            .join("sidecar")
            .join("data")
            .join("onboarding_state.json"),
    );
    let _ = std::fs::remove_file(data_dir.join("sidecar").join(".extracted"));

    if full {
        let sidecar = data_dir.join("sidecar");
        let _ = std::fs::remove_dir_all(sidecar.join("data").join("models"));
        let _ = std::fs::remove_dir_all(sidecar.join("vectors"));
        let _ = std::fs::remove_dir_all(sidecar.join("storage"));
        if let Ok(home) = std::env::var("HOME") {
            let webkit = std::path::PathBuf::from(&home)
                .join("Library/WebKit/com.nexe.app");
            let _ = std::fs::remove_dir_all(&webkit);
        }
    }
}

/// Return the path of the first-run flag file (pure, testable helper).
pub fn flag_path(app: &AppHandle) -> std::path::PathBuf {
    app.path()
        .app_config_dir()
        .unwrap_or_default()
        .join("onboarding_complete")
}

/// Write the onboarding completion flag to disk.
///
/// Called via `invoke("mark_onboarding_complete")` when the user clicks
/// "Start server-nexe" in Step 5. Creates the config dir if it does not exist.
/// Errors are silently ignored — a failed write means the wizard will show again
/// on next launch, which is a safe degradation.
#[tauri::command]
pub fn mark_onboarding_complete(app: AppHandle) {
    if let Ok(config_dir) = app.path().app_config_dir() {
        let _ = std::fs::create_dir_all(&config_dir);
        let _ = std::fs::write(config_dir.join("onboarding_complete"), b"1");
    }
}

// DO NOT add a `get_nexe_api_key` Tauri command: exposing the primary
// api_key via `invoke()` is an XSS exfiltration vector (any compromised
// plugin frame could read it). The wizard receives the api_key in the
// `/installer/finalize` response body instead — see
// src/onboarding/step5-apikey.js.

#[cfg(test)]
mod tests {
    use std::fs;
    use tempfile::TempDir;

    /// Helper: simulate the flag-file logic without a real AppHandle.
    fn flag_exists(dir: &std::path::Path) -> bool {
        dir.join("onboarding_complete").exists()
    }

    fn write_flag(dir: &std::path::Path) {
        fs::create_dir_all(dir).unwrap();
        fs::write(dir.join("onboarding_complete"), b"1").unwrap();
    }

    #[test]
    fn no_flag_means_first_run() {
        let tmp = TempDir::new().unwrap();
        assert!(!flag_exists(tmp.path()), "fresh dir => first_run should be true");
    }

    #[test]
    fn flag_present_means_not_first_run() {
        let tmp = TempDir::new().unwrap();
        write_flag(tmp.path());
        assert!(flag_exists(tmp.path()), "flag written => first_run should be false");
    }

    #[test]
    fn write_flag_creates_file() {
        let tmp = TempDir::new().unwrap();
        assert!(!flag_exists(tmp.path()));
        write_flag(tmp.path());
        assert!(flag_exists(tmp.path()));
    }

    // ── check_partial_install helpers ──────────────────────────────────────

    fn partial_install_detected(config_dir: &std::path::Path, data_dir: &std::path::Path) -> bool {
        let extracted = data_dir.join("sidecar").join(".extracted");
        let complete = config_dir.join("onboarding_complete");
        extracted.exists() && !complete.exists()
    }

    fn write_extracted(data_dir: &std::path::Path) {
        let sidecar = data_dir.join("sidecar");
        fs::create_dir_all(&sidecar).unwrap();
        fs::write(sidecar.join(".extracted"), b"sha256-placeholder").unwrap();
    }

    #[test]
    fn fresh_install_no_extracted_not_partial() {
        let cfg = TempDir::new().unwrap();
        let data = TempDir::new().unwrap();
        assert!(!partial_install_detected(cfg.path(), data.path()));
    }

    #[test]
    fn extracted_without_complete_flag_is_partial() {
        let cfg = TempDir::new().unwrap();
        let data = TempDir::new().unwrap();
        write_extracted(data.path());
        assert!(partial_install_detected(cfg.path(), data.path()));
    }

    #[test]
    fn extracted_with_complete_flag_is_not_partial() {
        let cfg = TempDir::new().unwrap();
        let data = TempDir::new().unwrap();
        write_extracted(data.path());
        write_flag(cfg.path());
        assert!(!partial_install_detected(cfg.path(), data.path()));
    }

    // ── reset_installation helpers ─────────────────────────────────────────

    fn do_reset(config_dir: &std::path::Path, data_dir: &std::path::Path) {
        let _ = fs::remove_file(config_dir.join("onboarding_complete"));
        let _ = fs::remove_file(
            data_dir
                .join("sidecar")
                .join("data")
                .join("onboarding_state.json"),
        );
        let _ = fs::remove_file(data_dir.join("sidecar").join(".extracted"));
    }

    #[test]
    fn reset_removes_all_three_flags() {
        let cfg = TempDir::new().unwrap();
        let data = TempDir::new().unwrap();

        write_flag(cfg.path());
        write_extracted(data.path());
        let state_path = data.path().join("sidecar").join("data");
        fs::create_dir_all(&state_path).unwrap();
        fs::write(state_path.join("onboarding_state.json"), b"{}").unwrap();

        do_reset(cfg.path(), data.path());

        assert!(!cfg.path().join("onboarding_complete").exists());
        assert!(!data.path().join("sidecar").join(".extracted").exists());
        assert!(!state_path.join("onboarding_state.json").exists());
    }

    #[test]
    fn reset_is_idempotent_on_fresh_dir() {
        let cfg = TempDir::new().unwrap();
        let data = TempDir::new().unwrap();
        // Must not panic when files are absent.
        do_reset(cfg.path(), data.path());
    }
}
