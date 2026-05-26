//! Validation of plugin IDs, requests and path resolution.
//!
//! Pure functions (except read-only canonicalize) — testable without Tauri runtime.

use std::path::{Path, PathBuf};
use tauri::Runtime;

// S08 F058 — Windows reserved device names.
// These words are DOS device names and Windows rejects them as
// file/directory names. We block them proactively for cross-platform consistency
// (the same plugin_id must be valid on macOS/Linux/Windows).
// Reference: https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
pub(crate) const WINDOWS_RESERVED_NAMES: &[&str] = &[
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8",
    "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
];

/// Validates a plugin id format: **lowercase** ASCII + `-` + `_`, 2-64 chars.
///
/// Lowercase-only to avoid cross-platform case bugs (APFS
/// case-insensitive vs ext4 case-sensitive). Prevents `plugin://RAG/...`
/// from working on macOS but breaking on Linux — and avoids per-plugin permission
/// bypass at marketplace level (a plugin 'Trusted' vs 'trusted' would be ambiguous).
///
/// S08 F058: also rejects Windows reserved device names (con, prn, aux, nul,
/// com1-9, lpt1-9) because they cannot be created as directories on Windows.
pub(crate) fn validate_plugin_id(id: &str) -> bool {
    if !(2..=64).contains(&id.len()) {
        return false;
    }
    if !id
        .chars()
        .all(|c| matches!(c, 'a'..='z' | '0'..='9' | '-' | '_'))
    {
        return false;
    }
    // F058: exact-match (id is already lowercase from the enforcement above).
    if WINDOWS_RESERVED_NAMES.contains(&id) {
        return false;
    }
    true
}

/// Validates the method + URI of a request. Pure function, testable without Tauri runtime.
///
/// S04 F036: query strings are accepted (JS framework `?v=123` cache-bust).
pub(crate) fn validate_request(method: &str, uri: &tauri::http::Uri) -> Result<(), u16> {
    // Only GET/HEAD — reduce attack surface (no POST/PUT/DELETE/OPTIONS/etc.)
    if !matches!(method, "GET" | "HEAD") {
        return Err(405);
    }
    // S04 F036: query string is accepted but ignored (not appended to the path).
    // We only reject explicit port (surface reduction).
    if uri.port().is_some() {
        return Err(400);
    }
    Ok(())
}

/// Resolves the absolute path of a plugin asset inside `<plugins_root>/<plugin_id>/ui/`
/// with anti path-traversal protection (canonicalize + starts_with against the SPECIFIC root).
///
/// Returns `Err(status)` with:
/// - 400 if `plugin_id` is invalid
/// - 404 if the plugin does not exist or the file is not found
/// - 403 if the path escapes the `<id>/ui/` directory (traversal, malicious symlinks)
///
/// Pure function: does not touch the FS except for `canonicalize` (read-only, no side effects).
pub(crate) fn resolve_plugin_path(
    plugins_root: &Path,
    plugin_id: &str,
    uri_path: &str,
) -> Result<PathBuf, u16> {
    if !validate_plugin_id(plugin_id) {
        return Err(400);
    }

    let plugin_ui_root = plugins_root.join(plugin_id).join("ui");
    let canon_ui_root = plugin_ui_root.canonicalize().map_err(|_| 404_u16)?;

    // percent-decoding for files with spaces/Unicode in their name
    let decoded = percent_encoding::percent_decode_str(uri_path.trim_start_matches('/'))
        .decode_utf8()
        .map_err(|_| 400_u16)?;

    let file_path = canon_ui_root.join(decoded.as_ref());
    let canon_file = file_path.canonicalize().map_err(|_| 404_u16)?;

    if !canon_file.starts_with(&canon_ui_root) {
        return Err(403);
    }

    if !canon_file.is_file() {
        return Err(404);
    }

    Ok(canon_file)
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- validate_plugin_id ---

    #[test]
    fn valid_plugin_ids() {
        assert!(validate_plugin_id("rag"));
        assert!(validate_plugin_id("my-plugin"));
        assert!(validate_plugin_id("my_plugin_v2"));
        assert!(validate_plugin_id("ab")); // min length 2
        assert!(validate_plugin_id(&"a".repeat(64))); // max length 64
    }

    #[test]
    fn rejects_too_short() {
        assert!(!validate_plugin_id("a"));
        assert!(!validate_plugin_id(""));
    }

    #[test]
    fn rejects_too_long() {
        assert!(!validate_plugin_id(&"a".repeat(65)));
    }

    #[test]
    fn rejects_uppercase() {
        assert!(!validate_plugin_id("Rag"));
        assert!(!validate_plugin_id("RAG"));
        assert!(!validate_plugin_id("myPlugin"));
    }

    #[test]
    fn rejects_special_chars() {
        assert!(!validate_plugin_id("my.plugin"));
        assert!(!validate_plugin_id("my/plugin"));
        assert!(!validate_plugin_id("my plugin"));
        assert!(!validate_plugin_id("../escape"));
    }

    #[test]
    fn rejects_windows_reserved_names() {
        assert!(!validate_plugin_id("con"));
        assert!(!validate_plugin_id("prn"));
        assert!(!validate_plugin_id("aux"));
        assert!(!validate_plugin_id("nul"));
        assert!(!validate_plugin_id("com1"));
        assert!(!validate_plugin_id("lpt1"));
    }

    #[test]
    fn allows_names_containing_reserved_as_substring() {
        assert!(validate_plugin_id("icon"));
        assert!(validate_plugin_id("console"));
        assert!(validate_plugin_id("my-aux-tool"));
    }

    // --- validate_request ---

    #[test]
    fn allows_get_and_head() {
        let uri: tauri::http::Uri = "plugin://test/index.html".parse().unwrap();
        assert!(validate_request("GET", &uri).is_ok());
        assert!(validate_request("HEAD", &uri).is_ok());
    }

    #[test]
    fn rejects_post_put_delete() {
        let uri: tauri::http::Uri = "plugin://test/index.html".parse().unwrap();
        assert_eq!(validate_request("POST", &uri), Err(405));
        assert_eq!(validate_request("PUT", &uri), Err(405));
        assert_eq!(validate_request("DELETE", &uri), Err(405));
    }

    #[test]
    fn rejects_uri_with_port() {
        let uri: tauri::http::Uri = "plugin://test:8080/index.html".parse().unwrap();
        assert_eq!(validate_request("GET", &uri), Err(400));
    }

    #[test]
    fn allows_query_string() {
        let uri: tauri::http::Uri = "plugin://test/app.js?v=123".parse().unwrap();
        assert!(validate_request("GET", &uri).is_ok());
    }

    // --- resolve_plugin_path ---

    #[test]
    fn rejects_invalid_plugin_id_in_resolve() {
        let root = std::env::temp_dir().join("nexe-validate-resolve");
        assert_eq!(resolve_plugin_path(&root, "BAD", "/index.html"), Err(400));
        assert_eq!(resolve_plugin_path(&root, "a", "/x"), Err(400));
        assert_eq!(resolve_plugin_path(&root, "con", "/x"), Err(400));
    }

    #[test]
    fn rejects_nonexistent_plugin() {
        let root = std::env::temp_dir().join("nexe-validate-noexist");
        assert_eq!(resolve_plugin_path(&root, "no-such-plugin", "/index.html"), Err(404));
    }

    #[test]
    fn resolves_valid_plugin_file() {
        let root = std::env::temp_dir().join("nexe-validate-ok");
        let ui_dir = root.join("test-plug/ui");
        std::fs::create_dir_all(&ui_dir).unwrap();
        std::fs::write(ui_dir.join("index.html"), "<html>ok</html>").unwrap();

        let result = resolve_plugin_path(&root, "test-plug", "/index.html");
        assert!(result.is_ok());

        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn rejects_path_traversal() {
        let root = std::env::temp_dir().join("nexe-validate-trav");
        let ui_dir = root.join("evil/ui");
        std::fs::create_dir_all(&ui_dir).unwrap();
        std::fs::write(ui_dir.join("ok.html"), "ok").unwrap();
        std::fs::write(root.join("evil/secret.txt"), "secret").unwrap();

        assert_eq!(resolve_plugin_path(&root, "evil", "/../secret.txt"), Err(403));

        std::fs::remove_dir_all(&root).ok();
    }
}

// Plugin root resolver with dev/release split (avoids baking builder's FS path into the release binary).
//
// Dev: looks for `plugins-dev/` relative to Cargo.toml (via CARGO_MANIFEST_DIR)
// Release: looks for `plugins/` inside the Tauri app resource dir (copied to bundle by build script)
#[cfg(debug_assertions)]
pub(crate) fn plugin_root<R: Runtime>(_app: &tauri::AppHandle<R>) -> PathBuf {
    // CARGO_MANIFEST_DIR always exists in debug (build.rs defines it).
    // If .parent() is None, we fall back to a path that triggers 404 on all requests.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.join("plugins-dev"))
        .unwrap_or_else(|| PathBuf::from("/nonexistent-plugins"))
}

#[cfg(not(debug_assertions))]
pub(crate) fn plugin_root<R: Runtime>(app: &tauri::AppHandle<R>) -> PathBuf {
    use tauri::Manager;
    // F050: safe fallback if the bundle is corrupt or tampered.
    // Returns a non-existent path → all requests return 404 (fail-closed).
    match app.path().resource_dir() {
        Ok(dir) => dir.join("plugins"),
        Err(e) => {
            tracing::error!("resource_dir unavailable (bundle corrupt?): {e}");
            std::path::PathBuf::from("/nonexistent-plugins")
        }
    }
}
