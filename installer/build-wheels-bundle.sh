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

# Use host python3 (build Mac is expected to have Python 3.12 available).
# pip download does not execute setup.py for wheel-only downloads, so host
# Python version only needs to be new enough to run pip itself.
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH" >&2
    exit 1
fi

PIP_BIN=(python3 -m pip)

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
    --dest "$WHEELS_DIR"
)

# Core + macOS requirements
"${PIP_BIN[@]}" "${PIP_DOWNLOAD_ARGS[@]}" -r "$REQ_BASE" -r "$REQ_MACOS"

# Inference engines (not in requirements.txt because install flow is per-host)
for engine in "${ENGINES[@]}"; do
    echo "  → $engine"
    "${PIP_BIN[@]}" "${PIP_DOWNLOAD_ARGS[@]}" "$engine"
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
