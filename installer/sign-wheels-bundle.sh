#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# sign-wheels-bundle.sh
# Re-signs every native binary (.so / .dylib) inside each wheel under
# InstallNexe.app/Contents/Resources/wheels/ with our Developer ID
# certificate, a secure timestamp, and the hardened runtime.
#
# Why: wheels from PyPI ship .so/.dylib signed ad-hoc (or by the wheel
# author) and without a secure timestamp. Apple Notarization rejects
# the whole .app if any nested Mach-O binary lacks a valid Developer ID
# signature.
#
# Hybrid pipeline (picked after two failures with pure-CLI and pure-Python
# approaches, 2026-04-16 run):
#   - Unpack:   `unzip -q`   — tolerates wheels with corrupt CRC-32 on
#                              individual members (e.g. ggml-config.cmake
#                              inside llama_cpp_python 0.3.20); Python
#                              zipfile raises BadZipFile and aborts.
#   - Sign:     `codesign`   — per-file with hardened runtime + timestamp.
#   - Record:   Python       — sha256 + urlsafe-b64 per PEP 376.
#   - Repack:   Python       — zipfile supports zip64 streams, while
#                              `zip -X` corrupts offsets in zip64 wheels
#                              (same llama wheel round-trips as garbage).
#
# Early skip for pure-Python wheels uses `grep -c … || true` because
# `grep -q` closes the pipe, unzip dies with SIGPIPE, and `set -o pipefail`
# then swallows every wheel as "no native binaries".
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
WHEELS_DIR="$APP_DIR/Contents/Resources/wheels"

CERT="Developer ID Application: Jordi Goy (NHG3THR2AF)"

# ── Step 1: Pre-flight ─────────────────────────────────────────────────
if [ ! -d "$WHEELS_DIR" ]; then
    echo "ERROR: wheels directory missing: $WHEELS_DIR" >&2
    exit 1
fi

if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "Developer ID Application: Jordi Goy"; then
    echo "ERROR: Developer ID certificate not found in keychain" >&2
    exit 2
fi

BUNDLE_PY="$APP_DIR/Contents/Resources/python/bin/python3"
if [ ! -x "$BUNDLE_PY" ]; then
    echo "ERROR: bundled Python not found at $BUNDLE_PY" >&2
    exit 3
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "==> Signing native binaries inside wheels"
echo "    Certificate: $CERT"
echo "    Wheels dir:  $WHEELS_DIR"

TOTAL_WHEELS=0
SIGNED_WHEELS=0
SIGNED_BINARIES=0

for whl in "$WHEELS_DIR"/*.whl; do
    [ -f "$whl" ] || continue
    TOTAL_WHEELS=$((TOTAL_WHEELS + 1))

    # Skip wheels without native binaries.
    so_count=$(unzip -l "$whl" 2>/dev/null | grep -cE '\.(so|dylib)$' || true)
    if [ "${so_count:-0}" -eq 0 ]; then
        continue
    fi

    basename=$(basename "$whl")
    WORK="$TMP_DIR/${basename}.d"
    rm -rf "$WORK"
    mkdir -p "$WORK"

    # Use Apple's `ditto -x -k` rather than `unzip -q`. Some wheels (the
    # llama_cpp_python Metal wheel from abetlen's index is the canonical
    # example) ship a zip64 central directory whose local-header offsets
    # macOS `unzip` parses incorrectly — it skips every member past the
    # break, exits 0, and leaves the critical lib/*.dylib files out. ditto
    # handles the same archive cleanly (verified on submission
    # ee85d2ec-ffb4-4d6f-88a6-d3c07f398cc7). zipfile also chokes here
    # because the same wheel has a corrupt CRC-32 on a stray CMake file.
    ditto -x -k "$whl" "$WORK" 2>/dev/null || true

    BIN_COUNT=0
    while IFS= read -r -d '' sofile; do
        codesign --force --timestamp --options runtime \
            --sign "$CERT" "$sofile" >/dev/null 2>&1
        BIN_COUNT=$((BIN_COUNT + 1))
    done < <(find "$WORK" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)

    if [ "$BIN_COUNT" -eq 0 ]; then
        rm -rf "$WORK"
        continue
    fi

    # Regenerate RECORD (sha256/base64url per PEP 376) and repack through
    # Python zipfile so zip64 wheels round-trip cleanly.
    "$BUNDLE_PY" - "$WORK" "$whl" <<'PY'
import base64
import hashlib
import os
import sys
import zipfile
from pathlib import Path

work = Path(sys.argv[1])
out_whl = Path(sys.argv[2])

# ZIP local-header date field can't encode anything before 1980-01-01.
# ditto preserves whatever mtime the archive claims, and some wheels
# have entries with mtime == 0 (epoch 1970). Clamp to the ZIP floor
# so zipfile.write() doesn't raise ValueError on repack. Content is
# unaffected — pip install does not inspect mtime.
ZIP_EPOCH = 315532800  # 1980-01-01T00:00:00 UTC

record_paths = list(work.glob("*.dist-info/RECORD"))
if record_paths:
    record = record_paths[0]
    lines = []
    for f in sorted(work.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(work).as_posix()
        if f == record:
            lines.append(f"{rel},,\n")
            continue
        data = f.read_bytes()
        digest = hashlib.sha256(data).digest()
        encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        lines.append(f"{rel},sha256={encoded},{len(data)}\n")
    record.write_text("".join(lines), encoding="utf-8")

if out_whl.exists():
    out_whl.unlink()

with zipfile.ZipFile(out_whl, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
    for f in sorted(work.rglob("*")):
        if not f.is_file():
            continue
        st = f.stat()
        if st.st_mtime < ZIP_EPOCH:
            os.utime(f, (ZIP_EPOCH, ZIP_EPOCH))
        zf.write(f, f.relative_to(work).as_posix())
PY

    SIGNED_WHEELS=$((SIGNED_WHEELS + 1))
    SIGNED_BINARIES=$((SIGNED_BINARIES + BIN_COUNT))
    rm -rf "$WORK"
done

echo ""
echo "==> Wheel signing complete"
echo "    Total wheels scanned:   $TOTAL_WHEELS"
echo "    Wheels re-signed:       $SIGNED_WHEELS"
echo "    Native binaries signed: $SIGNED_BINARIES"
echo ""
echo "Done."
