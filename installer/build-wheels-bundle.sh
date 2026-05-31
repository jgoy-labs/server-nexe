#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-wheels-bundle.sh
# Downloads all Python wheels (requirements.txt + requirements-macos.txt +
# inference engines) as arm64 macOS 14+ binaries into
# InstallNexe.app/Contents/Resources/wheels/ so the client installer can
# run "pip install --no-index --find-links wheels/" 100% offline.
#
# Target: Apple Silicon (arm64), macOS 14 Sonoma or newer, Python 3.12.
# (macOS 13 Ventura was dropped 2026-04-16: mlx 0.30.4+ — required by our
# pinned mlx-lm 0.31.2 — ships wheels only for macosx_14_0_arm64+.)
# Requires: network access + recent pip at build time (dev Mac).
# Produces: ~330 MB of wheels (post v1.0.4-beta TODO 1.3 — torch + torchvision
# included for VL/multimodal model support). Fails clearly if any wheel is
# missing or if any pinned wheel SHA256 mismatches (B8 supply chain check).
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
RESOURCES="$APP_DIR/Contents/Resources"
WHEELS_DIR="$RESOURCES/wheels"

PY_TARGET_VERSION="3.12"
PY_TARGET_ABI="cp312"
PLATFORM_TAG="macosx_14_0_arm64"

REQ_BASE="$PROJECT_ROOT/requirements.txt"
REQ_MACOS="$PROJECT_ROOT/requirements-macos.txt"

# Inference engines installed dynamically by installer_setup_env.py.
# We must bundle their wheels here so the client install stays offline.
ENGINES=(
    "llama-cpp-python==0.3.19"  # 0.3.20 has corrupt wheel on abetlen Metal index (Bad CRC-32)
    "mlx-lm==0.31.2"
    "mlx-vlm==0.4.4"
    # PyTorch + torchvision — required at runtime by Qwen3 VL and other multimodal
    # models (Qwen3VLVideoProcessor needs torchvision for image preprocessing).
    # Wheels are macosx_11_0_arm64 (NOT macosx_14_0_arm64) — pip resolves upward
    # since 11.0 is the wheel's MIN macOS version, fully compat with macOS 14+
    # hosts. Verified empirically 2026-05-01: torch 2.11.0 macOS arm64 wheel
    # does NOT include CUDA/cuDNN libs (Linux-only Requires-Dist), so the bundle
    # delta is ~92 MB net (not the ~600 MB feared in the v1.0.4-beta master plan).
    # SHA256 cross-validated 3 sources (PyPI download, PyPI JSON Warehouse API,
    # pip hash) at pin time — see installer/wheels-checksums.txt.
    "torch==2.11.0"
    "torchvision==0.26.0"  # pairs exactly with torch 2.11.0 (Requires-Dist: torch (==2.11.0))
)

# ── Step 1: Validate inputs ────────────────────────────────────────────
[ -f "$REQ_BASE" ] || { echo "ERROR: $REQ_BASE not found" >&2; exit 1; }
[ -f "$REQ_MACOS" ] || { echo "ERROR: $REQ_MACOS not found" >&2; exit 1; }

# Use the bundled Python 3.12 (not host python3). pip resolves dependency
# environment markers (python_version, platform_system, …) against the
# *running* interpreter even when --python-version/--platform/--abi are
# given. On build Macs with Python 3.13+ installed system-wide, markers
# like `numpy>=2.1.0 ; python_version >= "3.13"` fire and break resolution
# against numpy==1.26.4 pinned for our 3.12 target. Driving pip with the
# bundle's 3.12 makes markers resolve correctly.
BUNDLE_PY="$APP_DIR/Contents/Resources/python/bin/python3"
if [ ! -x "$BUNDLE_PY" ]; then
    echo "ERROR: bundled Python not found at $BUNDLE_PY" >&2
    echo "       Run installer/build-python-bundle.sh first." >&2
    exit 1
fi

PIP_BIN=("$BUNDLE_PY" -m pip)

echo "==> Building wheels bundle"
echo "    Platform: $PLATFORM_TAG"
echo "    Python:   $PY_TARGET_VERSION ($PY_TARGET_ABI)"
echo "    Output:   $WHEELS_DIR"

# ── Step 2: Prepare wheels directory ───────────────────────────────────
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: $APP_DIR does not exist. Run build-python-bundle.sh first." >&2
    exit 1
fi

mkdir -p "$RESOURCES"
rm -rf "$WHEELS_DIR"
mkdir -p "$WHEELS_DIR"

# ── Step 3: Download wheels ────────────────────────────────────────────
echo "==> Downloading wheels (only-binary, arm64 macOS 14+, cp312)..."

# Common pip download flags:
#   --only-binary=:all:      reject source distributions (no compilation needed)
#   --platform               target macOS version + arch
#   --python-version         target Python minor
#   --implementation cp      CPython only
#   --abi cp312              matches our bundled Python 3.12
#   --extra-index-url        official llama-cpp-python Metal wheels index
#                            (abetlen = upstream maintainer; PyPI ships only
#                            sdist for this package, so the client install
#                            would require a C toolchain without this)
#   --dest                   output dir
#
# Pure-python ("py3-none-any") wheels are accepted automatically when
# --implementation + --abi are set.
PIP_DOWNLOAD_ARGS=(
    download
    --only-binary=:all:
    --platform "$PLATFORM_TAG"
    --python-version "$PY_TARGET_VERSION"
    --implementation cp
    --abi "$PY_TARGET_ABI"
    --extra-index-url "https://abetlen.github.io/llama-cpp-python/whl/metal/"
    --dest "$WHEELS_DIR"
)

# Pure-Python packages distributed only as sdist on PyPI (no wheel).
# They must be filtered out of pip-download (which uses --only-binary=:all:
# and would abort) and rebuilt locally from sdist in Step 3b so the client
# install stays 100% offline.
SDIST_ONLY_PKGS=(
    "rumps"
)

# Transitive deps of sdist-only packages that have binary wheels on PyPI.
# pip wheel --no-deps (Step 3b) skips these, so we download them explicitly
# in Step 3c to keep the client install 100% offline.
SDIST_TRANSITIVE_DEPS=(
    "pyobjc-framework-Cocoa"   # rumps → pyobjc-framework-Cocoa → pyobjc-core
)

# Build a grep -E pattern: ^(rumps|other)([= ].*)?$ to match requirement lines
SDIST_PATTERN="^($(IFS='|'; echo "${SDIST_ONLY_PKGS[*]}"))([=<>! ].*)?$"
REQ_MACOS_FILTERED="$(mktemp -t reqmacos-filtered.XXXXXX)"
trap 'rm -f "$REQ_MACOS_FILTERED"' EXIT
grep -v -E "$SDIST_PATTERN" "$REQ_MACOS" > "$REQ_MACOS_FILTERED" || true

# Core + macOS requirements (sdist-only packages filtered out)
"${PIP_BIN[@]}" "${PIP_DOWNLOAD_ARGS[@]}" -r "$REQ_BASE" -r "$REQ_MACOS_FILTERED"

# Inference engines (not in requirements.txt because install flow is per-host)
for engine in "${ENGINES[@]}"; do
    echo "  → $engine"
    "${PIP_BIN[@]}" "${PIP_DOWNLOAD_ARGS[@]}" "$engine"
done

# ── Step 3b: Build sdist-only wheels locally ────────────────────────────
# Reads version pins from requirements-macos.txt so there is no duplication
# between the filter whitelist and the actual pinned version.
echo "==> Building sdist-only wheels locally..."
for pkg in "${SDIST_ONLY_PKGS[@]}"; do
    SPEC=$(grep -E "^${pkg}([=<>! ].*)?$" "$REQ_MACOS" | head -1 | awk '{print $1}')
    if [ -z "$SPEC" ]; then
        echo "ERROR: ${pkg} listed as SDIST_ONLY but not found in $REQ_MACOS" >&2
        exit 5
    fi
    echo "  → $SPEC"
    "${PIP_BIN[@]}" wheel "$SPEC" --wheel-dir "$WHEELS_DIR" --no-deps
done

# ── Step 3c: Download transitive deps of sdist-only packages ──────────
# These have binary wheels on PyPI but were skipped by --no-deps above.
# pip download resolves their full dep chain (e.g. pyobjc-framework-Cocoa
# pulls pyobjc-core automatically).
if [ "${#SDIST_TRANSITIVE_DEPS[@]}" -gt 0 ]; then
    echo "==> Downloading transitive deps of sdist-only packages..."
    for dep in "${SDIST_TRANSITIVE_DEPS[@]}"; do
        echo "  → $dep"
        "${PIP_BIN[@]}" "${PIP_DOWNLOAD_ARGS[@]}" "$dep"
    done
fi

# ── Step 4: Sanity checks ──────────────────────────────────────────────
echo "==> Validating wheels..."

WHEEL_COUNT=$(find "$WHEELS_DIR" -maxdepth 1 -name '*.whl' | wc -l | tr -d ' ')
if [ "$WHEEL_COUNT" -lt 30 ]; then
    echo "ERROR: Only $WHEEL_COUNT wheels downloaded — expected 30+" >&2
    exit 2
fi

# ── Step 4b: SHA256 supply chain verification (B8 pattern, TODO 1.3 v1.0.4) ─
# Verifies that the wheels we just pulled from PyPI match the SHA256 hashes
# pinned in installer/wheels-checksums.txt. Same threat model as the Ollama
# bundle pin (B8 r4): a build-time MITM (proxy, DNS hijack, malicious Wi-Fi)
# could substitute a same-shape backdoored wheel; the size and pip resolver
# would not catch it. Hashes were cross-validated from 3 independent sources
# at pin time (PyPI download, PyPI JSON Warehouse API, pip hash) — see the
# checksums file header for the procedure on bumping pinned versions.
#
# Why the verification lives HERE (after Step 3c, before Step 4 size sanity):
#   - Step 3+3b+3c finished downloading every wheel — the pinned files MUST
#     be present on disk by now (else exit 7 = pin in checksums but wheel
#     vanished).
#   - Failing fast (before size/sanity checks) gives a clearer error: a
#     mismatched SHA is far more diagnostic than "bundle is wrong size".
#
# Why we use a manual loop with _sha256 instead of `shasum -a 256 -c`:
#   - The Ollama bundle (single file Ollama-darwin.zip) uses `shasum -c`,
#     but here the entries reference wheels in $WHEELS_DIR (not CWD), and
#     embedding the cross-validation provenance + per-wheel diagnostics in
#     the loop body keeps the supply chain audit trail visible.
#   - Reuses the same _sha256() helper as build-embedding-bundle.sh
#     (internal security review AUD-INT-001 §2.7) — single behaviour, two scripts.
#
# Why we do NOT do a tamper test against the live bundle in CI: this script
# starts with `rm -rf "$WHEELS_DIR"` at Step 2 and re-downloads, so any
# byte-flip on a wheel is wiped on the next run. The tamper coverage lives
# in tests/test_installer_wheels_checksum.py:test_shasum_check_rejects_corrupt_wheels
# (sandbox with random-bytes files at the pinned filenames) — equivalent
# adversarial coverage, reproducible, runs in CI without network.

# Cross-platform sha256: prefer GNU sha256sum, fall back to BSD shasum.
# (Same helper as build-embedding-bundle.sh; bash scripts are self-contained,
# no shared lib — duplication accepted, refactor only if a 3rd script needs it.)
_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

CHECKSUMS_FILE="$PROJECT_ROOT/installer/wheels-checksums.txt"
# Hard-fail if the checksums file is missing. A supply-chain defense that
# silently disappears when its config file disappears is not a defense —
# either by accident (bad rebase / clean-room checkout) or intent (someone
# deletes it to ship faster). Post-TODO 1.3 the file is mandatory; an older
# checkout that legitimately lacks it should not be calling this build
# script either way.
if [ ! -f "$CHECKSUMS_FILE" ]; then
    echo "ERROR: $CHECKSUMS_FILE not found." >&2
    echo "       The B8 supply-chain check (TODO 1.3 v1.0.4-beta) is mandatory" >&2
    echo "       for every build — DO NOT bypass by deleting this file. If you" >&2
    echo "       are bumping pinned versions, follow the procedure in the file" >&2
    echo "       header (3-source cross-validation)." >&2
    exit 6
fi

echo "==> Verifying pinned wheels SHA256 (supply chain — B8 pattern)..."

# Counter ensures the loop did real work. An empty-or-comments-only checksums
# file would otherwise pass with zero verifications and exit 0 — bypass.
verified_count=0

# `|| [ -n "$line" ]` covers the case where the last line lacks a trailing
# newline: `read` returns 1 on EOF but $line still holds the partial last
# line. Without this guard, the FINAL pinned wheel would be silently skipped.
while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines.
    case "$line" in '#'*|'') continue ;; esac

    # Format: "<sha256-hex>  <wheel-filename>" (two spaces — `shasum -c`
    # compatible). awk handles both the canonical 2-space separator and
    # any longer run of whitespace as a defensive fallback.
    expected_hash=$(printf '%s\n' "$line" | awk '{print $1}')
    wheel_name=$(printf '%s\n' "$line" | awk '{print $2}')
    [ -n "$expected_hash" ] && [ -n "$wheel_name" ] || continue

    # Defense-in-depth: reject path components that escape $WHEELS_DIR.
    # Per threat model (in-repo file, build-time supply chain), this is not
    # exploitable, but rejecting `..` / `/` keeps any future use of the loop
    # over an attacker-influenced source (e.g. a downloaded pin file) honest.
    case "$wheel_name" in
        */*|*..*)
            echo "ERROR: invalid wheel name (path component): $wheel_name" >&2
            exit 9
            ;;
    esac

    wheel_path="$WHEELS_DIR/$wheel_name"
    if [ ! -f "$wheel_path" ]; then
        echo "ERROR: pinned wheel missing from bundle: $wheel_name" >&2
        echo "       (listed in $CHECKSUMS_FILE but not downloaded)" >&2
        exit 7
    fi
    actual_hash=$(_sha256 "$wheel_path")
    if [ "$actual_hash" != "$expected_hash" ]; then
        echo "ERROR: SHA256 mismatch for $wheel_name" >&2
        echo "  expected: $expected_hash" >&2
        echo "  actual:   $actual_hash" >&2
        echo "" >&2
        echo "Possible causes (in order of likelihood):" >&2
        echo "  1. Upstream wheel re-published at the same version (rare but" >&2
        echo "     happens — re-validate from 3 sources before bumping the pin)." >&2
        echo "  2. MITM / DNS hijack / proxy injecting backdoored wheel." >&2
        echo "  3. PyPI CDN cache divergence (try a different network path)." >&2
        echo "Do NOT bypass — see installer/wheels-checksums.txt header for" >&2
        echo "the cross-validation procedure on legitimate version bumps." >&2
        exit 8
    fi
    echo "  ✓ $wheel_name (${actual_hash:0:12}…)"
    verified_count=$((verified_count + 1))
done < "$CHECKSUMS_FILE"

# An empty or comments-only checksums file would otherwise sail through the
# loop with zero iterations and exit 0. Refuse to ship a build with no
# verifications performed.
if [ "$verified_count" -lt 1 ]; then
    echo "ERROR: $CHECKSUMS_FILE has no active pin lines — zero wheels verified." >&2
    echo "       The B8 check is mandatory; an empty/comments-only file is not" >&2
    echo "       a valid configuration." >&2
    exit 10
fi
echo "    ($verified_count pinned wheel(s) verified.)"

# Expected critical wheels (substring match on filename)
EXPECTED_SUBSTRINGS=(
    "llama_cpp_python-"
    "mlx_lm-"
    "mlx_vlm-"
    "torch-"          # PyTorch (v1.0.4-beta TODO 1.3) — Qwen3 VL multimodal runtime
    "torchvision-"    # paired with torch — image preprocessing for VL models
    "fastapi-"
    "pydantic-"
    "numpy-"
    "fastembed-"
    "onnxruntime-"
    "sqlcipher3-"
    "cryptography-"
    "rumps-"
    "pyobjc_framework_cocoa-"
    "pyobjc_core-"
)

MISSING=()
for sub in "${EXPECTED_SUBSTRINGS[@]}"; do
    if ! find "$WHEELS_DIR" -maxdepth 1 -name "${sub}*.whl" -print -quit | grep -q .; then
        MISSING+=("$sub")
    fi
done

if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "ERROR: Missing critical wheels:" >&2
    printf "  - %s\n" "${MISSING[@]}" >&2
    echo "" >&2
    echo "Available wheels:" >&2
    ls -1 "$WHEELS_DIR" >&2
    exit 3
fi

# Check size range. Floor and ceiling were re-baselined for v1.0.4-beta
# TODO 1.3 (torch + torchvision added — empirical bundle ~330 MB, NOT the
# 750-900 MB the master plan feared: macOS arm64 torch wheels do not ship
# CUDA/cuDNN libs). Floor 250 catches a silent pip download failure (almost
# nothing landed); ceiling 600 catches an accidental Linux/CUDA transitive
# pulled in by a future ENGINES bump.
SIZE_MB=$(du -sm "$WHEELS_DIR" | cut -f1)
if [ "$SIZE_MB" -lt 250 ]; then
    echo "ERROR: Wheels bundle is only ${SIZE_MB} MB — expected >250 MB (post torch+torchvision)" >&2
    exit 4
fi
if [ "$SIZE_MB" -gt 600 ]; then
    echo "WARN: Wheels bundle is ${SIZE_MB} MB — larger than expected (~330 MB)" >&2
fi

# ── Step 5: Report ─────────────────────────────────────────────────────
echo ""
echo "==> Wheels bundle ready"
echo "    Location: $WHEELS_DIR"
echo "    Wheels:   $WHEEL_COUNT"
echo "    Size:     ${SIZE_MB} MB"
echo ""
echo "Done."
