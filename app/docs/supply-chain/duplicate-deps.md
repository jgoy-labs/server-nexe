# Duplicate Cargo dependencies — snapshot + bump roadmap

**C37** — `Cargo.lock` multi-version crypto/random crates.
**Generated:** 2026-04-21 via `cargo tree --duplicates`.
**Baseline raw lines:** 73 (31 unique crate names with 2+ versions).

---

## Current duplicates (31 unique crates)

| Crate | Versions present | Root cause | Bump path |
|---|---|---|---|
| `base64` | 0.21.7, 0.22.1 | `swift-rs`→`tauri-utils` (old) vs `plist`/`tauri-codegen` (new) | Wait tauri-utils bump |
| `bitflags` | 1.3.2, 2.11.1 | `png`/`selectors`/`kuchikiki` (v1) vs objc2/tao (v2) | Wait gtk-rs/kuchikiki upgrade |
| `deranged` | 0.5.8 + new | `time` crate version split | Wait tauri upstream |
| `getrandom` | 0.1.16, 0.2.17, 0.3.4, 0.4.2 | **4 versions** — rand 0.7/0.8/0.9 each pull different getrandom | Critical: rand fragmentation |
| `hashbrown` | 0.12.3, 0.17.0 | `indexmap` v1 vs v2 pull different hashbrown | Wait indexmap unification |
| `indexmap` | 1.9.3, 2.14.0 | Multiple crates locked to indexmap 1.x | Deprioritize — safe |
| `log` | 0.4.29 (single new) | `log` crate appears under duplicates but single version | No action needed |
| `percent-encoding` | 2.3.2 (watch) | Appears in duplicate scan but may be single version | Monitor |
| `phf` | 0.8.0, 0.10.1, 0.11.3 | **3 versions** — `kuchikiki` (0.8), css_color_parser (0.10), cssparser (0.11) | Wait kuchikiki upgrade |
| `phf_codegen` | 0.8.0, 0.11.3 | Same as phf | Wait |
| `phf_generator` | 0.8.0, 0.10.0, 0.11.3 | Same as phf | Wait |
| `phf_macros` | 0.10.0, 0.11.3 | Same as phf | Wait |
| `phf_shared` | 0.8.0, 0.10.0, 0.11.3 | Same as phf | Wait |
| `rand` | 0.7.3, 0.8.6, 0.9.4 | **3 versions** — kuchikiki→rand 0.7 (RUSTSEC-2026-0097 unsound), upstream 0.8, new 0.9 | Blocked by kuchikiki in tauri-utils |
| `rand_chacha` | 0.2.2, 0.3.1, 0.9.0 | Follows rand versions | Same |
| `rand_core` | 0.5.1, 0.6.4, 0.9.5 | Follows rand versions | Same |
| `regex-automata` | 0.4.14 (watch) | May appear from multiple regex paths | Monitor |
| `semver` | 1.0.28 (watch) | Scan artifact | Monitor |
| `serde` | 1.0.228 + `serde_core` 1.0.228 | Legitimate split — `serde_core` is serde's internal | Not a dup |
| `serde_json` | 1.0.149 | Watch for 2 versions | Monitor |
| `serde_spanned` | 0.6.9, 1.1.1 | toml 0.8 vs toml 0.9 | Wait toml unification |
| `siphasher` | 0.3.11, 1.0.2 | phf version split | Same as phf |
| `syn` | 1.0.109, 2.0.117 | Proc-macro crates still on syn 1; most migrated to 2 | Deprioritize — safe |
| `tauri-utils` | 2.8.3 (single) | Appears under base64 tree but single version | No action |
| `thiserror` | 1.0.69, 2.0.18 | Many crates still on thiserror 1 | Deprioritize — safe |
| `time` | 0.3.47 | Appears as duplicate in scan | Monitor |
| `toml` | 0.8.2, 0.9.12 | config parsing split | Wait upstream unification |
| `toml_datetime` | 0.6.3, 0.7.5 | Follows toml | Wait |
| `winnow` | 0.5.40, 0.7.15, 1.0.1 | toml/serde_spanned parsing | Wait |

---

## Critical: rand fragmentation (RUSTSEC-2026-0097)

The most security-relevant duplication:
- `rand 0.7.3` via **kuchikiki** ← tauri-utils ← almost everything
  - `rand 0.7.3` is **unsound** (RUSTSEC-2026-0097) — ignored in audit.toml with review-date 2026-10-01
  - Root cause in **tauri-utils** depending on **kuchikiki** which depends on rand 0.7
- `rand 0.8.6` via multiple crates
- `rand 0.9.4` new rand APIs

**Fix path:** When `tauri-utils` bumps `kuchikiki` or replaces it, rand 0.7.3 drops out.
Track: https://github.com/tauri-apps/tauri/issues (search kuchikiki or rand)

---

## CI threshold (scripts/verify.sh)

```bash
# Current baseline (2026-04-21): 73 raw lines, 31 unique crates
# Threshold set to 80 to catch regressions without false positives
if [[ $COUNT -gt 80 ]]; then
  echo "WARNING: duplicate crates exceeded threshold"
  exit 1
fi
```

Adjust threshold downward as tauri-utils / kuchikiki issues are resolved upstream.

---

## Bump roadmap

| Priority | Blocker | When |
|---|---|---|
| **High** | `tauri-utils` bump `kuchikiki` → `rand 0.8+` | When tauri 2.x ships fix |
| **High** | `kuchikiki` causing `rand 0.7.3` unsound (RUSTSEC-2026-0097) | Monitor tauri GitHub |
| Medium | `phf` versions unify (0.8→0.11) when kuchikiki upgrades | Follows kuchikiki |
| Low | `syn` 1→2 migration (all proc-macro deps) | Organic upstream |
| Low | `thiserror` 1→2 migration | Organic upstream |
| Low | `toml` 0.8→0.9 unification | When tauri bumps |
