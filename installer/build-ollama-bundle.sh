#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-ollama-bundle.sh
# Downloads Ollama-darwin.zip into InstallNexe.app/Contents/Resources/ollama/
# so the client installer can extract Ollama.app 100% offline.
#
# Target: macOS (arm64 universal binary). ~156 MB download.
#
# B8 r4: SHA256 verification post-download against installer/ollama-checksums.txt.
# Aborts (exit 4) if checksum mismatch — closes a build-time MITM vector that
# could otherwise inject a backdoored Ollama binary into the shipped DMG.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
RESOURCES="$APP_DIR/Contents/Resources"
OLLAMA_DIR="$RESOURCES/ollama"
OLLAMA_ZIP="$OLLAMA_DIR/Ollama-darwin.zip"

# F3.4 BUG-NF-8: prefer a versioned GitHub release URL over the unversioned
# CDN. The CDN URL (`ollama.com/download/Ollama-darwin.zip`) is updated
# in-place by upstream, so the build SHA pin in ollama-checksums.txt
# silently flips from "valid" to "MITM" when Ollama ships a new version.
# With OLLAMA_VERSION set we fetch a fixed release artifact — the pin
# corresponds to exactly that version. Unset/latest falls back to the
# legacy URL with the same SHA gate as before (build will fail-fast on drift).
OLLAMA_VERSION="${OLLAMA_VERSION:-}"
# F5.6 OBS-2 — strip a leading "v" so both OLLAMA_VERSION=0.5.4 and
# OLLAMA_VERSION=v0.5.4 produce the same URL (avoid /releases/download/vv0.5.4/).
OLLAMA_VERSION="${OLLAMA_VERSION#v}"
if [ -n "$OLLAMA_VERSION" ] && [ "$OLLAMA_VERSION" != "latest" ]; then
    OLLAMA_URL="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/Ollama-darwin.zip"
else
    OLLAMA_URL="https://ollama.com/download/Ollama-darwin.zip"
fi
CHECKSUMS_FILE="$SCRIPT_DIR/ollama-checksums.txt"

# ── Validate ──────────────────────────────────────────────────────────
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: $APP_DIR does not exist. Run build-python-bundle.sh first." >&2
    exit 1
fi

if [ ! -f "$CHECKSUMS_FILE" ]; then
    echo "ERROR: $CHECKSUMS_FILE does not exist. SHA256 pin required (B8 r4)." >&2
    exit 1
fi

# ── Download ──────────────────────────────────────────────────────────
mkdir -p "$OLLAMA_DIR"

if [ -f "$OLLAMA_ZIP" ]; then
    echo "==> Ollama bundle already exists, re-downloading..."
    rm -f "$OLLAMA_ZIP"
fi

echo "==> Downloading Ollama for macOS..."
echo "    URL:  $OLLAMA_URL"
echo "    Dest: $OLLAMA_ZIP"
curl -fSL -o "$OLLAMA_ZIP" "$OLLAMA_URL"

# ── Validate ──────────────────────────────────────────────────────────
SIZE_MB=$(du -m "$OLLAMA_ZIP" | cut -f1)
if [ "$SIZE_MB" -lt 50 ]; then
    echo "ERROR: Ollama zip is only ${SIZE_MB} MB — expected ~150 MB" >&2
    rm -f "$OLLAMA_ZIP"
    exit 2
fi

# Quick zip integrity check
if ! unzip -t "$OLLAMA_ZIP" > /dev/null 2>&1; then
    echo "ERROR: Ollama zip is corrupt" >&2
    rm -f "$OLLAMA_ZIP"
    exit 3
fi

# ── B8 r4: SHA256 verification ────────────────────────────────────────
# Mismatch preserves $OLLAMA_ZIP on disk for forensic inspection (no rm).
echo "==> Verifying SHA256 against pinned checksum..."
if ! (cd "$OLLAMA_DIR" && shasum -a 256 -c "$CHECKSUMS_FILE" --status); then
    EXPECTED=$(grep -v '^[[:space:]]*#' "$CHECKSUMS_FILE" | grep "Ollama-darwin.zip" | awk '{print $1}')
    ACTUAL=$(shasum -a 256 "$OLLAMA_ZIP" | awk '{print $1}')
    echo "ERROR: SHA256 mismatch — possible MITM or upstream version change" >&2
    echo "   Expected: $EXPECTED" >&2
    echo "   Actual:   $ACTUAL" >&2
    echo "   Path:     $OLLAMA_ZIP (preserved for inspection)" >&2
    echo "" >&2
    echo "If Ollama released a new version, update $CHECKSUMS_FILE after" >&2
    echo "verifying the new digest from a clean network and the official source." >&2
    echo "See the inline 'Update procedure' in the checksums file." >&2
    exit 4
fi
echo "    SHA256: OK"

echo ""
echo "==> Ollama bundle ready"
echo "    Location: $OLLAMA_ZIP"
echo "    Size:     ${SIZE_MB} MB"
echo ""
echo "Done."
