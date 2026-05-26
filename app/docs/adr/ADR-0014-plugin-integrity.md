# ADR-0014: Plugin integrity — SHA-256 ACTIU (Sprint 0.15)

**Date:** 2026-04-18 (v1 Sprint 0.15) / 2026-04-21 (v2 C01 security fix) / 2026-04-21 (v3 B5 atomic snapshot)
**Status:** Accepted — **Active** (Sprint 0.18, atomic snapshot verify+load, v0.1.2-fase0-security-v2)
**Decided by:** Jordi Goy
**Previous status:** stub / deferred (Sprint 0.14 #T6)
**Revisions:**
- **v2 2026-04-21** — TOCTOU mtime cache bypass detectat per auditoria de seguretat (finding C01 consolidat, 3/3 verificacions + verificació empírica APFS). L'algoritme original basat en `CacheEntry { mtime: SystemTime }` era bypassable per edició in-place d'un fitxer existent (dir mtime no canvia). Substituït per re-hash a cada request.
- **v3 2026-04-21 Sprint 0.18** — TOCTOU **verify→serve double-read** detectat per red team (finding B5 consolidat, PoC empíric **70.5% hit-rate**). El fix v2 tapava el TOCTOU cache però deixava obert un segon TOCTOU: el handler feia `verify_plugin_integrity` (lectura 1 del FS per hashar) i després `File::open + read_to_end` (lectura 2 per servir). Un atacant local amb write access a `plugins-dev/<id>/` podia substituir contingut entre les dues lectures → el serve retornava bytes diferents dels que havien passat el hash. **Substituït per "atomic snapshot via open fd"**: la nova funció `verify_and_load_plugin_asset` obre TOTS els fds del plugin abans de qualsevol read, llegeix des dels fds (Unix garanteix inode viva contra rename/unlink/write externs), hasha des del snapshot en memòria, i retorna els bytes del fitxer requested DES DEL MATEIX snapshot. Els bytes servits són, per invariant, els bytes que van passar el hash. Verificat amb mutation test empíric (pattern pre-fix reintroduït → test detecta 251/500 bypasses; pattern post-fix → 0/500).

## Context

The `plugin://` URI scheme (ADR-0009) serves arbitrary files under `<plugins_root>/<plugin_id>/`. Without integrity verification, a local attacker who can modify the installed plugin directory can inject exfiltration JS, overwrite legitimate assets, or tamper with the manifest. The host would serve the compromised file without warning.

## Decision

**Enforce SHA-256 integrity on every plugin request using an atomic FS snapshot: open all plugin files' fds before any read, hash from the in-memory snapshot, compare against `[integrity].sha256` in the manifest, and serve the requested file's bytes FROM THE SAME snapshot. Any tampering between walk and open (or between open and read) is either absorbed by the fd's inode-pinning semantics or causes a hash mismatch (Err 403). The served bytes are, by invariant, the bytes that passed the hash. ~10 ms cost per request in exchange for tamper-evident delivery even under local in-place attacks and under verify→serve race attacks.**

### Scope (option A — whole plugin folder)

1. **Hash target:** the entire plugin folder (`<plugins_root>/<plugin_id>/`), not just `ui/`. This protects the manifest, icons, and any auxiliary files.
2. **Manifest canonicalization:** when hashing `manifest.toml`, the `[integrity]` section is stripped and the TOML is re-serialized canonically. This breaks the hash↔manifest circularity (the hash cannot depend on itself).
3. **Feature flag:** `STRICT_INTEGRITY: bool = true` at the top of `src-tauri/src/integrity.rs` (`cfg(not(debug_assertions))`). Dev builds short-circuit to `Ok(())` to avoid friction each edit (F024); release builds enforce hash match.
4. **No invalidation cache on the decision path.** `VERIFIED_PLUGINS: LruCache<String, CacheEntry { known_hash }>` now stores the last successful hash **exclusively for observability** (logs, metrics, future fingerprint ADR). The verifier never consults the cache before re-hashing; a stale cache cannot serve a tampered plugin.
5. **Failed verifications are not cached** (F007 preserved) — transient errors self-recover on the next request.

### Why re-hash every request (C01 rationale)

The previous algorithm used `CacheEntry { mtime: SystemTime }` with `plugin_dir_mtime(plugin_dir)` as the invalidation key. This was empirically proven wrong (APFS, verified 2026-04-20 + 2026-04-21) and is identical on ext4/NTFS/HFS+:

- **POSIX semantics:** `stat(2)` of a directory only updates `mtime` when entries are added, removed, or renamed. Editing the **contents** of an existing child file does not touch the parent dir's mtime.
- **Attack vector:** a local adversary with write access to `plugins/<id>/ui/*.html` could tamper with a previously verified plugin; on the next `plugin://` request, the cache saw the old mtime unchanged and served the manipulated bytes without re-hashing.
- **Cost analysis:** a typical plugin is <2 MB; SHA-256 on a modern CPU runs at ~500 MB/s → ~4 ms per plugin even at the bound, commonly <1 ms. The promised "O(1) after first request" saved well under 10 ms per request but broke the tamper-evidence promise. For a framework with strong security goals, this trade is unacceptable.

### Why atomic snapshot verify+load (B5 rationale — Sprint 0.18)

The v2 fix re-hashed every request but kept `verify` and `serve` as two separate FS reads:

```rust
// v2 handler (vulnerable):
verify_plugin_integrity(&plugin_id, &plugins_root)?;        // Read 1: walks + hashes
// ... small window ...
let bytes = std::fs::read(&canon_file)?;                     // Read 2: serves
return build_response(bytes);
```

Red team (2026-04-21) crafted a spin-write attacker thread that alternated the file's content between "benign" and "malicious" at microsecond intervals. Over 556 requests, **392 (70.5%)** returned malicious bytes that the hash had **not** just verified. The attacker simply had to keep writing; the verify→serve gap was ~µs but reachable by any concurrent writer.

The v3 algorithm closes this by reading **once** under an atomic snapshot:

```rust
// v3 (atomic snapshot):
// Phase 1: open all plugin file descriptors before any read
let files = walk_plugin_files_sorted(&plugin_dir)?;
let handles: Vec<(PathBuf, File)> = files.iter().map(|p| (p, File::open(p))).collect();
// From here, Unix fd semantics pin the inode: rename/unlink/write from another
// process creates NEW inodes; our fds keep reading from the pre-tamper one.

// Phase 2: read all content from the pinned fds (the snapshot)
let contents: Vec<(PathBuf, Vec<u8>)> = handles.into_iter().map(|(p, f)| read_to_end(f)).collect();

// Phase 3: hash from memory + compare with manifest hash from the same snapshot
let actual = hash_from_snapshot(&contents);
let expected = read_expected_hash_from_snapshot(&contents);
if actual != expected { return Err(403); }

// Phase 4: serve the requested file's bytes FROM the snapshot (never re-open from FS)
return Ok(contents.find(requested_rel_path)?.bytes);
```

**Invariant:** the bytes returned are **byte-for-byte identical** to the bytes that produced the hash. Any tampering during walk causes the hash to mismatch; any tampering between open and read is absorbed by the fd's inode-pinning (Unix) or by `File::open`'s default sharing mode (Windows). No intermediate read of the FS occurs between verify and serve.

**Cost:** the snapshot reads every file once (same I/O as the old verify). The handler no longer re-opens the requested file — net I/O is identical. Memory cost: all plugin bytes held transiently during the snapshot; bounded by `MAX_HASH_FILE_BYTES = 10 MB` per file and `MAX_HASH_TOTAL_BYTES = 50 MB` combined (B6 Sprint 0.18).

**Mutation test (release-only):** `b5_verify_and_load_atomic_snapshot_no_bypass` spawns a spin-write attacker, issues 500 verify+load requests, and asserts **zero** returns with bytes mismatching the hash. Re-introducing the pre-fix pattern (separate verify + separate read with a 100 µs sleep) causes the test to fail with 251/500 bypasses — confirming the test is not theater.

### Alternative considered but rejected (Option B — fingerprint cache)

`CacheEntry { fingerprint: Vec<(PathBuf, SystemTime, u64)> }` storing `(path, mtime, size)` tuples for every file under the subtree. This would keep O(N files) rather than O(total bytes) on cache hits. Rejected for v0.1.1:

- **Complexity overhead:** walk + stat on every request still costs I/O; the savings vs full hash are small for the plugin sizes used (median < 500 KB).
- **Still metadata-trust:** size + mtime heuristics are FS-specific. A tool that preserves size and restores mtime (`touch -r`, backup utilities) could recreate a fingerprint match with tampered bytes.
- **Future path:** if profiling on real clones shows the 10 ms dominates a hot path, a fingerprint cache **with a periodic full re-hash** (hybrid) can be introduced in a follow-up ADR. Until proven necessary, we err on the side of correctness.

## Hash algorithm

**SHA-256 over the plugin folder**, with a deterministic serialization:

```
for each file under <plugin_dir>/, ordered by canonical relative path (forward-slash):
    if file == "manifest.toml":
        parsed = toml::from_str(content)
        parsed.remove("integrity")
        bytes = toml::to_string(parsed).as_bytes()
    else:
        bytes = file_content_bytes
    hasher.update(rel_path + "\n")
    hasher.update(str(len(bytes)) + "\n")
    hasher.update(bytes)
return hex(hasher.finalize())
```

Symlinks and non-regular files are skipped (never followed during walk — prevents loops and escape attacks).

## Manifest format

```toml
[plugin]
id = "rag"
version = "0.1.0"
# ...

[integrity]
sha256 = "00ad7711022740e610224eea59913e107547973f9aa66d9f64daa06bdb07488d"
```

The `sha256` field is **required** when `STRICT_INTEGRITY=true`. Empty or wrong-length values return HTTP 403.

## Implementation

### Rust functions

- **`verify_and_load_plugin_asset(plugin_id, plugins_root, requested_rel_path) -> Result<Vec<u8>, u16>`** (v3) — primary entry point for the `plugin://` GET path. Atomic snapshot (walk → open all fds → read all bytes → hash → verify → return requested bytes from snapshot). Replaces the old `verify_plugin_integrity` + `File::open + read_to_end` pattern.
- `compute_plugin_hash(plugin_dir: &Path) -> Result<String, u16>` — walks + hashes from FS (re-reads the fs). Used at build time for `scripts/plugin-hash` CLI and for `HEAD` requests (no body needed).
- `read_expected_hash(plugin_dir: &Path) -> Result<String, u16>` — reads `manifest.toml` from FS, extracts `[integrity].sha256`, validates length=64. Shared with the CLI; runtime verify uses the snapshot variant.
- `verify_plugin_integrity(plugin_id, plugins_root) -> Result<(), u16>` — v2 FS re-read path, **deprecated for GET** (keeps TOCTOU gap with subsequent reads). Retained for `HEAD` requests which do not read the body.
- `canonicalize_manifest_for_hash(content: &str) -> Result<Vec<u8>, u16>` — TOML parse, strip integrity, re-serialize.
- `walk_plugin_files_sorted(root: &Path) -> Result<Vec<PathBuf>, u16>` — recursive walk with deterministic ordering.

**Constants:**
- `MAX_HASH_FILE_BYTES: u64 = 10 * 1024 * 1024` (10 MB per file)
- `MAX_HASH_TOTAL_BYTES: u64 = 50 * 1024 * 1024` (50 MB combined per plugin)

Both caps trigger `Err(413)` to prevent OOM via sparse files or malicious plugin layouts.

### Handler integration

The handler routes `HEAD` and `GET` differently:

- **`HEAD`** (RFC 9110 §9.3.2): calls `verify_plugin_integrity` (no body I/O saved) + `std::fs::metadata` for `Content-Length`. Integrity is still enforced to avoid making `HEAD` an oracle of file existence that bypasses integrity.
- **`GET`** (the hot path): calls `verify_and_load_plugin_asset` once — which returns the verified bytes directly. No second `File::open`, no `read_to_end`, no TOCTOU gap.

The LRU observability entry is refreshed on successful GET verify, and `tracing::debug!` emits a signal when the hash rotates between verifies (expected in dev flows, noteworthy in release).

### Dev tools

- `src-tauri/src/bin/plugin-hash.rs` — binary: `cargo run --bin plugin-hash -- <dir>` prints the hash.
- `scripts/compute-plugin-hash.sh` — wrapper: `./scripts/compute-plugin-hash.sh plugins-dev/rag` prints the hash from the repo root.

### Dependencies added

```toml
sha2 = "0.10"
toml = "0.8"
```

## Alternatives considered (and rejected)

| Option | Motiu descart |
|---|---|
| Hash only `ui/` subtree (option B) | Misses tampering of manifest (e.g. changing trust level, capabilities). Option A is strictly stronger. |
| Ed25519 signatures | Overkill at starter phase; requires key management. Deferred to marketplace phase. |
| Merkle tree per file | 10× more complex; useful for partial verification but irrelevant to "did anyone touch this plugin". |
| Skip integrity entirely | Unacceptable: local tampering undetected. |

## Consequences

### Positives
- **Tamper-evident on every request.** Any tampering (content, manifest logic, auxiliary files), including in-place edits of existing files, is detected the moment the plugin URL is next requested — no "wait for dir mtime to change" window.
- **No TOCTOU surface between verify and the serve** (C01 + B5 closed). The verifier and the serve share an atomic FS snapshot; the bytes returned to the webview are, by invariant, the bytes that produced the matching hash.
- **Fd-pinned snapshot resists concurrent writers.** Unix file descriptors held open keep the inode alive against `rename`/`unlink`/write-by-another-fd semantics; Windows `File::open` defaults deny exclusive-write to other processes while the fd is held. No intermediate FS re-read occurs.
- Hash is stable across formatting changes (comments, whitespace) thanks to canonicalization.
- Starter format is forward-compatible with marketplace signatures (add `[integrity].ed25519` later).
- Observability cache still emits `tracing::debug!` when a plugin's known_hash rotates — useful for detecting accidental drift between `manifest.toml` and disk in dev, or post-update in release.

### Negatives
- **~10 ms per request latency** (SHA-256 of a <2 MB plugin on modern CPU, commonly <5 ms). Mitigations: plugins are served by an 8-thread bounded pool (S03 F004) so concurrent verifies parallelize; requests on the hot path (`/ui/index.html` first load) amortize well under typical Wi-Fi round-trips.
- **Memory cost transient during snapshot.** v3 holds every plugin file's bytes in memory until hash+verify+serve completes. `MAX_HASH_FILE_BYTES = 10 MB` per file and `MAX_HASH_TOTAL_BYTES = 50 MB` per plugin cap the worst case. A plugin with 500 × 100 KB assets would allocate ~50 MB briefly per GET; a plugin with one 20 MB file is rejected (413).
- Build/bundle step must recompute the hash when plugins change, or verification fails on the next request. Mitigated by `scripts/compute-plugin-hash.sh` and a future CI step.
- Transient errors are **not** cached (F007) — a plugin with a temporarily unreadable manifest will re-attempt on the following request and self-heal when the FS settles.
- **Operational note:** no cache means there is no "restart required" for a legitimate plugin update in release — editing the plugin files and the matching `manifest.toml` in lockstep is enough. This changes the recovery story relative to v1 of this ADR.

## Workflow when a plugin changes

1. Edit the plugin files.
2. Run `./scripts/compute-plugin-hash.sh plugins-dev/<id>`.
3. Copy the hex into the plugin's `manifest.toml` `[integrity].sha256`.
4. The next `plugin://` request picks up the new hash automatically (no restart required in release; dev short-circuits via `STRICT_INTEGRITY=false`).

## Tests (lib.rs `mod tests`)

- `compute_hash_deterministic` — same input → same output, 64-char length.
- `compute_hash_ignores_integrity_section` — changing `[integrity].sha256` does **not** change the hash (canonicalization proof).
- `compute_hash_changes_when_content_changes` — modifying a byte of `ui/*` changes the hash.
- `compute_hash_handles_subdirs` — nested paths work.
- `verify_integrity_valid_passes` — correct hash → Ok.
- `verify_integrity_mismatch_rejected` (release-only) — wrong hash → Err(403).
- `verify_integrity_no_manifest_rejected` (release-only) — missing `manifest.toml` → Err(403).
- `verify_integrity_empty_hash_rejected` (release-only) — `sha256 = ""` → Err(403).
- `verify_integrity_short_hash_rejected` (release-only) — length != 64 → Err(403).
- `toctou_edit_in_place_detected` (release-only, **C01 regression**) — in-place edit of an existing file (no dir-mtime change) must return `Err(403)` on the very next request. Guards against any future regression to mtime-based cache invalidation.
- `b5_verify_and_load_atomic_snapshot_no_bypass` (release-only, **B5 regression**) — spin-write attacker alternates a plugin's file content over 500 verify+load requests. **Zero** returns must have bytes differing from the verified hash. Mutation-tested: reintroducing the pre-fix verify-then-read pattern causes the test to fail with ~50% bypass rate.
- `b6_hash_per_file_cap_enforced` (release-only, **B6 regression**) — a plugin containing a file > `MAX_HASH_FILE_BYTES` (10 MB) must return `Err(413)` rather than exhausting memory.
- `concurrent_verify_determinism` (release-only) — 10 threads verifying concurrently all return `Ok(())`, and the observability cache entry's `known_hash` matches the computed hash.
- `cache_does_not_persist_errors` (release-only) — a transient `Err(403)` does not poison the cache; fixing the manifest and retrying yields `Ok(())` without restart.

## References

- [ADR-0007 Plugins 3 tiers](ADR-0007-plugins-tres-nivells.md)
- [ADR-0009 plugin:// URI scheme](ADR-0009-plugin-uri-scheme.md)
- `plugins-dev/rag/manifest.toml` — example with real hash.
- `src-tauri/src/lib.rs` — implementation.
- `src-tauri/src/bin/plugin-hash.rs` — dev CLI.
- `scripts/compute-plugin-hash.sh` — wrapper.
