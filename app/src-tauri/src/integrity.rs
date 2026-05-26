//! Plugin integrity SHA-256 — Sprint 0.15 #4 / ADR-0014 ACTIVE.
//!
//! Algorithm: hash over the entire plugin folder (option A):
//!   - Recursive walk of `<plugins_root>/<plugin_id>/`, sorted by relative path
//!     (forward-slash, deterministic cross-platform).
//!   - Per file: `H(rel_path || "\n" || size || "\n" || content_bytes)`
//!   - For `manifest.toml`: parse TOML, remove [integrity] section, re-serialize
//!     canonically. This avoids circularity (the hash depends on a field that
//!     contains the hash).
//!
//! C01(2026-04-21): fix TOCTOU mtime. POSIX/APFS/NTFS do NOT update
//! directory mtime when a file is edited in-place — `CacheEntry` based on
//! `plugin_dir_mtime` allowed total bypass. The new algorithm re-computes
//! `compute_plugin_hash()` on every request and compares with the manifest.
//!
//! B5 Sprint 0.18 (2026-04-21): fix TOCTOU verify→serve double-read.
//! The C01 fix covered the cache TOCTOU but NOT the TOCTOU between verify and the
//! subsequent `File::open + read_to_end` in the handler (70.5% hit-rate in the
//! security PoC). The new function `verify_and_load_plugin_asset`
//! implements "atomic snapshot via open fd": we open ALL plugin fds BEFORE any
//! read, read from the fds (Unix guarantees inode alive for open fds against
//! external rename/unlink/write), hash from bytes already in memory, and return
//! the bytes of the requested file FROM THE SAME snapshot. This eliminates
//! the verify↔serve window completely.
//!
//! B6 Sprint 0.18: MAX_HASH_FILE_BYTES cap per file (10MB) and
//! MAX_HASH_TOTAL_BYTES combined cap (50MB) to prevent OOM via malicious
//! plugins or large sparse files.
//!
//! S02 F007: only cache successes. Errors auto-retry on next request.
//! S03 F029: LRU cap (500 entries) to prevent OOM via different IDs.
//! S06 F024: dev=false to avoid friction each-edit; release=true mandatory.
//!
//! ADR-0014 v2 — Per-file integrity (2026-05-09):
//! New format: manifest.toml has `[integrity].manifest_sha256` (hash of the manifest
//! canonicalised without that field) and `[integrity.files]` (per-file sha256).
//! Each GET verifies only the requested file (open fd → read → hash → compare),
//! eliminating the O(plugin_size) cost of the directory-hash algorithm.
//! Legacy `[integrity].sha256` (directory hash) is still supported.

use lru::LruCache;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::io::Read;
use std::num::NonZeroUsize;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

#[cfg(debug_assertions)]
pub(crate) const STRICT_INTEGRITY: bool = false;
#[cfg(not(debug_assertions))]
pub(crate) const STRICT_INTEGRITY: bool = true;

/// B6: per-file cap. Prevents OOM via large sparse files
/// or malicious plugins. 10MB matches the cap the handler uses
/// for serving (`MAX_PLUGIN_ASSET_BYTES`) — consistent.
pub(crate) const MAX_HASH_FILE_BYTES: u64 = 10 * 1024 * 1024;

/// B6: combined cap for the entire plugin. Prevents OOM via plugins
/// with many large files. 50MB sufficient for reasonable UI plugins
/// (the current rag spike weighs ~10KB).
pub(crate) const MAX_HASH_TOTAL_BYTES: u64 = 50 * 1024 * 1024;

/// Positive cache entry. Stores the hash computed at the last successful
/// verification for observability (logs, metrics, future fingerprint-based ADR).
/// C01+B5: NOT used as an invalidation key — the hash is always re-computed
/// from an atomic snapshot of open fds.
#[derive(Clone, Debug)]
pub(crate) struct CacheEntry {
    pub(crate) known_hash: String,
}

pub(crate) const VERIFIED_LRU_CAP: usize = 500;

static VERIFIED_PLUGINS: OnceLock<Mutex<LruCache<String, CacheEntry>>> = OnceLock::new();

pub(crate) fn verified_plugins() -> &'static Mutex<LruCache<String, CacheEntry>> {
    VERIFIED_PLUGINS.get_or_init(|| {
        // VERIFIED_LRU_CAP is const=500 > 0 — unwrap_or safe with minimal fallback
        let cap = NonZeroUsize::new(VERIFIED_LRU_CAP).unwrap_or(NonZeroUsize::MIN);
        Mutex::new(LruCache::new(cap))
    })
}

/// Sorted recursive path walk. Follows only regular files (ignores
/// symlinks and other types to prevent loops and attacks).
pub(crate) fn walk_plugin_files_sorted(root: &Path) -> Result<Vec<PathBuf>, u16> {
    let mut out = Vec::new();
    walk_rec(root, &mut out)?;
    out.sort();
    Ok(out)
}

fn walk_rec(dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), u16> {
    let entries = std::fs::read_dir(dir).map_err(|_| 500_u16)?;
    for entry in entries {
        let entry = entry.map_err(|_| 500_u16)?;
        let ty = entry.file_type().map_err(|_| 500_u16)?;
        let path = entry.path();
        if ty.is_dir() {
            walk_rec(&path, out)?;
        } else if ty.is_file() {
            out.push(path);
        }
        // symlinks and other types: explicit skip
    }
    Ok(())
}

/// Canonicalizes `manifest.toml` for hashing: parse, remove [integrity],
/// re-serialize. This breaks the hash↔manifest circularity.
pub(crate) fn canonicalize_manifest_for_hash(content: &str) -> Result<Vec<u8>, u16> {
    let mut parsed: toml::Value = toml::from_str(content).map_err(|_| 403_u16)?;
    if let toml::Value::Table(ref mut table) = parsed {
        table.remove("integrity");
    }
    let serialized = toml::to_string(&parsed).map_err(|_| 403_u16)?;
    Ok(serialized.into_bytes())
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

/// Computes SHA-256 of a plugin folder.
///
/// Public to allow use from the auxiliary binary `scripts/plugin-hash` (build-time
/// pre-manifest). At runtime (handler), use `verify_and_load_plugin_asset`
/// which eliminates the TOCTOU verify→serve (B5 Sprint 0.18).
///
/// `plugin_dir`: plugin directory (e.g. `plugins-dev/rag/`).
/// Returns a 64-char hex string or `Err(u16)` with HTTP status.
pub fn compute_plugin_hash(plugin_dir: &Path) -> Result<String, u16> {
    let files = walk_plugin_files_sorted(plugin_dir)?;
    let mut hasher = Sha256::new();
    let mut total_bytes_read: u64 = 0;
    for abs_path in &files {
        let rel_path = abs_path.strip_prefix(plugin_dir).map_err(|_| 500_u16)?;
        // forward-slash cross-platform
        let rel_str = rel_path.to_string_lossy().replace('\\', "/");

        // B6: per-file cap + combined cap
        let f = std::fs::File::open(abs_path).map_err(|_| 500_u16)?;
        let mut raw_bytes = Vec::new();
        f.take(MAX_HASH_FILE_BYTES + 1)
            .read_to_end(&mut raw_bytes)
            .map_err(|_| 500_u16)?;
        if raw_bytes.len() as u64 > MAX_HASH_FILE_BYTES {
            tracing::warn!(
                file = %rel_str,
                max = MAX_HASH_FILE_BYTES,
                "plugin hash: file exceeds per-file cap"
            );
            return Err(413);
        }
        total_bytes_read += raw_bytes.len() as u64;
        if total_bytes_read > MAX_HASH_TOTAL_BYTES {
            tracing::warn!(
                total = total_bytes_read,
                max = MAX_HASH_TOTAL_BYTES,
                "plugin hash: total bytes exceed combined cap"
            );
            return Err(413);
        }

        let bytes: Vec<u8> = if rel_str == "manifest.toml" {
            let content = std::str::from_utf8(&raw_bytes).map_err(|_| 403_u16)?;
            canonicalize_manifest_for_hash(content)?
        } else {
            raw_bytes
        };

        hasher.update(rel_str.as_bytes());
        hasher.update(b"\n");
        hasher.update(bytes.len().to_string().as_bytes());
        hasher.update(b"\n");
        hasher.update(&bytes);
    }
    Ok(hex_encode(&hasher.finalize()))
}

/// Reads the expected hash from a plugin's manifest.toml.
/// Returns Err(403) if manifest is missing/invalid, field absent or empty.
///
/// NOTE: this function reads the manifest from the FS. On the security
/// verify+serve path (B5), use `read_expected_hash_from_snapshot` which
/// operates on bytes already in memory from the atomic snapshot.
pub(crate) fn read_expected_hash(plugin_dir: &Path) -> Result<String, u16> {
    let manifest_path = plugin_dir.join("manifest.toml");
    let content = std::fs::read_to_string(&manifest_path).map_err(|_| 403_u16)?;
    parse_expected_hash_from_manifest_str(&content)
}

/// Extracts the `integrity.sha256` field from an in-memory manifest.toml.
/// Shared helper between `read_expected_hash` (FS) and
/// `read_expected_hash_from_snapshot` (memory) to avoid duplicating
/// parsing + validation logic.
fn parse_expected_hash_from_manifest_str(content: &str) -> Result<String, u16> {
    let parsed: toml::Value = toml::from_str(content).map_err(|_| 403_u16)?;
    let hash = parsed
        .get("integrity")
        .and_then(|i| i.get("sha256"))
        .and_then(|v| v.as_str())
        .ok_or(403_u16)?;
    if hash.is_empty() || hash.len() != 64 {
        return Err(403);
    }
    Ok(hash.to_string())
}

/// Extracts the expected hash from manifest bytes already in memory (B5 snapshot).
/// Avoids a second FS read that would introduce a secondary TOCTOU.
fn read_expected_hash_from_snapshot(
    file_contents: &[(PathBuf, Vec<u8>)],
    plugin_dir: &Path,
) -> Result<String, u16> {
    for (path, bytes) in file_contents {
        let rel = path.strip_prefix(plugin_dir).map_err(|_| 500_u16)?;
        let rel_str = rel.to_string_lossy().replace('\\', "/");
        if rel_str == "manifest.toml" {
            let content = std::str::from_utf8(bytes).map_err(|_| 403_u16)?;
            return parse_expected_hash_from_manifest_str(content);
        }
    }
    Err(403) // manifest.toml not found in snapshot
}

/// B5 Sprint 0.18: **verify + load in one atomic snapshot**.
///
/// Eliminates the TOCTOU verify→serve window that the C01 fix left open. Pattern:
///
/// 1. Walk plugin_dir → list of paths
/// 2. Open ALL `std::fs::File` handles BEFORE any read
/// 3. Read ALL content from the open handles (snapshot)
///    - Unix: fd keeps the inode alive against external rename/unlink/write
///    - Windows: `File::open` by default allows FILE_SHARE_READ+DELETE;
///      an attacker CANNOT open with exclusive GENERIC_WRITE while we hold READ,
///      implicit defense
/// 4. Compute hash FROM THE IN-MEMORY BYTES
/// 5. Compare with expected (extracted from manifest in the same snapshot)
/// 6. If OK, return the bytes of `requested_rel_path` FROM THE SAME snapshot —
///    the caller's handler never goes back to the FS
///
/// **Key invariant:** the bytes served are the same ones that passed the hash.
/// An attacker replacing content between walk and open fails the hash (Err 403);
/// if replaced after open, the fds already have the previous inode pinned and
/// the content seen is the snapshot.
///
/// Parameters:
/// - `plugin_id`: plugin identifier (e.g. `"rag"`)
/// - `plugins_root`: plugin root directory (e.g. `plugins-dev/`)
/// - `requested_rel_path`: relative path of the requested file (e.g. `"ui/index.html"`)
///
/// Returns:
/// - `Ok(Vec<u8>)` with the verified file bytes
/// - `Err(403)` on integrity mismatch or invalid manifest
/// - `Err(404)` if `requested_rel_path` does not exist in the plugin
/// - `Err(413)` if any file or total exceeds the caps
/// - `Err(500)` for I/O errors or poisoned paths
///
/// When `STRICT_INTEGRITY = false` (dev mode): skip integrity, read the
/// requested file without verification (friction-free edit loop).
/// B5: Open ALL fds BEFORE any read (TOCTOU elimination).
/// Unix guarantees inode alive for open fds against external rename/unlink/write.
fn open_atomic_snapshot(
    plugin_id: &str,
    files: &[PathBuf],
) -> Result<Vec<(PathBuf, std::fs::File)>, u16> {
    let mut handles = Vec::with_capacity(files.len());
    for abs_path in files {
        match std::fs::File::open(abs_path) {
            Ok(f) => handles.push((abs_path.clone(), f)),
            Err(_) => {
                tracing::warn!(
                    plugin_id = %plugin_id,
                    "plugin integrity: could not open file during snapshot"
                );
                return Err(500);
            }
        }
    }
    Ok(handles)
}

/// B6: Read all content from open handles with per-file and total caps.
fn read_snapshot_with_caps(
    handles: Vec<(PathBuf, std::fs::File)>,
    plugin_dir: &Path,
) -> Result<Vec<(PathBuf, Vec<u8>)>, u16> {
    let mut file_contents = Vec::with_capacity(handles.len());
    let mut total_bytes_read: u64 = 0;
    for (path, f) in handles {
        let mut buf = Vec::new();
        (&f).take(MAX_HASH_FILE_BYTES + 1)
            .read_to_end(&mut buf)
            .map_err(|_| 500_u16)?;
        if buf.len() as u64 > MAX_HASH_FILE_BYTES {
            let rel_str = path
                .strip_prefix(plugin_dir)
                .map(|p| p.to_string_lossy().replace('\\', "/"))
                .unwrap_or_default();
            tracing::warn!(
                file = %rel_str,
                max = MAX_HASH_FILE_BYTES,
                "plugin snapshot: file exceeds per-file cap"
            );
            return Err(413);
        }
        total_bytes_read += buf.len() as u64;
        if total_bytes_read > MAX_HASH_TOTAL_BYTES {
            tracing::warn!(
                total = total_bytes_read,
                max = MAX_HASH_TOTAL_BYTES,
                "plugin snapshot: total bytes exceed combined cap"
            );
            return Err(413);
        }
        file_contents.push((path, buf));
    }
    Ok(file_contents)
}

/// Update LRU cache for observability (not a decision path).
fn update_verification_cache(plugin_id: &str, actual_hash: String) {
    let mut guard = match verified_plugins().lock() {
        Ok(g) => g,
        Err(poison) => {
            tracing::warn!("VERIFIED_PLUGINS mutex poisoned — recovering");
            poison.into_inner()
        }
    };
    if let Some(prev) = guard.peek(plugin_id) {
        if prev.known_hash != actual_hash {
            tracing::debug!(
                plugin_id = %plugin_id,
                "plugin known_hash rotated between verifies"
            );
        }
    }
    guard.put(
        plugin_id.to_string(),
        CacheEntry { known_hash: actual_hash },
    );
}

pub(crate) fn verify_and_load_plugin_asset(
    plugin_id: &str,
    plugins_root: &Path,
    requested_rel_path: &str,
) -> Result<Vec<u8>, u16> {
    let plugin_dir = plugins_root.join(plugin_id);

    // Dev mode: skip integrity, read directly from FS
    if !STRICT_INTEGRITY {
        let canon_file = plugin_dir.join(requested_rel_path);
        return std::fs::read(&canon_file).map_err(|_| 404_u16);
    }

    // ADR-0014 v2: if manifest uses per-file format, use the cheaper per-file path.
    let manifest_path = plugin_dir.join("manifest.toml");
    if let Ok(content) = std::fs::read_to_string(&manifest_path) {
        if let IntegrityFormat::PerFile(_) = detect_integrity_format(&content) {
            let files_map = verify_manifest_integrity(&plugin_dir)?;
            return verify_and_load_file_asset_per_file(&plugin_dir, requested_rel_path, &files_map);
        }
    }

    // --- Atomic snapshot: walk → open → read → hash → verify → serve ---
    let files = walk_plugin_files_sorted(&plugin_dir)?;
    if files.is_empty() {
        tracing::warn!(plugin_id = %plugin_id, "plugin dir is empty or missing");
        return Err(403);
    }

    let handles = open_atomic_snapshot(plugin_id, &files)?;
    let file_contents = read_snapshot_with_caps(handles, &plugin_dir)?;

    let actual_hash = compute_hash_from_snapshot(&file_contents, &plugin_dir)?;
    let expected_hash = read_expected_hash_from_snapshot(&file_contents, &plugin_dir)?;

    if actual_hash != expected_hash {
        tracing::error!(plugin_id = %plugin_id, "plugin integrity check failed: hash mismatch");
        return Err(403);
    }

    update_verification_cache(plugin_id, actual_hash);

    // Serve the requested file FROM THE SAME snapshot (no FS read)
    for (abs_path, bytes) in &file_contents {
        let rel = abs_path.strip_prefix(&plugin_dir).map_err(|_| 500_u16)?;
        let rel_str = rel.to_string_lossy().replace('\\', "/");
        if rel_str == requested_rel_path {
            return Ok(bytes.clone());
        }
    }

    tracing::debug!(
        plugin_id = %plugin_id,
        requested = %requested_rel_path,
        "requested file not found in plugin snapshot"
    );
    Err(404)
}

/// Computes SHA-256 of an in-memory plugin snapshot.
/// Same algorithm as `compute_plugin_hash` but operates on bytes
/// in memory to avoid re-reading the FS (B5).
fn compute_hash_from_snapshot(
    file_contents: &[(PathBuf, Vec<u8>)],
    plugin_dir: &Path,
) -> Result<String, u16> {
    let mut hasher = Sha256::new();
    for (abs_path, raw_bytes) in file_contents {
        let rel_path = abs_path.strip_prefix(plugin_dir).map_err(|_| 500_u16)?;
        let rel_str = rel_path.to_string_lossy().replace('\\', "/");

        let bytes: Vec<u8> = if rel_str == "manifest.toml" {
            let content = std::str::from_utf8(raw_bytes).map_err(|_| 403_u16)?;
            canonicalize_manifest_for_hash(content)?
        } else {
            raw_bytes.clone()
        };

        hasher.update(rel_str.as_bytes());
        hasher.update(b"\n");
        hasher.update(bytes.len().to_string().as_bytes());
        hasher.update(b"\n");
        hasher.update(&bytes);
    }
    Ok(hex_encode(&hasher.finalize()))
}

/// Verifies plugin integrity by re-computing SHA-256 on every request.
/// Returns Ok(()) if the hash matches the expected value, Err(403) on failure.
///
/// **DEPRECATED at runtime:** this function performs an isolated verify without
/// retaining the bytes, so if the handler subsequently does `File::open + read`
/// to serve, it introduces TOCTOU verify→serve (B5 security review,
/// 70.5% hit-rate). Use `verify_and_load_plugin_asset` which does verify + load
/// in one atomic snapshot.
///
/// Kept for compatibility with the HEAD path (does not serve body, only
/// Content-Length from metadata) and test cases that do not need the bytes.
///
/// If `STRICT_INTEGRITY = false`, always Ok(()) (layered defense off).
pub(crate) fn verify_plugin_integrity(plugin_id: &str, plugins_root: &Path) -> Result<(), u16> {
    if !STRICT_INTEGRITY {
        return Ok(());
    }
    let plugin_dir = plugins_root.join(plugin_id);

    // Re-compute hash on every request (C01 semantic).
    let expected = read_expected_hash(&plugin_dir);
    let actual = compute_plugin_hash(&plugin_dir);

    let result: Result<String, u16> = match (expected, actual) {
        (Ok(e), Ok(a)) if e == a => Ok(a),
        (Err(s), _) | (_, Err(s)) => Err(s),
        _ => {
            tracing::error!(
                plugin_id = %plugin_id,
                "plugin integrity check failed: hash mismatch"
            );
            Err(403)
        }
    };

    match result {
        Ok(known_hash) => {
            let mut guard = match verified_plugins().lock() {
                Ok(g) => g,
                Err(poison) => {
                    tracing::warn!("VERIFIED_PLUGINS mutex poisoned — recovering");
                    poison.into_inner()
                }
            };
            if let Some(prev) = guard.peek(plugin_id) {
                if prev.known_hash != known_hash {
                    tracing::debug!(
                        plugin_id = %plugin_id,
                        "plugin known_hash rotated between verifies"
                    );
                }
            }
            guard.put(plugin_id.to_string(), CacheEntry { known_hash });
            Ok(())
        }
        Err(status) => Err(status),
    }
}

// ─── ADR-0014 v2 — Per-file integrity ────────────────────────────────────────

/// Per-file integrity format: `[integrity].manifest_sha256` + `[integrity.files]`.
pub struct ManifestFiles {
    /// rel_path (forward-slash) → sha256_hex
    pub files: HashMap<String, String>,
}

/// Which integrity format a manifest uses.
pub enum IntegrityFormat {
    /// ADR-0014 v2: per-file hashes + manifest_sha256.
    PerFile(ManifestFiles),
    /// ADR-0014 v1 (legacy): single directory hash in `[integrity].sha256`.
    DirectoryHash(String),
}

/// SHA-256 of a byte slice, returned as 64-char lowercase hex.
pub fn compute_file_hash(data: &[u8]) -> String {
    hex_encode(&Sha256::digest(data))
}

/// Canonicalise `manifest.toml` for hashing: parse TOML, remove
/// `[integrity].manifest_sha256` (the field that would contain the result),
/// re-serialise deterministically (toml sorts keys alphabetically), then SHA-256.
///
/// This breaks the circularity: the hash does not depend on its own stored value.
pub fn compute_manifest_hash(content: &str) -> Result<String, u16> {
    let mut parsed: toml::Value = toml::from_str(content).map_err(|_| 403_u16)?;
    if let toml::Value::Table(ref mut root) = parsed {
        if let Some(toml::Value::Table(ref mut integrity)) = root.get_mut("integrity") {
            integrity.remove("manifest_sha256");
        }
    }
    let serialised = toml::to_string(&parsed).map_err(|_| 403_u16)?;
    Ok(hex_encode(&Sha256::digest(serialised.as_bytes())))
}

/// Detect whether a manifest uses the per-file format (v2) or the legacy
/// directory-hash format (v1). Returns `DirectoryHash` for legacy manifests
/// that have `[integrity].sha256` but no `[integrity].manifest_sha256`.
pub fn detect_integrity_format(content: &str) -> IntegrityFormat {
    let Ok(parsed) = toml::from_str::<toml::Value>(content) else {
        return IntegrityFormat::DirectoryHash(String::new());
    };
    let integrity = match parsed.get("integrity") {
        Some(toml::Value::Table(t)) => t,
        _ => return IntegrityFormat::DirectoryHash(String::new()),
    };

    // v2 format: has manifest_sha256 key
    if integrity.contains_key("manifest_sha256") {
        let files_map = integrity
            .get("files")
            .and_then(|v| v.as_table())
            .map(|t| {
                t.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect::<HashMap<_, _>>()
            })
            .unwrap_or_default();
        return IntegrityFormat::PerFile(ManifestFiles { files: files_map });
    }

    // v1 legacy format: has sha256 key
    let hash = integrity
        .get("sha256")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    IntegrityFormat::DirectoryHash(hash)
}

/// Load and verify the manifest for per-file mode.
/// Returns the `HashMap<rel_path, sha256_hex>` if `manifest_sha256` is valid.
/// Returns `Err(403)` if manifest is missing, invalid, or tampered.
pub fn verify_manifest_integrity(plugin_dir: &Path) -> Result<HashMap<String, String>, u16> {
    let manifest_path = plugin_dir.join("manifest.toml");
    let content = std::fs::read_to_string(&manifest_path).map_err(|_| 403_u16)?;

    let IntegrityFormat::PerFile(manifest_files) = detect_integrity_format(&content) else {
        return Err(403); // caller should only call this for per-file manifests
    };

    // Verify manifest_sha256
    let parsed: toml::Value = toml::from_str(&content).map_err(|_| 403_u16)?;
    let stored_hash = parsed
        .get("integrity")
        .and_then(|i| i.get("manifest_sha256"))
        .and_then(|v| v.as_str())
        .ok_or(403_u16)?;

    if stored_hash.len() != 64 {
        return Err(403);
    }

    let actual_hash = compute_manifest_hash(&content)?;
    if actual_hash != stored_hash {
        return Err(403);
    }

    Ok(manifest_files.files)
}

/// Load a single file asset with per-file integrity verification (B5 atomic per-file).
///
/// Opens fd(manifest) and fd(requested_file) BEFORE any read — eliminates TOCTOU.
/// Returns `Ok(bytes)` only if the bytes match the hash in the verified manifest.
fn verify_and_load_file_asset_per_file(
    plugin_dir: &Path,
    requested_rel_path: &str,
    files_map: &HashMap<String, String>,
) -> Result<Vec<u8>, u16> {
    // Validate path (no traversal, no absolute)
    if requested_rel_path.contains("..") || requested_rel_path.starts_with('/') {
        return Err(403);
    }

    let expected_hash = files_map.get(requested_rel_path).ok_or(404_u16)?;
    if expected_hash.len() != 64 {
        return Err(403);
    }

    let file_path = plugin_dir.join(requested_rel_path);

    // Atomic: open fd BEFORE read (inode pinned against external rename/unlink)
    let f = std::fs::File::open(&file_path).map_err(|_| 404_u16)?;
    let mut buf = Vec::new();
    (&f).take(MAX_HASH_FILE_BYTES + 1)
        .read_to_end(&mut buf)
        .map_err(|_| 500_u16)?;
    drop(f); // fd released after read

    if buf.len() as u64 > MAX_HASH_FILE_BYTES {
        return Err(413);
    }

    let actual_hash = compute_file_hash(&buf);
    if actual_hash != *expected_hash {
        return Err(403);
    }

    Ok(buf)
}

/// Test helper: compute per-file hashes for all files in a plugin and write
/// a new manifest with `[integrity].manifest_sha256` + `[integrity.files]`.
#[cfg(test)]
pub fn write_per_file_manifest(root: &Path, plugin_id: &str) -> Result<(), String> {
    let plugin_dir = root.join(plugin_id);
    let files = walk_plugin_files_sorted(&plugin_dir).map_err(|e| format!("walk: {e}"))?;

    let mut file_hashes = toml::map::Map::new();
    for abs_path in &files {
        let rel = abs_path.strip_prefix(&plugin_dir).map_err(|_| "strip_prefix")?;
        let rel_str = rel.to_string_lossy().replace('\\', "/");
        if rel_str == "manifest.toml" { continue; }
        let content = std::fs::read(abs_path).map_err(|e| format!("read: {e}"))?;
        file_hashes.insert(rel_str, toml::Value::String(compute_file_hash(&content)));
    }

    // Build the TOML value tree (without manifest_sha256 first)
    let mut integrity = toml::map::Map::new();
    integrity.insert("manifest_sha256".into(), toml::Value::String("placeholder".into()));
    integrity.insert("files".into(), toml::Value::Table(file_hashes));

    let mut plugin = toml::map::Map::new();
    plugin.insert("id".into(), toml::Value::String(plugin_id.into()));
    plugin.insert("version".into(), toml::Value::String("0.1.0".into()));

    let mut root_map = toml::map::Map::new();
    root_map.insert("plugin".into(), toml::Value::Table(plugin));
    root_map.insert("integrity".into(), toml::Value::Table(integrity));

    let draft_str = toml::to_string(&toml::Value::Table(root_map.clone()))
        .map_err(|e| format!("toml::to_string draft: {e}"))?;

    // Compute hash of the draft (placeholder value is excluded by compute_manifest_hash)
    let manifest_hash = compute_manifest_hash(&draft_str).map_err(|e| format!("hash: {e}"))?;

    // Replace placeholder with real hash
    if let toml::Value::Table(ref mut t) = root_map.get_mut("integrity").unwrap() {
        t.insert("manifest_sha256".into(), toml::Value::String(manifest_hash));
    }
    let final_str = toml::to_string(&toml::Value::Table(root_map))
        .map_err(|e| format!("toml::to_string final: {e}"))?;

    std::fs::write(plugin_dir.join("manifest.toml"), final_str)
        .map_err(|e| format!("write: {e}"))?;
    Ok(())
}
