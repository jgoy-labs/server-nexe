#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-embedding-bundle.sh
# Downloads the default embedding model (fastembed format, ONNX) into
# InstallNexe.app/Contents/Resources/embeddings/ so the client installer
# can copy it into the fastembed cache dir and the server starts with
# RAG working offline from the first boot.
#
# Model: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
#        Multilingual (ca/es/en + 50 languages). int8 quantized variant
#        from the Xenova mirror, ~280 MB unpacked (vs ~1058 MB FP32).
#        See Step 4 for the variant-selection rationale and the three
#        runtime-compatibility hacks (Xenova mirror, basename rename,
#        lowercase cache dir).
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

# ── Step 4: Download the model (int8 quantized ONNX, explicit variant) ─
echo "==> Downloading embedding model (int8 quantized ONNX, explicit variant from Xenova mirror)..."
echo "    This may take several minutes the first time."

# We bypass fastembed's default download and use huggingface_hub directly
# to force the int8 dynamic-quantized variant of the ONNX model. fastembed
# (>=0.3.6) defaults to FP32 (~1058 MB); int8 dynamic-quant is functionally
# equivalent for our RAG use case (typical -1-3% MTEB on mpnet-base) and
# REDUCES disk usage by 75% (266 MB vs 1058 MB).
#
# Why NOT FP16 (the original v1.0.4 TODO 1.2 target — 530 MB):
#   Empirically verified 2026-05-01 — both Xenova/model_fp16.onnx and
#   Xenova/model_q4f16.onnx FAIL to initialize with onnxruntime 1.25.x
#   (the version fastembed 0.8.x ships):
#
#     [ONNXRuntimeError] : 1 : FAIL : Exception during initialization:
#     Attempting to get index by a name which does not exist:
#     InsertedPrecisionFreeCast_/.../LayerNorm/Constant_output_0
#     for node: /embeddings/LayerNorm/Mul/SimplifiedLayerNormFusion/
#
#   The FP16 ONNX export contains precision-free cast nodes that collide
#   with ORT's modern SimplifiedLayerNormFusion optimizer. Was valid with
#   older ORT, broken with current. sentence-transformers/model_O4.onnx
#   loads but takes ~108s first-time (graph compilation) — UX blocker for
#   first-run users. int8 quantized loads in <0.5s.
#   See: PLA-20260501-onnx-fp16.md, memory feedback_verificacio_empirica_repos_hf
#
# THREE HACKS, validated empirically 2026-05-01:
#
#   1) WHY Xenova mirror (not the canonical sentence-transformers repo):
#      The official sentence-transformers/paraphrase-multilingual-mpnet-base-v2
#      repo only ships FP32 + Olevel + qint8 (CPU-arch-specific) variants.
#      It does NOT publish a portable model_quantized.onnx with the
#      onnx/ directory layout fastembed expects. The community Xenova
#      mirror does (266 MB exactly, dynamic int8).
#
#   2) WHY rename onnx/model_quantized.onnx → onnx/model.onnx:
#      At runtime fastembed.TextEmbedding loads the literal basename
#      "onnx/model.onnx" from its cache; it does NOT auto-discover
#      variant files like model_quantized.onnx. Renaming the int8 file
#      in place tricks fastembed into transparently loading the smaller
#      variant. verify_embedding_bundle hashes by basename so the
#      manifest contract is preserved (the recorded SHA256 matches the
#      int8 quantized bytes).
#
#   3) WHY rename models--Xenova-- → models--xenova-- (lowercase):
#      fastembed's internal mapping for the runtime model_id
#      "sentence-transformers/paraphrase-multilingual-mpnet-base-v2" resolves
#      to the LOWERCASE directory models--xenova--paraphrase-multilingual-
#      mpnet-base-v2/ in the cache (verified empirically in
#      ~/.cache/fastembed/). HF's snapshot_download creates the directory
#      with the verbatim repo_id case (Xenova). On case-sensitive filesystems
#      (Linux build hosts, container builders) the mismatch would cause
#      fastembed to NOT find the cached snapshot and silently re-download
#      the FP32 default from the network at first user run. On macOS
#      (case-insensitive HFS+/APFS) this rename is a no-op but harmless.
"$VENV_PY" - "$EMBEDDING_MODEL" "$EMBEDDINGS_DIR" <<'PY'
import shutil
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

# argv[1] is the runtime model_id (sentence-transformers/...) — the SSOT
# from memory/embeddings/constants.py. We do not pass it to snapshot_download
# because the Xenova mirror is the only repo shipping an int8 quantized
# variant in the onnx/ subfolder layout fastembed expects. The SSOT name is
# still consumed by Step 6 (manifest model_name field) outside this Python
# block, so dropping it here would silently desync the manifest from the
# runtime constant.
_ = sys.argv[1]  # contract-only — see comment above
cache_dir = Path(sys.argv[2])
cache_dir.mkdir(parents=True, exist_ok=True)

DOWNLOAD_REPO = "Xenova/paraphrase-multilingual-mpnet-base-v2"

# Whitelist exactly the 5 files needed by fastembed runtime. Anything else
# (README, gitattributes, alternative ONNX variants, weights.bin, ...) is
# excluded to keep the bundle minimal.
ALLOW = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "config.json",
    "onnx/model_quantized.onnx",
]

print(f"  snapshot_download({DOWNLOAD_REPO!r}, allow_patterns={ALLOW!r})")
snapshot_path = Path(
    snapshot_download(
        repo_id=DOWNLOAD_REPO,
        cache_dir=str(cache_dir),
        allow_patterns=ALLOW,
    )
)
print(f"  Downloaded snapshot to: {snapshot_path}")

# ── Hack 2: rename onnx/model_quantized.onnx → onnx/model.onnx ─────────
variant_path = snapshot_path / "onnx" / "model_quantized.onnx"
target_path = snapshot_path / "onnx" / "model.onnx"
if not variant_path.is_file():
    onnx_dir = snapshot_path / "onnx"
    listing = list(onnx_dir.iterdir()) if onnx_dir.is_dir() else []
    raise SystemExit(
        f"FATAL: expected {variant_path} after snapshot_download — "
        f"found {[p.name for p in listing]}"
    )
variant_path.rename(target_path)
print(f"  Renamed onnx/{variant_path.name} -> onnx/{target_path.name}")

# Resolve the underlying blob (HF stores files as symlinks → blobs/<sha>).
# After renaming the symlink, the blob it points at still exists and is the
# physical int8-quantized weights; verify_embedding_bundle will hash through
# the symlink (sha256_of_file follows symlinks) so the manifest pin matches.

# ── Hack 3: rename models--Xenova-- → models--xenova-- (lowercase) ─────
def _lowercase_xenova_dir(parent: Path) -> None:
    src = parent / "models--Xenova--paraphrase-multilingual-mpnet-base-v2"
    dst = parent / "models--xenova--paraphrase-multilingual-mpnet-base-v2"
    if not src.is_dir():
        return
    if dst.is_dir():
        try:
            same = src.samefile(dst)
        except (OSError, ValueError):
            same = False
        if same:
            # Case-insensitive FS (macOS HFS+/APFS): src and dst point to
            # the same inode → already correct, nothing to rename.
            print(f"  {src.name} already lowercase on this FS (no-op)")
            return
        # Defensive: stale prior build artifact — remove it so rename succeeds.
        shutil.rmtree(dst)
    src.rename(dst)
    print(f"  Renamed {src.name} -> {dst.name} (fastembed runtime mapping)")

_lowercase_xenova_dir(cache_dir)
_lowercase_xenova_dir(cache_dir / ".locks")

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

# Check size range (~250-350 MB expected for mpnet-base multilingual int8).
# int8 dynamic-quantized variant: the .onnx file alone is 266 MB, plus the
# tokenizer (~16 MB) and small JSON configs. The HF cache dedupes via blob
# symlinks but `du -sm` follows them by default, so the figure is the real
# disk footprint at install time.
SIZE_MB=$(du -sm "$EMBEDDINGS_DIR" | cut -f1)
if [ "$SIZE_MB" -lt 200 ]; then
    echo "ERROR: Embedding bundle is only ${SIZE_MB} MB — expected ~280 MB" >&2
    exit 5
fi
if [ "$SIZE_MB" -gt 600 ]; then
    echo "WARN: Embedding bundle is ${SIZE_MB} MB — larger than expected (~280 MB)" >&2
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
