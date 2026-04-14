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

# ── Step 3: Copy models.json (Swift tier format) ─────────────────
MODELS_SRC="$SCRIPT_DIR/swift-wizard/Resources/models.json"
if [ -f "$MODELS_SRC" ]; then
    info "Copying models.json (tier format)..."
    cp "$MODELS_SRC" "$RESOURCES/models.json"
    TIER_COUNT=$(python3 -c "import json; d=json.load(open('$RESOURCES/models.json')); print(len(d))" 2>/dev/null || echo "?")
    info "  tiers: $TIER_COUNT"
else
    warn "models.json not found at $MODELS_SRC"
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
    --exclude='NexeTray.app' \
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

# ── Step 4a-bis: Sync .plist versions des de pyproject.toml ─────
# Garanteix que Nexe.app i NexeTray.app porten la versió del projecte
# abans de bundlejar-les. Font única: pyproject.toml ([project].version).
info "Syncing Info.plist versions from pyproject.toml..."
if python3 -m installer.sync_plist_versions; then
    info "  Plist versions synced OK"
else
    warn "  Plist sync failed — continuing with possibly stale versions"
fi

# ── Step 4a-ter: Compilar launcher Swift natiu per Nexe.app ─────
# El launcher natiu (vs bash script) gestiona applicationShouldHandleReopen,
# apareix a Força la Sortida, i estabilitza el triangle "app activa" al Dock.
# Reemplaca Nexe.app/Contents/MacOS/NexeTray amb el binari compilat.
LAUNCHER_SRC="$SCRIPT_DIR/nexe_launcher.swift"
LAUNCHER_DEST="$PROJECT_ROOT/Nexe.app/Contents/MacOS/NexeTray"
if [ -f "$LAUNCHER_SRC" ] && [ -d "$PROJECT_ROOT/Nexe.app/Contents/MacOS" ]; then
    info "Compiling native Nexe launcher (Swift)..."
    if swiftc -O -o "$LAUNCHER_DEST" "$LAUNCHER_SRC" 2>&1; then
        chmod +x "$LAUNCHER_DEST"
        # Esborrar bash obsolet `nexe-tray` (sense capital) si hi era
        rm -f "$PROJECT_ROOT/Nexe.app/Contents/MacOS/nexe-tray"
        info "  Launcher compilat OK ($(du -h "$LAUNCHER_DEST" | cut -f1))"
    else
        error "Swift launcher compilation failed — Nexe.app Dock behavior breaks."
    fi
fi

# ── Step 4b: Bundle Nexe.app i NexeTray.app inside installer resources ─
# Ambdues són excluded del payload.tar.gz (són .app bundles, no codi font).
# Han de viatjar dins InstallNexe.app/Contents/Resources/ perquè el Swift
# wizard les desplegui a installPath just abans d'executar install_headless.
if [ -d "$PROJECT_ROOT/Nexe.app" ]; then
    info "Bundling Nexe.app into installer resources..."
    rm -rf "$RESOURCES/Nexe.app"
    cp -R "$PROJECT_ROOT/Nexe.app" "$RESOURCES/Nexe.app"
    info "  Nexe.app bundled OK"
else
    error "Nexe.app not found at $PROJECT_ROOT/Nexe.app — DMG sense Nexe.app = sense icona Dock ni Login Item. Aborting."
fi

if [ -d "$PROJECT_ROOT/installer/NexeTray.app" ]; then
    info "Bundling NexeTray.app into installer resources..."
    rm -rf "$RESOURCES/NexeTray.app"
    cp -R "$PROJECT_ROOT/installer/NexeTray.app" "$RESOURCES/NexeTray.app"
    info "  NexeTray.app bundled OK"
else
    error "NexeTray.app not found at $PROJECT_ROOT/installer/NexeTray.app — DMG sense tray = servidor no arrenca. Aborting."
fi

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

    # Signar launcher natiu de Nexe.app (Swift binary). `--deep` NO el cobreix
    # dins Resources/ — cal explícit amb hardened runtime + timestamp perquè
    # Apple accepti notarització.
    NEXE_LAUNCHER="$RESOURCES/Nexe.app/Contents/MacOS/NexeTray"
    if [ -f "$NEXE_LAUNCHER" ] && file "$NEXE_LAUNCHER" | grep -q "Mach-O"; then
        info "Signing Nexe.app native launcher..."
        codesign --force --sign "$IDENTITY" --options runtime --timestamp "$NEXE_LAUNCHER"
        info "  Signed: Nexe.app/Contents/MacOS/NexeTray"
    fi
    # Signar el bundle Nexe.app complet (seal de Info.plist, Resources, etc.)
    # NO usem --deep aquí: el launcher intern (NexeTray) ja ha estat signat
    # explícitament a dalt. --deep re-signaria i podria heretar entitlements
    # del wrapper extern, cosa que NO volem (el launcher no els necessita).
    if [ -d "$RESOURCES/Nexe.app" ]; then
        codesign --force --sign "$IDENTITY" --options runtime --timestamp "$RESOURCES/Nexe.app"
        info "  Signed: Nexe.app bundle (bottom-up, sense --deep)"
    fi
    # NexeTray.app (bash wrapper del tray — Step 4b)
    if [ -d "$RESOURCES/NexeTray.app" ]; then
        codesign --force --sign "$IDENTITY" --options runtime --timestamp "$RESOURCES/NexeTray.app"
        info "  Signed: NexeTray.app bundle"
    fi

    # Frameworks del bundle extern (InstallNexe.app): signar explícitament
    # abans del bundle pare perquè el seal final ja trobi les firmes correctes.
    if [ -d "$APP_BUNDLE/Contents/Frameworks" ]; then
        info "Signing InstallNexe.app Frameworks..."
        find "$APP_BUNDLE/Contents/Frameworks" -type f \( -name '*.dylib' -o -perm +111 \) | while read f; do
            if file "$f" | grep -q "Mach-O"; then
                codesign --force --sign "$IDENTITY" --options runtime --timestamp "$f" 2>/dev/null || true
            fi
        done
    fi

    info "Signing app bundle (wrapper, sense --deep)..."
    # NO --deep: evita re-signar recursivament el bundle intern Nexe.app i
    # que el seu launcher hereti els entitlements d'InstallNexe.
    codesign --force --verify --verbose \
        --sign "$IDENTITY" \
        --options runtime \
        --timestamp \
        --entitlements "$ENTITLEMENTS" \
        "$APP_BUNDLE"

    info "Verifying app signature..."
    codesign -dv "$APP_BUNDLE" 2>&1 || true

    # ── Verificació: launcher intern NO ha d'heretar entitlements del wrapper ──
    # Nota: sintaxi `--entitlements -` (sense `:`) és la recomanada per Apple a macOS 26+.
    # La vella `:-` emet un warning deprecation que es colava al check i generava
    # fals positius. Filtrem també warning:/Error: per robustesa a futurs avisos.
    NEXE_LAUNCHER_ENT="$(codesign -d --entitlements - "$RESOURCES/Nexe.app/Contents/MacOS/NexeTray" 2>&1 \
        | grep -vE '^(Executable=|warning:|Error:)' \
        | tr -d '[:space:]')"
    if [ -n "$NEXE_LAUNCHER_ENT" ]; then
        warn "Nexe.app/Contents/MacOS/NexeTray té entitlements — NO hauria (fuga des del wrapper extern?)"
        codesign -d --entitlements - "$RESOURCES/Nexe.app/Contents/MacOS/NexeTray" || true
    else
        info "  OK: NexeTray no hereta entitlements del wrapper"
    fi

    # Verificació final (strict, --deep aquí només inspecciona — NO re-signa)
    info "Verifying final bundle (strict + deep inspect)..."
    codesign --verify --strict --deep --verbose=2 "$APP_BUNDLE" 2>&1 || warn "codesign --verify ha reportat problemes"
else
    warn "No signing identity found — app bundle will be unsigned"
fi

# ── Step 7: Build DMG ────────────────────────────────────────────
info "Building DMG..."

# Remove old DMG
[ -f "$DMG_PATH" ] && rm "$DMG_PATH"

# Detach any previous volume with same name
hdiutil detach "/Volumes/$DMG_VOLUME_NAME" -force 2>/dev/null || true

# Crear staging dir amb l'app bundle
DMG_STAGING="$(mktemp -d)/dmg_staging"
mkdir -p "$DMG_STAGING"
cp -R "$APP_BUNDLE" "$DMG_STAGING/"

info "Building DMG..."
# create-dmg gestiona background, icones i DS_Store correctament a Sequoia
# ⚠️ POSICIÓ VALIDADA — NO CANVIAR {260, 145} sense revisar el background (520x400)
CREATE_DMG="$(which create-dmg 2>/dev/null || echo /opt/homebrew/bin/create-dmg)"
if [ ! -x "$CREATE_DMG" ]; then
    error "create-dmg no trobat. Instal·la: brew install create-dmg"
fi

"$CREATE_DMG" \
    --volname "$DMG_VOLUME_NAME" \
    --background "$DMG_BACKGROUND" \
    --window-pos 100 100 \
    --window-size 520 400 \
    --icon-size 128 \
    --icon "$APP_NAME.app" 260 145 \
    --no-internet-enable \
    "$DMG_PATH" \
    "$DMG_STAGING/" || {
    warn "create-dmg AppleScript failed — retrying with --skip-jenkins (no background)"
    rm -f "$DMG_PATH"
    "$CREATE_DMG" \
        --volname "$DMG_VOLUME_NAME" \
        --window-pos 100 100 \
        --window-size 520 400 \
        --icon-size 128 \
        --icon "$APP_NAME.app" 260 145 \
        --no-internet-enable \
        --skip-jenkins \
        "$DMG_PATH" \
        "$DMG_STAGING/" || error "create-dmg failed (both attempts)"
    warn "DMG creat sense background (Finder no disponible)"
}

rm -rf "$DMG_STAGING"

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
