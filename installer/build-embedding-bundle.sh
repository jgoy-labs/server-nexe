#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-embedding-bundle.sh
# Downloads the default embedding model (fastembed format, ONNX) into
# InstallNexe.app/Contents/Resources/embeddings/ so the client installer
# can copy it into the fastembed cache dir and the server starts with
# RAG working offline from the first boot.
#
# Model: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
#        Multilingual (ca/es/en + 50 languages). ~470 MB unpacked.
#
# Requires: network access + python3 at build time (dev Mac).
# Uses a temporary venv so the host Python stays clean.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
RESOURCES="$APP_DIR/Contents/Resources"
EMBEDDINGS_DIR="$RESOURCES/embeddings"

# Single source of truth for the embedding model name is
# memory/embeddings/constants.py. This script mirrors it; if the code
# constant changes, update this script too (caught by integration test).
EMBEDDING_MODEL="sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

TMP_VENV="$(mktemp -d)/nexe-build-venv"
trap 'rm -rf "$(dirname "$TMP_VENV")"' EXIT

# ── Step 1: Validate inputs ────────────────────────────────────────────
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: $APP_DIR does not exist. Run build-python-bundle.sh first." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH" >&2
    exit 1
fi

echo "==> Building embedding model bundle"
echo "    Model:    $EMBEDDING_MODEL"
echo "    Output:   $EMBEDDINGS_DIR"

# ── Step 2: Prepare output directory ───────────────────────────────────
mkdir -p "$RESOURCES"
rm -rf "$EMBEDDINGS_DIR"
mkdir -p "$EMBEDDINGS_DIR"

# ── Step 3: Create temporary venv and install fastembed ────────────────
echo "==> Creating temporary venv at $TMP_VENV..."
python3 -m venv "$TMP_VENV"

VENV_PIP="$TMP_VENV/bin/pip"
VENV_PY="$TMP_VENV/bin/python"

"$VENV_PIP" install --quiet --upgrade pip
"$VENV_PIP" install --quiet 'fastembed>=0.3.6' 'huggingface_hub>=0.36.2'

# ── Step 4: Download the model ─────────────────────────────────────────
echo "==> Downloading embedding model (fastembed ONNX cache format)..."
echo "    This may take several minutes the first time."

# fastembed places the model under <cache_dir>/models-<org>-<name>/
# or similar. We don't hard-code the internal path; we pass cache_dir
# and trust fastembed to populate it.
"$VENV_PY" - "$EMBEDDING_MODEL" "$EMBEDDINGS_DIR" <<'PY'
import sys
from pathlib import Path
from fastembed import TextEmbedding

model_name = sys.argv[1]
cache_dir = Path(sys.argv[2])
cache_dir.mkdir(parents=True, exist_ok=True)

print(f"  TextEmbedding({model_name!r}, cache_dir={str(cache_dir)!r})")
TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
print("  Download complete.")
PY

# ── Step 5: Validate downloaded artefacts ──────────────────────────────
echo "==> Validating embedding bundle..."

# The HuggingFace Hub cache (used by fastembed for this model) stores
# blobs under models--<org>--<name>/blobs/<sha256> and exposes the real
# filenames (model.onnx, tokenizer.json, config.json, …) as *symlinks*
# under snapshots/<revision>/. We therefore pass `find -L` so the -type f
# predicate follows symlinks and matches the snapshot entries.
if ! find -L "$EMBEDDINGS_DIR" -type f -name 'model*.onnx' -print -quit | grep -q .; then
    echo "ERROR: No model.onnx found under $EMBEDDINGS_DIR" >&2
    find "$EMBEDDINGS_DIR" -maxdepth 3 >&2
    exit 2
fi

if ! find -L "$EMBEDDINGS_DIR" -type f -name 'tokenizer.json' -print -quit | grep -q .; then
    echo "ERROR: No tokenizer.json found under $EMBEDDINGS_DIR" >&2
    exit 3
fi

if ! find -L "$EMBEDDINGS_DIR" -type f -name 'config.json' -print -quit | grep -q .; then
    echo "ERROR: No config.json found under $EMBEDDINGS_DIR" >&2
    exit 4
fi

# Check size range (~400-600 MB expected for mpnet-base multilingual)
SIZE_MB=$(du -sm "$EMBEDDINGS_DIR" | cut -f1)
if [ "$SIZE_MB" -lt 300 ]; then
    echo "ERROR: Embedding bundle is only ${SIZE_MB} MB — expected ~470 MB" >&2
    exit 5
fi
if [ "$SIZE_MB" -gt 800 ]; then
    echo "WARN: Embedding bundle is ${SIZE_MB} MB — larger than expected (~470 MB)" >&2
fi

# ── Step 6: Integrity manifest (F4.1 audit DoD-AUD-SX-0423 §2.7) ───────
# Emit `embeddings.manifest.json` alongside the downloaded model with the
# SHA256 digests of the three critical files (model*.onnx, tokenizer.json,
# config.json). The client installer (`installer/download_verify.py`:
# `verify_embedding_bundle`) re-hashes these files at copy time and aborts
# if any digest does not match — protecting against tampering on the
# distribution channel or corruption during DMG build.
#
# The hashes are computed via sha256sum / shasum (both available on
# macOS 14+ and any Linux host we build from). `find -L` follows the HF
# hub cache symlinks so the digest is of the real blob bytes, not the
# symlink target path.
echo "==> Writing integrity manifest..."

MANIFEST="$EMBEDDINGS_DIR/embeddings.manifest.json"

# Locate the three critical files (first match — there should be only one).
MODEL_ONNX=$(find -L "$EMBEDDINGS_DIR" -type f -name 'model*.onnx' -print -quit)
TOKENIZER_JSON=$(find -L "$EMBEDDINGS_DIR" -type f -name 'tokenizer.json' -print -quit)
CONFIG_JSON=$(find -L "$EMBEDDINGS_DIR" -type f -name 'config.json' -print -quit)

if [ -z "$MODEL_ONNX" ] || [ -z "$TOKENIZER_JSON" ] || [ -z "$CONFIG_JSON" ]; then
    echo "ERROR: Cannot locate the three critical files under $EMBEDDINGS_DIR" >&2
    exit 6
fi

# Cross-platform sha256: prefer GNU sha256sum, fall back to BSD shasum.
_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

MODEL_ONNX_HASH=$(_sha256 "$MODEL_ONNX")
TOKENIZER_JSON_HASH=$(_sha256 "$TOKENIZER_JSON")
CONFIG_JSON_HASH=$(_sha256 "$CONFIG_JSON")

# We record the basename (stable across HF cache layouts) — the runtime
# verifier locates the file by basename anywhere under the bundle root.
MODEL_ONNX_NAME=$(basename "$MODEL_ONNX")
TOKENIZER_JSON_NAME=$(basename "$TOKENIZER_JSON")
CONFIG_JSON_NAME=$(basename "$CONFIG_JSON")

GENERATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$MANIFEST" <<EOF_MANIFEST
{
  "schema_version": 1,
  "model_name": "$EMBEDDING_MODEL",
  "generated_at": "$GENERATED_AT",
  "files": {
    "$MODEL_ONNX_NAME": "$MODEL_ONNX_HASH",
    "$TOKENIZER_JSON_NAME": "$TOKENIZER_JSON_HASH",
    "$CONFIG_JSON_NAME": "$CONFIG_JSON_HASH"
  }
}
EOF_MANIFEST

echo "    Manifest: $MANIFEST"
echo "    $MODEL_ONNX_NAME: ${MODEL_ONNX_HASH:0:12}…"
echo "    $TOKENIZER_JSON_NAME: ${TOKENIZER_JSON_HASH:0:12}…"
echo "    $CONFIG_JSON_NAME: ${CONFIG_JSON_HASH:0:12}…"

# ── Step 7: Report ─────────────────────────────────────────────────────
echo ""
echo "==> Embedding bundle ready"
echo "    Location: $EMBEDDINGS_DIR"
echo "    Size:     ${SIZE_MB} MB"
echo ""
echo "Done."
