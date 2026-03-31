#!/bin/bash
# ────────────────────────────────────────────────────────────────
# build_dmg.sh — Build "Install Nexe.dmg" from source
#
# Usage:
#   cd /path/to/server-nexe
#   bash installer/build_dmg.sh
#
# Requirements:
#   - macOS (hdiutil, osascript)
#   - Swift toolchain (for wizard binary)
#   - Python 3.11+ (for payload + models.json)
#   - installer/dmg_background.png (520x400 PNG)
#
# Output:
#   - "Install Nexe.dmg" at project root
#
# Notes:
#   - Codesign + notarization included (Developer ID Application: Jordi Goy)
#   - The wizard binary (InstallNexe) is built from swift-wizard/
#     If swift-wizard/ is not present, falls back to the launcher
#     shell script (dev mode)
# ────────────────────────────────────────────────────────────────
set -euo pipefail

# Flags
NOTARIZE=true
if [[ "${1:-}" == "--no-notarize" ]]; then
    NOTARIZE=false
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="InstallNexe"
APP_BUNDLE="$PROJECT_ROOT/$APP_NAME.app"
DMG_NAME="Install Nexe.dmg"
DMG_PATH="$PROJECT_ROOT/$DMG_NAME"
DMG_VOLUME_NAME="Install Nexe"
DMG_BACKGROUND="$SCRIPT_DIR/dmg_background.png"
SWIFT_WIZARD_DIR="$SCRIPT_DIR/swift-wizard"
BUNDLE_ID="net.jgoy.nexe-installer"
MIN_MACOS="13.0"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Step 0: Preflight checks ────────────────────────────────────
info "Preflight checks..."

[ -f "$DMG_BACKGROUND" ] || error "Missing dmg_background.png at $DMG_BACKGROUND"
[ -f "$SCRIPT_DIR/install_headless.py" ] || error "Missing installer scripts"
command -v hdiutil >/dev/null 2>&1 || error "hdiutil not found (macOS required)"

# ── Step 1: Build Swift wizard binary (if available) ─────────────
EXECUTABLE=""
EXECUTABLE_NAME=""

if [ -d "$SWIFT_WIZARD_DIR" ] && [ -f "$SWIFT_WIZARD_DIR/Package.swift" ]; then
    info "Building Swift wizard..."
    cd "$SWIFT_WIZARD_DIR"
    swift build -c release 2>&1 | tail -5
    SWIFT_BIN="$SWIFT_WIZARD_DIR/.build/arm64-apple-macosx/release/InstallNexe"
    if [ -x "$SWIFT_BIN" ]; then
        EXECUTABLE="$SWIFT_BIN"
        EXECUTABLE_NAME="InstallNexe"
        info "Swift wizard built OK"
    else
        warn "Swift build produced no binary, falling back to launcher"
    fi
    cd "$PROJECT_ROOT"
fi

if [ -z "$EXECUTABLE" ]; then
    # Fallback: use bash launcher (dev mode)
    LAUNCHER="$APP_BUNDLE/Contents/MacOS/launcher"
    if [ -f "$LAUNCHER" ]; then
        EXECUTABLE="$LAUNCHER"
        EXECUTABLE_NAME="launcher"
        warn "Using bash launcher (dev mode — no Swift wizard)"
    else
        error "No executable found. Need swift-wizard/ or existing app bundle."
    fi
fi

# ── Step 2: Create/refresh app bundle ────────────────────────────
info "Creating app bundle..."

CONTENTS="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
FRAMEWORKS="$CONTENTS/Frameworks"

# Clean old executables (keep python/ runtime and other resources)
rm -f "$MACOS_DIR/launcher" 2>/dev/null || true
rm -f "$MACOS_DIR/InstallNexe" 2>/dev/null || true
rm -rf "$RESOURCES/installer" 2>/dev/null || true
mkdir -p "$MACOS_DIR" "$RESOURCES/installer" "$FRAMEWORKS"

# Copy executable
cp "$EXECUTABLE" "$MACOS_DIR/$EXECUTABLE_NAME"
chmod +x "$MACOS_DIR/$EXECUTABLE_NAME"

# Info.plist
cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${EXECUTABLE_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>${MIN_MACOS}</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <false/>
    <key>LSArchitecturePriority</key>
    <array>
        <string>arm64</string>
        <string>x86_64</string>
    </array>
    <key>NSSupportsAutomaticTermination</key>
    <false/>
</dict>
</plist>
PLIST

# Copy installer scripts
for f in "$SCRIPT_DIR"/*.py; do
    [ -f "$f" ] && cp "$f" "$RESOURCES/installer/"
done

# Copy logo
[ -f "$SCRIPT_DIR/logo.png" ] && cp "$SCRIPT_DIR/logo.png" "$RESOURCES/"

# Copy icon (if exists in resources)
if [ -d "$SWIFT_WIZARD_DIR/Resources" ] && [ -f "$SWIFT_WIZARD_DIR/Resources/AppIcon.icns" ]; then
    cp "$SWIFT_WIZARD_DIR/Resources/AppIcon.icns" "$RESOURCES/"
elif [ -f "$RESOURCES/AppIcon.icns" ]; then
    : # already there
fi

# ── Step 3: Export models.json ───────────────────────────────────
if [ -f "$SCRIPT_DIR/export_catalog_json.py" ]; then
    info "Exporting models.json..."
    python3 "$SCRIPT_DIR/export_catalog_json.py" "$RESOURCES/models.json" 2>/dev/null || warn "models.json export failed (non-fatal)"
fi

# ── Step 4: Create payload.tar.gz ────────────────────────────────
info "Creating payload.tar.gz..."
PAYLOAD_TMP="$(mktemp -d)"
# Include essential project files (no venv, storage, .git, etc.)
tar czf "$PAYLOAD_TMP/payload.tar.gz" \
    -C "$PROJECT_ROOT" \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='qdrant' \
    --exclude='snapshots' \
    --exclude='.env' \
    --exclude='*.dmg' \
    --exclude='*.pkg' \
    --exclude='InstallNexe.app' \
    --exclude='Install Nexe.app' \
    --exclude='Nexe.app' \
    --exclude='diari' \
    --exclude='dev-tools' \
    --exclude='.claude' \
    --exclude='.DS_Store' \
    --exclude='.coverage' \
    --exclude='.build' \
    core/ plugins/ memory/ personality/ installer/ tests/ knowledge/ \
    setup.sh requirements.txt requirements-macos.txt pyproject.toml .env.example \
    install_nexe.py LICENSE COMMANDS.md 2>/dev/null || warn "Some files excluded from payload"

mv "$PAYLOAD_TMP/payload.tar.gz" "$RESOURCES/payload.tar.gz"
rm -rf "$PAYLOAD_TMP"

# ── Step 5: Copy Python runtime (if bundled) ─────────────────────
# The python/ and tcl-tk/ dirs + libpython3.12.dylib should already
# exist in the app bundle from a previous build or from
# installer/build-python-bundle.sh. We don't rebuild them here.
# See docs/BUILDING.md for the full build flow.
if [ ! -d "$RESOURCES/python" ]; then
    warn "No bundled Python runtime in app. Users will need system Python."
fi

# ── Step 6: Code sign app bundle ──────────────────────────────────
IDENTITY="${NEXE_SIGNING_IDENTITY:-Developer ID Application: Jordi Goy (NHG3THR2AF)}"
ENTITLEMENTS="$SWIFT_WIZARD_DIR/InstallNexe.entitlements"

if security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
    # Signar tots els binaris Mach-O del Python bundled individualment
    # (--deep no recorre Resources/python/ correctament i deixen signatura adhoc)
    if [ -d "$RESOURCES/python" ]; then
        info "Signing embedded Python binaries..."
        find "$RESOURCES/python" \( -name '*.dylib' -o -name '*.so' -o -perm +111 \) -type f | while read f; do
            if file "$f" | grep -q "Mach-O"; then
                codesign --force --sign "$IDENTITY" --options runtime --timestamp "$f" 2>/dev/null || true
                info "  Signed: $(basename "$f")"
            fi
        done
    fi

    info "Signing app bundle..."
    codesign --deep --force --verify --verbose \
        --sign "$IDENTITY" \
        --options runtime \
        --timestamp \
        --entitlements "$ENTITLEMENTS" \
        "$APP_BUNDLE"

    info "Verifying app signature..."
    codesign -dv "$APP_BUNDLE" 2>&1 || true
else
    warn "No signing identity found — app bundle will be unsigned"
fi

# ── Step 7: Build DMG ────────────────────────────────────────────
info "Building DMG..."

# Remove old DMG
[ -f "$DMG_PATH" ] && rm "$DMG_PATH"

# Create temporary DMG (read-write, empty)
DMG_TMP="$(mktemp -d)/tmp.dmg"
DMG_SIZE_MB=$(( $(du -sm "$APP_BUNDLE" | cut -f1) + 50 ))
[ "$DMG_SIZE_MB" -lt 100 ] && DMG_SIZE_MB=100

# Detach any previous volume with same name
hdiutil detach "/Volumes/$DMG_VOLUME_NAME" -force 2>/dev/null || true

hdiutil create \
    -size "${DMG_SIZE_MB}m" \
    -fs HFS+ \
    -volname "$DMG_VOLUME_NAME" \
    "$DMG_TMP" || error "hdiutil create failed"

# Mount read-write, copy app and add background
MOUNT_POINT="/Volumes/$DMG_VOLUME_NAME"
hdiutil attach "$DMG_TMP" -nobrowse -readwrite || error "hdiutil attach failed"

# Copy app bundle to DMG
cp -R "$APP_BUNDLE" "$MOUNT_POINT/"

# Add background
mkdir -p "$MOUNT_POINT/.background"
cp "$DMG_BACKGROUND" "$MOUNT_POINT/.background/background.png"

# Set window properties via AppleScript
osascript <<APPLESCRIPT
tell application "Finder"
    tell disk "$DMG_VOLUME_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {100, 100, 620, 500}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 128
        set background picture of viewOptions to file ".background:background.png"
        -- ⚠️ POSICIÓ VALIDADA — NO CANVIAR sense revisar amb el background (520x400)
        -- Finestra: {100,100,620,500} = 520x400. Icona centrada sobre el logo.
        set position of item "$APP_NAME.app" of container window to {260, 145}
        close
        open
        update without registering applications
        delay 1
        close
    end tell
end tell
APPLESCRIPT

# Unmount
sync
sleep 1
hdiutil detach "$MOUNT_POINT" -force 2>/dev/null || true
sleep 1

# Convert to compressed (read-only)
hdiutil convert "$DMG_TMP" \
    -format ULMO \
    -o "$DMG_PATH" || error "hdiutil convert failed"

rm -f "$DMG_TMP"

# ── Step 9: Sign DMG + Notarize ──────────────────────────────────
if security find-identity -v -p codesigning | grep -q "Developer ID Application"; then
    info "Signing DMG..."
    codesign --force --verify --verbose \
        --sign "$IDENTITY" \
        --timestamp \
        "$DMG_PATH"

    if [ "$NOTARIZE" = true ]; then
        if xcrun notarytool history --keychain-profile "nexe" >/dev/null 2>&1; then
            info "Submitting for notarization (this may take a few minutes)..."
            xcrun notarytool submit "$DMG_PATH" \
                --keychain-profile "nexe" \
                --wait

            info "Stapling notarization ticket..."
            xcrun stapler staple "$DMG_PATH"

            info "Verifying notarization..."
            spctl -a -t open --context context:primary-signature "$DMG_PATH" 2>&1 || warn "spctl check failed (may need retry)"
        else
            warn "Notarization credentials not found — skipping"
        fi
    else
        info "Notarization skipped (--no-notarize). Run without flag for final release."
    fi
else
    warn "No signing identity found — DMG will be unsigned"
fi

# ── Done ─────────────────────────────────────────────────────────
DMG_SIZE=$(du -h "$DMG_PATH" | cut -f1)
info "DMG built: $DMG_PATH ($DMG_SIZE)"
info "Done!"
