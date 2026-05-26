#!/usr/bin/env bash
# sign-macos.sh — Signat + notarització macOS per a releases públiques de nexe-app.
#
# Flow complet (ADR-0008 active):
#   1. cargo tauri build --release  → genera .app + .dmg sense signar
#   2. codesign aplicat via TAURI_SIGNING_IDENTITY (signat de l'app)
#   3. xcrun notarytool submit    → Apple notarization servers
#   4. xcrun stapler staple       → pega el ticket de notarització al DMG
#
# Requisits previs (Jordi ha de configurar-los una vegada):
#   - Apple Developer Program account (99 USD/any)
#   - Developer ID Application certificate al Keychain
#   - App-specific password d'Apple ID (per notarytool)
#
# Ús:
#   export TAURI_SIGNING_IDENTITY="Developer ID Application: Jordi Goy (TEAMID)"
#   export TAURI_APPLE_ID="jgoy@jgoy.net"
#   export TAURI_APPLE_PASSWORD="@keychain:AC_PASSWORD"  # o valor directe
#   export TAURI_APPLE_TEAM_ID="XXXXXXXXXX"
#   ./scripts/sign-macos.sh
#
# Troubleshooting:
#   - `security find-identity -v -p codesigning` → veure certificats instal·lats
#   - `xcrun notarytool history --apple-id ... --team-id ...` → revisar submissions

set -euo pipefail
cd "$(dirname "$0")/.."

# Validació variables entorn
: "${TAURI_SIGNING_IDENTITY:?Need TAURI_SIGNING_IDENTITY (ex: 'Developer ID Application: Name (TEAMID)')}"
: "${TAURI_APPLE_ID:?Need TAURI_APPLE_ID (Apple ID email)}"
: "${TAURI_APPLE_PASSWORD:?Need TAURI_APPLE_PASSWORD (use @keychain:NAME, never a literal password)}"
: "${TAURI_APPLE_TEAM_ID:?Need TAURI_APPLE_TEAM_ID (10 char team ID)}"

# B21: reject literal passwords — must use @keychain: reference to avoid
# exposing credentials in shell history, CI logs, or process table.
if [ -n "${TAURI_APPLE_PASSWORD:-}" ] && [[ "$TAURI_APPLE_PASSWORD" != @keychain:* ]]; then
    echo "ERROR: TAURI_APPLE_PASSWORD must use @keychain: prefix (never a literal password)" >&2
    echo "       Set it with: security add-generic-password -a your@apple.id -s AC_PASSWORD -w" >&2
    echo "       Then export TAURI_APPLE_PASSWORD=@keychain:AC_PASSWORD" >&2
    exit 1
fi

echo "=== macOS Signing + Notarization ==="
echo "Identity : $TAURI_SIGNING_IDENTITY"
echo "Apple ID : $TAURI_APPLE_ID"
echo "Team ID  : $TAURI_APPLE_TEAM_ID"
echo ""

# Variables que tauri bundler llegeix directament
export APPLE_SIGNING_IDENTITY="$TAURI_SIGNING_IDENTITY"
export APPLE_ID="$TAURI_APPLE_ID"
export APPLE_PASSWORD="$TAURI_APPLE_PASSWORD"
export APPLE_TEAM_ID="$TAURI_APPLE_TEAM_ID"

echo "=== cargo tauri build --release ==="
cd src-tauri
cargo tauri build

echo ""
echo "=== Verificacio signatura ==="
APP="target/release/bundle/macos/nexe-app.app"
if [[ -d "$APP" ]]; then
    codesign -dvv "$APP" 2>&1 | grep -E "Identifier|TeamIdentifier|Authority|Sealed"
    # F3.4 BUG-NF-33: in strict mode (CI / release pipeline) treat a failing
    # spctl assess as a hard error instead of swallowing the exit code with `||`.
    # Pre-notarization runs should leave NEXE_STRICT_SIGNING unset (default) so
    # the warning is informational; the release-pipeline driver sets it to 1
    # right before notarization so the build fails fast on signing regressions.
    if [[ "${NEXE_STRICT_SIGNING:-0}" == "1" ]]; then
        spctl --assess --type execute --verbose=4 "$APP" || {
            echo "❌  spctl assess ha fallat (NEXE_STRICT_SIGNING=1) — abortant build"
            exit 1
        }
    else
        spctl --assess --type execute --verbose=4 "$APP" || {
            echo "⚠️  spctl assess ha fallat — comprovar notarització"
        }
    fi
fi

echo ""
echo "=== Verificacio notarització DMG ==="
# S11a F032: parametritzat — escanejem DMGs generats en lloc d'assumir nom.
# Suporta qualsevol version + arch (x86_64/aarch64/universal) sense hardcoding.
DMG_DIR="target/release/bundle/dmg"
if [[ -d "$DMG_DIR" ]]; then
    for DMG in "$DMG_DIR"/*.dmg; do
        [[ -f "$DMG" ]] || continue
        echo "Verificant $(basename "$DMG"):"
        spctl -a -t open --context context:primary-signature -v "$DMG" || {
            echo "⚠️  $(basename "$DMG") no notaritzat correctament"
        }
    done
else
    echo "⚠️  $DMG_DIR no existeix — cap DMG generat?"
fi

echo ""
echo "✅ Signing + notarization complet."
echo "Artifact: $APP"
echo "DMGs: $DMG_DIR/"
