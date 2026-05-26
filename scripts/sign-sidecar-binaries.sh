#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────
# sign-sidecar-binaries.sh
# Re-signs every Mach-O binary inside target/sidecar/ with our Developer
# ID certificate, secure timestamp, and hardened runtime.
#
# F5.2b: scope = target/sidecar/venv (333 Mach-O wheels + libs).
# F5.2.1 (2026-05-18): scope expanded to target/sidecar/ complet — inclou
# python-runtime/ (PBS copiat dins el bundle): bin/python3.12 + ~45-55 .so
# de lib-dynload (ssl, socket, hashlib, ctypes, sqlite3, ...). codesign
# --force substitueix la signatura CMS upstream del PBS per la nostra
# Developer ID — comportament correcte per a notarytool Apple, que exigeix
# que tots els Mach-O del bundle estiguin signats amb la mateixa identity
# que l'app. Sense aquesta expansió F5.2.1, el python3.12 del PBS quedaria
# amb signatura CMS upstream que Gatekeeper accepta peró notarytool no
# valida com a part del nostre Developer ID team.
#
# Why (F5.2b): el PBS venv conté centenars de .so/.dylib signats ad-hoc
# pels autors dels wheels (o no signats). Apple notarization rebutja tot
# el .app si qualsevol Mach-O annidat no porta Developer ID + timestamp +
# hardened runtime. Submission FAIL `4d42c92d-44ab-4405-...` va llistar
# _miniaudio.abi3.so, _cffi_backend, mmh3, + dotzenes més com a issues.
#
# Difference vs server-nexe legacy `sign-wheels-bundle.sh`: aquell operava
# sobre .whl files (unpack → sign → repack amb sha256 RECORD). Aquí el
# venv ja està extret (PBS+uv install), només cal caminar el bundle i
# signar in-place — sense round-trip zip.
#
# Usage:
#   APPLE_SIGNING_IDENTITY="Developer ID Application: Jordi Goy (NHG3THR2AF)" \
#     bash scripts/sign-sidecar-binaries.sh [SIDECAR_DIR]
#
# If APPLE_SIGNING_IDENTITY is unset, the script exits 0 with a warning
# (dev-mode build without certificate). Release builds must set it.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SIDECAR_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)/target/sidecar}"

if [ ! -d "$SIDECAR_DIR/venv" ]; then
    echo "ERROR: venv directory missing: $SIDECAR_DIR/venv" >&2
    echo "       Run scripts/build-sidecar.sh first." >&2
    exit 1
fi

if [ -z "${APPLE_SIGNING_IDENTITY:-}" ]; then
    echo "==> sign-sidecar-binaries: APPLE_SIGNING_IDENTITY unset → skipping (dev build)"
    exit 0
fi

# Verify the identity is actually available in the keychain. `find-identity`
# matches by substring so we strip the cert prefix and grep for the unique
# Team ID in parens.
if ! security find-identity -v -p codesigning 2>/dev/null | grep -qF "$APPLE_SIGNING_IDENTITY"; then
    echo "ERROR: Signing identity not found in keychain: $APPLE_SIGNING_IDENTITY" >&2
    echo "       Available identities:" >&2
    security find-identity -v -p codesigning >&2
    exit 2
fi

echo "==> Signing Mach-O binaries in $SIDECAR_DIR"
echo "    Scope: venv/ + python-runtime/ (F5.2.1 expansion)"
echo "    Identity: $APPLE_SIGNING_IDENTITY"

TOTAL=0
SIGNED=0
SKIPPED=0
FAILED=0
START=$(date +%s)

# Candidate files: .so, .dylib, anything with exec bit (catches torch's
# protoc, torch_shm_manager, PBS python3.12 binary, etc.).
# Filter actual Mach-O via `file` magic (skips shell scripts, .pyc, text).
# F5.2.1: find ara cobreix $SIDECAR_DIR complet — venv/ + python-runtime/
# (PBS). Veure header per justificació.
while IFS= read -r -d '' f; do
    if ! file "$f" 2>/dev/null | grep -q "Mach-O"; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    TOTAL=$((TOTAL + 1))
    if codesign --force --options=runtime --timestamp \
            --sign "$APPLE_SIGNING_IDENTITY" "$f" >/dev/null 2>&1; then
        SIGNED=$((SIGNED + 1))
    else
        FAILED=$((FAILED + 1))
        echo "    sign failed: ${f#"$SIDECAR_DIR/"}" >&2
    fi
done < <(find "$SIDECAR_DIR" -type f \
    \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) \
    -print0)

ELAPSED=$(($(date +%s) - START))

echo "==> Sign report"
echo "    Mach-O signed:    $SIGNED / $TOTAL"
echo "    Non-Mach-O skipped: $SKIPPED"
echo "    Failed:           $FAILED"
echo "    Time:             ${ELAPSED}s"

if [ "$FAILED" -gt 0 ]; then
    echo "❌ $FAILED Mach-O failed to sign — aborting" >&2
    exit 3
fi

echo "✓ All Mach-O signed with Developer ID + timestamp + hardened runtime"
