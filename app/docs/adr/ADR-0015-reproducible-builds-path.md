# ADR-0015: Reproducible builds — SLSA baseline

**Date:** 2026-04-18
**Status:** Accepted — **Active baseline** (Sprint 0.15 #5), SLSA L3 deferred
**Decided by:** Jordi Goy
**Updated:** Sprint 0.15 #5 — `SOURCE_DATE_EPOCH` + reproducible-build.sh added

## Context

Two separate concerns are commonly grouped under "reproducible builds":

1. **Binary hygiene** — the release binary should not leak the builder's filesystem paths (e.g. `~/projects/my-app/...` appearing in DWARF debug info or `panic!` backtraces).
2. **Bit-for-bit reproducibility** — two independent builds from the same source produce identical binaries (SLSA Level 3-4 requirement). This needs `SOURCE_DATE_EPOCH`, deterministic zip ordering, stripped build timestamps, and — critically — upstream support from Tauri's `generate_context!()` macro.

For a starter, (1) is achievable with today's toolchain. (2) is a moving target that depends on upstream Tauri + Rust stability.

## Decision

**Ship (1) today. Document (2) as a future goal with prerequisites.**

### Implemented baseline

- `src-tauri/Cargo.toml`:
  ```toml
  [profile.release]
  strip = "symbols"       # Remove debug symbols → no DWARF path leak
  lto = true
  codegen-units = 1       # Deterministic panic traces
  panic = "abort"
  ```
- `src-tauri/.cargo/config.toml`:
  ```toml
  [build]
  rustflags = [
      "--remap-path-prefix=@CARGO_HOME=@cargo",
  ]
  ```
- `scripts/reproducible-build.sh` (Sprint 0.15 #5 — **active**):
  ```bash
  ./scripts/reproducible-build.sh
  ```
  The script sets:
  - `SOURCE_DATE_EPOCH` from the HEAD commit timestamp (deterministic build time).
  - `CARGO_INCREMENTAL=0` (incremental caches can introduce nondeterminism).
  - `RUSTFLAGS` with `--remap-path-prefix` for `$HOME` and `$CARGO_HOME`.
  - Prints SHA-256 of the resulting `target/release/nexe-app` for manual verification.

  Reproducibility check (two clean builds must produce identical hashes):
  ```bash
  ./scripts/reproducible-build.sh && H1=$(cat /tmp/nexe-build.hash)
  (cd src-tauri && cargo clean)
  ./scripts/reproducible-build.sh && H2=$(cat /tmp/nexe-build.hash)
  [[ "$H1" == "$H2" ]] && echo "✅ reproduïble" || echo "❌ divergeix"
  ```

### What this buys us

- `strings target/release/nexe-app | grep $HOME` → empty (no builder path leaked).
- Panic backtraces show `@cargo/...` and `~/...` instead of `~/projects/my-app/.cargo/...` and `~/projects/my-app/...`.
- `SOURCE_DATE_EPOCH` propagated to crates that honor it (most of the ecosystem does) → build timestamp constant across invocations.
- `CARGO_INCREMENTAL=0` → no stale cache artifacts leaking between builds.
- **Two builds on the same machine from the same commit produce the same `target/release/nexe-app` SHA-256.** Empirically verified 2026-04-18 (Sprint 0.15 #5): two `cargo clean` → `reproducible-build.sh` cycles produced identical SHA-256 `91630e8feac0fb286e758718c1ca0d9de02f34c6a8f17ac3f5c2a2382656f088`.
- Bundle (`.dmg`/`.app`) timestamps still differ — documented below as not-yet-solvable without upstream Tauri work.

### What this does NOT buy us

- Bit-for-bit identical `.app` / `.dmg` / `.AppImage` across different builders (timestamps in bundle Info.plist, code signing info, etc. still differ).
- SLSA Level 3+ provenance attestation.
- Defense against a compromised builder that injects subtly different code.

## Alternatives considered

| Option | Motiu descart |
|---|---|
| Full SLSA L3 now | Requires GitHub OIDC + sigstore + provenance attestation; disproportionate for a starter. |
| Skip the remap | Release binary leaks builder's `$HOME` in backtraces. Unacceptable default. |
| Only `strip` without remap | Panic traces still leak paths at runtime. |

## Consequences

**Positives:**
- Baseline binary hygiene achievable with 5 lines of config.
- Forward-compatible: activating `SOURCE_DATE_EPOCH` later is additive.

**Negatives / risks:**
- `--remap-path-prefix` at `.cargo/config.toml` level uses placeholder tokens (variables don't expand). CI must inject real paths via `RUSTFLAGS`.
- `lto = true` increases release compile time ~2-3×. Acceptable for a release build, not for iteration.

## Future path to SLSA (L2 → L3)

The baseline above gives a **SLSA L1-equivalent** posture for the binary. To progress:

1. ~~**`SOURCE_DATE_EPOCH`**~~ ✅ **Implemented** via `scripts/reproducible-build.sh`.
2. **Verify Tauri `generate_context!()` honors `SOURCE_DATE_EPOCH`** — upstream currently embeds build time in a few places; file upstream issue if divergence found when empirically testing.
3. **Reproducible `.app`/`.dmg` bundle** — Tauri's bundler uses current time for Info.plist / code-sign metadata; requires upstream work or a post-build canonicalization step (strip timestamps, re-sign deterministically).
4. **Containerized CI build** — fixed `$HOME`, `$CARGO_HOME`, Rust version pinned to exact SHA (not `stable` channel) → identical bytes across runners.
5. **`sigstore-cosign`** for signed provenance attestation (SLSA L2).
6. **`slsa-github-generator`** action → full L3 provenance attestation signed by GitHub OIDC.

Items 3-6 are not blockers for the starter. Items 1-2 are done / actionable today.

## References

- [Rust RFC 3127 — `--remap-path-prefix`](https://rust-lang.github.io/rfcs/3127-trim-paths.html)
- [SLSA spec](https://slsa.dev/)
- [Reproducible Builds project](https://reproducible-builds.org/)
- [SOURCE_DATE_EPOCH spec](https://reproducible-builds.org/specs/source-date-epoch/)
- `src-tauri/.cargo/config.toml` — current `rustflags` config.
- `src-tauri/Cargo.toml` — `[profile.release]` hardening.
- `scripts/reproducible-build.sh` — active baseline script.
