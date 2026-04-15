#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-wheels-bundle.sh
# Downloads all Python wheels (requirements.txt + requirements-macos.txt +
# inference engines) as arm64 macOS 13+ binaries into
# InstallNexe.app/Contents/Resources/wheels/ so the client installer can
# run "pip install --no-index --find-links wheels/" 100% offline.
#
# Target: Apple Silicon (arm64), macOS 13 Ventura or newer, Python 3.12.
# Requires: network access + recent pip at build time (dev Mac).
# Produces: ~220 MB of wheels. Fails clearly if any wheel is missing.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
RESOURCES="$APP_DIR/Contents/Resources"
WHEELS_DIR="$RESOURCES/wheels"

PY_TARGET_VERSION="3.12"
PY_TARGET_ABI="cp312"
PLATFORM_TAG="macosx_13_0_arm64"

REQ_BASE="$PROJECT_ROOT/requirements.txt"
REQ_MACOS="$PROJECT_ROOT/requirements-macos.txt"

# Inference engines installed dynamically by installer_setup_env.py.
# We must bundle their wheels here so the client install stays offline.
ENGINES=(
    "llama-cpp-python"
    "mlx-lm==0.31.2"
    "mlx-vlm==0.4.4"
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
echo "==> Downloading wheels (only-binary, arm64 macOS 13+, cp312)..."

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

# ── Step 4: Sanity checks ──────────────────────────────────────────────
echo "==> Validating wheels..."

WHEEL_COUNT=$(find "$WHEELS_DIR" -maxdepth 1 -name '*.whl' | wc -l | tr -d ' ')
if [ "$WHEEL_COUNT" -lt 30 ]; then
    echo "ERROR: Only $WHEEL_COUNT wheels downloaded — expected 30+" >&2
    exit 2
fi

# Expected critical wheels (substring match on filename)
EXPECTED_SUBSTRINGS=(
    "llama_cpp_python-"
    "mlx_lm-"
    "mlx_vlm-"
    "fastapi-"
    "pydantic-"
    "numpy-"
    "fastembed-"
    "onnxruntime-"
    "sqlcipher3-"
    "cryptography-"
    "rumps-"
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

# Check size range (target ~200-300 MB; fail if obviously wrong)
SIZE_MB=$(du -sm "$WHEELS_DIR" | cut -f1)
if [ "$SIZE_MB" -lt 100 ]; then
    echo "ERROR: Wheels bundle is only ${SIZE_MB} MB — expected >100 MB" >&2
    exit 4
fi
if [ "$SIZE_MB" -gt 500 ]; then
    echo "WARN: Wheels bundle is ${SIZE_MB} MB — larger than expected (~220 MB)" >&2
fi

# ── Step 5: Report ─────────────────────────────────────────────────────
echo ""
echo "==> Wheels bundle ready"
echo "    Location: $WHEELS_DIR"
echo "    Wheels:   $WHEEL_COUNT"
echo "    Size:     ${SIZE_MB} MB"
echo ""
echo "Done."
