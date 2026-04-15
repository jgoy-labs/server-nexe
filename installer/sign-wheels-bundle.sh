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
# signature. Signing the .so files before the DMG is built makes the
# notarization pass (429 issues -> 0 in the run that motivated this
# script: submission e4311642-9af8-4546-883e-25b8c03e148b, 2026-04-16).
#
# A wheel is a ZIP; we unpack, codesign each native file, re-pack. The
# RECORD file inside the wheel carries sha256 hashes for each entry —
# pip install does not re-check them at install time by default, but to
# keep external tooling happy we regenerate RECORD after signing.
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

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH (needed to regenerate RECORD)" >&2
    exit 3
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "==> Signing native binaries inside wheels"
echo "    Certificate: $CERT"
echo "    Wheels dir:  $WHEELS_DIR"

# ── Step 2: Iterate wheels and sign ────────────────────────────────────
TOTAL_WHEELS=0
SIGNED_WHEELS=0
SIGNED_BINARIES=0

for whl in "$WHEELS_DIR"/*.whl; do
    [ -f "$whl" ] || continue
    TOTAL_WHEELS=$((TOTAL_WHEELS + 1))

    # Skip wheels that don't contain native binaries (pure-Python).
    # NOTE: `grep -q` closes the pipe early, causing `unzip` to die with
    # SIGPIPE; with `set -o pipefail` the whole pipe then reports failure
    # and `if !` would swallow it as "no match". Use `grep -c` with `|| true`
    # so the pipe always finishes cleanly and we inspect the count.
    so_count=$(unzip -l "$whl" 2>/dev/null | grep -cE '\.(so|dylib)$' || true)
    if [ "${so_count:-0}" -eq 0 ]; then
        continue
    fi

    basename=$(basename "$whl")
    WORK="$TMP_DIR/${basename}.d"
    rm -rf "$WORK"
    mkdir -p "$WORK"

    (cd "$WORK" && unzip -q "$whl")

    # Sign every native file. --force replaces any ad-hoc signature;
    # --timestamp adds the secure timestamp Apple notarization requires;
    # --options runtime enables the hardened runtime (same as our app).
    BIN_COUNT=0
    while IFS= read -r -d '' sofile; do
        codesign --force --timestamp --options runtime \
            --sign "$CERT" "$sofile" >/dev/null 2>&1
        BIN_COUNT=$((BIN_COUNT + 1))
    done < <(find "$WORK" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)

    if [ "$BIN_COUNT" -eq 0 ]; then
        # Should not happen after the unzip -l filter, but stay safe.
        continue
    fi

    # Regenerate RECORD so the file list + hashes stay consistent with
    # our (now re-signed) .so binaries. We find it under *.dist-info/RECORD.
    RECORD_PATH=$(find "$WORK" -type f -path '*.dist-info/RECORD' -print -quit)
    if [ -n "$RECORD_PATH" ]; then
        DIST_INFO_DIR=$(dirname "$RECORD_PATH")
        python3 - "$WORK" "$DIST_INFO_DIR" "$RECORD_PATH" <<'PY'
import base64
import hashlib
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
dist_info = Path(sys.argv[2])
record_path = Path(sys.argv[3])

def rec_hash(p: Path) -> tuple[str, int]:
    data = p.read_bytes()
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}", len(data)

lines = []
for f in sorted(root.rglob("*")):
    if not f.is_file():
        continue
    rel = f.relative_to(root).as_posix()
    # RECORD itself is listed with empty hash+size per PEP 376.
    if f == record_path:
        lines.append(f"{rel},,\n")
        continue
    h, size = rec_hash(f)
    lines.append(f"{rel},{h},{size}\n")

record_path.write_text("".join(lines), encoding="utf-8")
PY
    fi

    # Re-zip the wheel. -X strips extra file attributes that would
    # otherwise bloat the zip and (on some tools) confuse readers.
    # -r recurse; we zip *from inside WORK* so paths are relative,
    # exactly as pip expects.
    rm -f "$whl"
    (cd "$WORK" && zip -X -q -r "$whl" .)

    SIGNED_WHEELS=$((SIGNED_WHEELS + 1))
    SIGNED_BINARIES=$((SIGNED_BINARIES + BIN_COUNT))

    # Clean up this wheel's workdir promptly — 1 GB+ of wheels unpacked
    # would easily overflow /tmp otherwise.
    rm -rf "$WORK"
done

# ── Step 3: Report ─────────────────────────────────────────────────────
echo ""
echo "==> Wheel signing complete"
echo "    Total wheels scanned:   $TOTAL_WHEELS"
echo "    Wheels re-signed:       $SIGNED_WHEELS"
echo "    Native binaries signed: $SIGNED_BINARIES"
echo ""
echo "Done."
