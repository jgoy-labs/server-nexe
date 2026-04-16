#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-ollama-bundle.sh
# Downloads Ollama-darwin.zip into InstallNexe.app/Contents/Resources/ollama/
# so the client installer can extract Ollama.app 100% offline.
#
# Target: macOS (arm64 universal binary). ~156 MB download.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
RESOURCES="$APP_DIR/Contents/Resources"
OLLAMA_DIR="$RESOURCES/ollama"
OLLAMA_ZIP="$OLLAMA_DIR/Ollama-darwin.zip"
OLLAMA_URL="https://ollama.com/download/Ollama-darwin.zip"

# ── Validate ──────────────────────────────────────────────────────────
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: $APP_DIR does not exist. Run build-python-bundle.sh first." >&2
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

echo ""
echo "==> Ollama bundle ready"
echo "    Location: $OLLAMA_ZIP"
echo "    Size:     ${SIZE_MB} MB"
echo ""
echo "Done."
