#!/usr/bin/env bash
# reproducible-build.sh — Build del binari release amb flags de reproducibilitat (ADR-0015).
#
# Inclou:
#   - SOURCE_DATE_EPOCH (timestamp del HEAD commit) → evita build timestamps variables
#   - CARGO_INCREMENTAL=0                           → no caches incrementals no-deterministes
#   - --remap-path-prefix  $HOME, $CARGO_HOME      → no builder FS paths al binari
#
# NO construeix el bundle (.app/.dmg/.AppImage) — aquests NO són bit-for-bit reproduïbles
# sense upstream support a Tauri (timestamps Info.plist, code-sign, etc.).
#
# Us:
#   ./scripts/reproducible-build.sh              # cargo clean + cargo build --release
#   ./scripts/reproducible-build.sh --no-clean   # skip cargo clean (faster, but second run
#                                                #   reuses cache → hashes match trivially,
#                                                #   NOT a real reproducibility proof)
#   ./scripts/reproducible-build.sh --bin plugin-hash
#
# B22: cargo clean is mandatory for a valid reproducibility test. Without it, two consecutive
# runs reuse the cache and produce identical hashes BY DEFINITION, not because the build is
# truly reproducible. Use --no-clean only for speed during development, never to claim
# reproducibility across separate environments.
#
# Verificació manual:
#   ./scripts/reproducible-build.sh && HASH1=$(cat /tmp/nexe-build.hash)
#   ./scripts/reproducible-build.sh && HASH2=$(cat /tmp/nexe-build.hash)
#   [[ "$HASH1" == "$HASH2" ]] && echo "✅ reproduïble" || echo "❌ divergeix"

set -euo pipefail

# B22: parse --no-clean flag
NO_CLEAN=0
PASSTHROUGH_ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--no-clean" ]]; then
        NO_CLEAN=1
    else
        PASSTHROUGH_ARGS+=("$arg")
    fi
done

cd "$(dirname "$0")/.."

# SOURCE_DATE_EPOCH: timestamp del HEAD commit (fallback: now si no hi ha git).
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct HEAD 2>/dev/null || date +%s)"
export SOURCE_DATE_EPOCH

# No caches incrementals (poden introduir no-determinisme entre builds).
export CARGO_INCREMENTAL=0

# Remap absolut → placeholders (tapats als panic traces i DWARF).
# Nota: config.toml té --remap-path-prefix=@CARGO_HOME=@cargo amb token literal;
# aquí injectem el valor real per si no està a PATH. Additiu amb RUSTFLAGS previ.
CARGO_HOME_VAL="${CARGO_HOME:-$HOME/.cargo}"
export RUSTFLAGS="--remap-path-prefix=${HOME}=~ --remap-path-prefix=${CARGO_HOME_VAL}=@cargo ${RUSTFLAGS:-}"

echo "=== Reproducible build config ==="
echo "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH ($(date -u -r "$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo 'epoch'))"
echo "CARGO_INCREMENTAL=$CARGO_INCREMENTAL"
echo "RUSTFLAGS=$RUSTFLAGS"
echo "HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo 'no-git')"
echo ""

cd src-tauri

# B22: cargo clean before build to ensure cache does not mask non-reproducibility.
# Skip only when --no-clean is explicitly passed (development convenience only).
if [[ $NO_CLEAN -eq 0 ]]; then
    echo "=== cargo clean (B22: required for valid reproducibility test) ==="
    cargo clean
    echo ""
else
    echo "⚠️  WARNING: --no-clean specified — cache reuse means identical hashes prove nothing"
    echo "   Use two separate clean builds to verify reproducibility."
    echo ""
fi

cargo build --release --locked "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"

# Hash del binari principal (pot ser diferent amb --bin)
BIN="target/release/nexe-app"
if [[ -f "$BIN" ]]; then
    if command -v shasum &>/dev/null; then
        HASH=$(shasum -a 256 "$BIN" | awk '{print $1}')
    else
        HASH=$(sha256sum "$BIN" | awk '{print $1}')
    fi
    SIZE=$(stat -f%z "$BIN" 2>/dev/null || stat -c%s "$BIN")
    echo ""
    echo "=== Build output ==="
    echo "Binary: src-tauri/$BIN"
    echo "Size:   $SIZE bytes"
    echo "SHA256: $HASH"
    echo "$HASH" > /tmp/nexe-build.hash
    echo ""
    echo "Hash saved to /tmp/nexe-build.hash (for reproducibility check)"
fi
