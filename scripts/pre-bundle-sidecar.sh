#!/usr/bin/env bash
# pre-bundle-sidecar.sh — create sidecar-bundle.tar.gz for Tauri resource bundling.
#
# Why tarball instead of a directory glob: Tauri 2 glob '**' does not recurse into
# deep directories, so the PBS+uv venv cannot be included via tauri.conf.json directly.
# A single .tar.gz sidesteps the bundler limitation entirely.
#
# F5.2 (initial): only venv/ + app/ archived.
# F5.2.1 (2026-05-18): venv/ + app/ + python-runtime/ — el PBS copiat per
# build-sidecar.sh Step 5.5 ha de viatjar al tarball perquè els symlinks
# relatius del venv (../../python-runtime/bin/python3.12) puguin resoldre al
# Mac destinatari. Sense això, el sidecar mai arrenca fora del Mac de build.
#
# Only venv/ + app/ + python-runtime/ are archived — the nexe-sidecar launcher
# is managed by externalBin (Contents/MacOS/) and does not belong in the tarball.
#
# At first launch, Rust extracts the tarball to app_data_dir/sidecar/ and sets
# NEXE_SIDECAR_DIR so the launcher finds venv/ and app/ there. A version-stamped
# .extracted marker prevents re-extraction unless the app version changes.
#
# Prerequisites: run scripts/build-sidecar.sh first to generate target/sidecar/.
# Usage: called automatically by `pnpm tauri:build` via tauri.conf.json beforeBundleCommand.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SIDECAR_SRC="$ROOT/target/sidecar"
TARBALL="$ROOT/src-tauri/sidecar-bundle.tar.gz"

if [ ! -d "$SIDECAR_SRC/venv" ]; then
  echo "pre-bundle-sidecar: target/sidecar/venv/ not found — run scripts/build-sidecar.sh first"
  exit 1
fi
# F5.2.1: el python-runtime/ ha d'existir (build-sidecar.sh Step 5.5).
if [ ! -d "$SIDECAR_SRC/python-runtime" ]; then
  echo "pre-bundle-sidecar: ERROR — target/sidecar/python-runtime/ not found." >&2
  echo "                    Run scripts/build-sidecar.sh (F5.2.1 Step 5.5)." >&2
  exit 2
fi

echo "pre-bundle-sidecar: creating sidecar-bundle.tar.gz..."
rm -f "$TARBALL"
# F5.5 — strip macOS AppleDouble (._*) files BEFORE tarball creation. Without
# this, the venv site-packages carry ~6400 ._*.py metadata files that the
# `transformers` library treats as Python source when scanning models/ and the
# scan crashes with UnicodeDecodeError (byte 0xa3 of the AppleDouble header
# magic is not valid UTF-8). COPYFILE_DISABLE=1 + --no-mac-metadata tell macOS
# tar to not emit fresh ones during archival. The `find -delete` deals with
# any already-present hidden metadata in the source tree.
find "$SIDECAR_SRC" -name '._*' -delete 2>/dev/null || true
# F5.2.1: --no-same-owner --no-acls --no-xattrs strip build-machine ownership
# i extended attributes que arrossegarien el UID/GID + flags quarantine del
# build machine cap al bundle final.
#
# Linux portability (FL-L1, 2026-05-22): GNU tar NO accepta `--no-mac-metadata`
# (és flag exclusiu de BSD tar / macOS) ni `--no-acls --no-xattrs` (sintaxi
# distinta). Detectem el tar real i bifurquem branca:
#   - GNU tar (Linux): omet flags BSD; el `find -delete` previ ja neteja AppleDouble.
#   - BSD tar (macOS): mantenim comportament F5.5 original + fallback històric.
if tar --version 2>&1 | grep -q "GNU tar"; then
    # Linux / GNU tar — sense flags BSD. --owner=0 --group=0 normalitza UID/GID
    # (equivalent funcional a --no-same-owner, però aplicat a creació).
    tar --owner=0 --group=0 -czf "$TARBALL" \
        -C "$SIDECAR_SRC" venv app python-runtime
else
    # macOS / BSD tar — comportament F5.5 original. El fallback (||) cobreix el
    # cas que un macOS tar futur canviï la sintaxi d'algun flag opcional.
    COPYFILE_DISABLE=1 tar --no-mac-metadata --no-same-owner --no-acls --no-xattrs \
        -czf "$TARBALL" -C "$SIDECAR_SRC" venv app python-runtime 2>/dev/null \
        || COPYFILE_DISABLE=1 tar --no-same-owner -czf "$TARBALL" \
            -C "$SIDECAR_SRC" venv app python-runtime
fi
echo "pre-bundle-sidecar: done ($(du -sh "$TARBALL" | cut -f1))"

# Generate SHA-256 of the tarball so the runtime can detect re-builds within
# the same CARGO_PKG_VERSION. Without this, `.extracted` marker compares
# version text and dev re-builds of the same version never re-extract the
# sidecar — see memory `feedback_extracted_marker_version_no_hash.md`.
SHA_FILE="${TARBALL%.tar.gz}.sha256"
SHASUM=$(shasum -a 256 "$TARBALL" 2>/dev/null | awk '{print $1}' \
       || sha256sum "$TARBALL" 2>/dev/null | awk '{print $1}')
if [ -n "$SHASUM" ]; then
    printf '%s  %s\n' "$SHASUM" "${TARBALL##*/}" > "$SHA_FILE"
    echo "pre-bundle-sidecar: sha256 = $SHASUM"
else
    echo "pre-bundle-sidecar: WARNING — neither shasum nor sha256sum found; SHA file not written" >&2
    : > "$SHA_FILE"  # empty placeholder → runtime falls back to version
fi
