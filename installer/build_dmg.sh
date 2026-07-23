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
#   - Codesign + notarization included (identity from $NEXE_SIGNING_IDENTITY)
#   - The wizard binary (InstallNexe) is built from swift-wizard/
#     If swift-wizard/ is not present, falls back to the launcher
#     shell script (dev mode)
# ────────────────────────────────────────────────────────────────
set -euo pipefail

# Flags
NOTARIZE=true
SKIP_BUNDLES=false
for arg in "$@"; do
    case "$arg" in
        --no-notarize)   NOTARIZE=false ;;
        --skip-bundles)  SKIP_BUNDLES=true ;;  # reuse existing wheels+embeddings (dev iter)
    esac
done

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
MIN_MACOS="14.0"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
# Exit code 14: offline-install bundles missing or too small.
bundle_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 14; }

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
    core/ plugins/ memory/ personality/ installer/ knowledge/ \
    setup.sh requirements.txt requirements-macos.txt pyproject.toml .env.example \
    install_nexe.py LICENSE COMMANDS.md 2>/dev/null || warn "Some files excluded from payload"

mv "$PAYLOAD_TMP/payload.tar.gz" "$RESOURCES/payload.tar.gz"
rm -rf "$PAYLOAD_TMP"

# ── Step 4a-bis: Sync .plist versions from pyproject.toml ─────
# Ensures Nexe.app and NexeTray.app carry the project version
# before bundling them. Single source: pyproject.toml ([project].version).
info "Syncing Info.plist versions from pyproject.toml..."
if python3 -m installer.sync_plist_versions; then
    info "  Plist versions synced OK"
else
    warn "  Plist sync failed — continuing with possibly stale versions"
fi

# ── Step 4a-ter: Compile native Swift launcher for Nexe.app ─────
# The native launcher (vs bash script) handles applicationShouldHandleReopen,
# appears in Force Quit, and stabilizes the "app active" triangle in the Dock.
# Replaces Nexe.app/Contents/MacOS/NexeTray with the compiled binary.
LAUNCHER_SRC="$SCRIPT_DIR/nexe_launcher.swift"
LAUNCHER_DEST="$PROJECT_ROOT/Nexe.app/Contents/MacOS/NexeTray"
if [ -f "$LAUNCHER_SRC" ] && [ -d "$PROJECT_ROOT/Nexe.app/Contents/MacOS" ]; then
    info "Compiling native Nexe launcher (Swift)..."
    if swiftc -O -o "$LAUNCHER_DEST" "$LAUNCHER_SRC" 2>&1; then
        chmod +x "$LAUNCHER_DEST"
        # Remove the obsolete bash `nexe-tray` (lowercase) if present
        rm -f "$PROJECT_ROOT/Nexe.app/Contents/MacOS/nexe-tray"
        info "  Launcher compilat OK ($(du -h "$LAUNCHER_DEST" | cut -f1))"
    else
        error "Swift launcher compilation failed — Nexe.app Dock behavior breaks."
    fi
fi

# ── Step 4b: Bundle Nexe.app i NexeTray.app inside installer resources ─
# Both are excluded from payload.tar.gz (they are .app bundles, not source code).
# They must travel inside InstallNexe.app/Contents/Resources/ so the Swift
# wizard deploys them to installPath just before running install_headless.
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

# ── Step 5a: Build wheels bundle (offline install) ───────────────
# Downloads all Python wheels as arm64 macOS 14+ binaries into
# Resources/wheels/ so the client installer runs `pip install` with
# --no-index --find-links, without ever touching PyPI or compiling.
# Net effect: zero Xcode Command Line Tools prompt at install time.
WHEELS_DIR="$RESOURCES/wheels"
EMBEDDINGS_DIR="$RESOURCES/embeddings"
OLLAMA_ZIP="$RESOURCES/ollama/Ollama-darwin.zip"

if [ "$SKIP_BUNDLES" = true ]; then
    warn "Skipping bundle rebuild (--skip-bundles) — reusing existing bundles"
else
    info "Building Python wheels bundle (~220 MB, arm64 macOS 14+)..."
    if ! bash "$SCRIPT_DIR/build-wheels-bundle.sh"; then
        bundle_error "build-wheels-bundle.sh failed. DMG would require online install."
    fi
    info "  Wheels bundle ready"

    info "Building embedding model bundle (~283 MB, int8 quantized)..."
    if ! bash "$SCRIPT_DIR/build-embedding-bundle.sh"; then
        bundle_error "build-embedding-bundle.sh failed. DMG would lack RAG at first boot."
    fi
    info "  Embedding bundle ready"

    info "Building Ollama bundle (~156 MB)..."
    if ! bash "$SCRIPT_DIR/build-ollama-bundle.sh"; then
        bundle_error "build-ollama-bundle.sh failed. DMG would require online Ollama download."
    fi
    info "  Ollama bundle ready"
fi

# ── Step 5b: Validate bundle sizes (exit 14 on failure) ──────────
# These checks catch silent failures of the build scripts (e.g. all
# caches already populated, empty download) before we ship a DMG that
# would fail at install time on the client machine.
if [ ! -d "$WHEELS_DIR" ]; then
    bundle_error "Wheels bundle missing at $WHEELS_DIR"
fi
if [ ! -d "$EMBEDDINGS_DIR" ]; then
    bundle_error "Embedding bundle missing at $EMBEDDINGS_DIR"
fi
if [ ! -f "$OLLAMA_ZIP" ]; then
    bundle_error "Ollama bundle missing at $OLLAMA_ZIP"
fi

WHEELS_SIZE_MB=$(du -sm "$WHEELS_DIR" | cut -f1)
EMBEDDINGS_SIZE_MB=$(du -sm "$EMBEDDINGS_DIR" | cut -f1)
OLLAMA_SIZE_MB=$(du -m "$OLLAMA_ZIP" | cut -f1)
info "  Wheels:     ${WHEELS_SIZE_MB} MB"
info "  Embeddings: ${EMBEDDINGS_SIZE_MB} MB"
info "  Ollama:     ${OLLAMA_SIZE_MB} MB"

if [ "$WHEELS_SIZE_MB" -lt 100 ]; then
    bundle_error "Wheels bundle only ${WHEELS_SIZE_MB} MB — expected 100+ MB."
fi
if [ "$EMBEDDINGS_SIZE_MB" -lt 200 ]; then
    bundle_error "Embedding bundle only ${EMBEDDINGS_SIZE_MB} MB — expected 200+ MB (int8 quantized model)."
fi

# ── Step 6: Code sign app bundle ──────────────────────────────────
# Identity from env (release). Unset → placeholder that won't match the keychain → signing skipped (dev build).
IDENTITY="${NEXE_SIGNING_IDENTITY:-UNSET_SIGNING_IDENTITY}"
ENTITLEMENTS="$SWIFT_WIZARD_DIR/InstallNexe.entitlements"

if security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
    # Step 6a: sign the native binaries inside the bundle wheels.
    # PyPI wheels carry .so/.dylib signed ad-hoc (or by their author)
    # without a secure timestamp; Apple Notarization rejects any nested
    # Mach-O without a Developer ID. This script iterates each wheel, signs
    # the .so/.dylib with our identity + timestamp + hardened
    # runtime, regenerates the RECORD and re-packages the wheel.
    if [ -d "$WHEELS_DIR" ] && ls "$WHEELS_DIR"/*.whl >/dev/null 2>&1; then
        info "Signing native binaries inside wheel bundle..."
        if ! bash "$SCRIPT_DIR/sign-wheels-bundle.sh"; then
            echo -e "${RED}[ERROR]${NC} sign-wheels-bundle.sh failed — notarization would reject the DMG." >&2
            exit 1
        fi
        info "  Wheels bundle signed"
    fi

    # Sign every Mach-O binary of the bundled Python individually
    # (--deep does not traverse Resources/python/ correctly and they keep an ad-hoc signature)
    if [ -d "$RESOURCES/python" ]; then
        info "Signing embedded Python binaries..."
        find "$RESOURCES/python" \( -name '*.dylib' -o -name '*.so' -o -perm +111 \) -type f | while read -r f; do
            if file "$f" | grep -q "Mach-O"; then
                codesign --force --sign "$IDENTITY" --options runtime --timestamp "$f" 2>/dev/null || true
                info "  Signed: $(basename "$f")"
            fi
        done
    fi

    # Sign the native Nexe.app launcher (Swift binary). `--deep` does NOT cover it
    # inside Resources/ — it must be explicit with hardened runtime + timestamp so
    # Apple accepts notarization.
    NEXE_LAUNCHER="$RESOURCES/Nexe.app/Contents/MacOS/NexeTray"
    if [ -f "$NEXE_LAUNCHER" ] && file "$NEXE_LAUNCHER" | grep -q "Mach-O"; then
        info "Signing Nexe.app native launcher..."
        codesign --force --sign "$IDENTITY" --options runtime --timestamp "$NEXE_LAUNCHER"
        info "  Signed: Nexe.app/Contents/MacOS/NexeTray"
    fi
    # Sign the full Nexe.app bundle (seal of Info.plist, Resources, etc.)
    # We do NOT use --deep here: the internal launcher (NexeTray) has already been
    # signed explicitly above. --deep would re-sign and could inherit entitlements
    # from the external wrapper, which we do NOT want (the launcher doesn't need them).
    if [ -d "$RESOURCES/Nexe.app" ]; then
        codesign --force --sign "$IDENTITY" --options runtime --timestamp "$RESOURCES/Nexe.app"
        info "  Signed: Nexe.app bundle (bottom-up, sense --deep)"
    fi
    # NexeTray.app (bash wrapper of the tray — Step 4b)
    if [ -d "$RESOURCES/NexeTray.app" ]; then
        codesign --force --sign "$IDENTITY" --options runtime --timestamp "$RESOURCES/NexeTray.app"
        info "  Signed: NexeTray.app bundle"
    fi

    # Frameworks of the external bundle (InstallNexe.app): sign explicitly
    # before the parent bundle so the final seal finds the correct signatures.
    if [ -d "$APP_BUNDLE/Contents/Frameworks" ]; then
        info "Signing InstallNexe.app Frameworks..."
        find "$APP_BUNDLE/Contents/Frameworks" -type f \( -name '*.dylib' -o -perm +111 \) | while read -r f; do
            if file "$f" | grep -q "Mach-O"; then
                codesign --force --sign "$IDENTITY" --options runtime --timestamp "$f" 2>/dev/null || true
            fi
        done
    fi

    info "Signing app bundle (wrapper, sense --deep)..."
    # NO --deep: avoids recursively re-signing the internal Nexe.app bundle and
    # its launcher inheriting the InstallNexe entitlements.
    codesign --force --verify --verbose \
        --sign "$IDENTITY" \
        --options runtime \
        --timestamp \
        --entitlements "$ENTITLEMENTS" \
        "$APP_BUNDLE"

    info "Verifying app signature..."
    codesign -dv "$APP_BUNDLE" 2>&1 || true

    # ── Verification: the internal launcher must NOT inherit the wrapper's entitlements ──
    # Note: the `--entitlements -` syntax (without `:`) is the one Apple recommends on macOS 26+.
    # The old `:-` emits a deprecation warning that leaked into the check and produced
    # false positives. We also filter warning:/Error: for robustness against future notices.
    NEXE_LAUNCHER_ENT="$(codesign -d --entitlements - "$RESOURCES/Nexe.app/Contents/MacOS/NexeTray" 2>&1 \
        | { grep -vE '^(Executable=|warning:|Error:)' || true; } \
        | tr -d '[:space:]')"
    if [ -n "$NEXE_LAUNCHER_ENT" ]; then
        warn "Nexe.app/Contents/MacOS/NexeTray té entitlements — NO hauria (fuga des del wrapper extern?)"
        codesign -d --entitlements - "$RESOURCES/Nexe.app/Contents/MacOS/NexeTray" || true
    else
        info "  OK: NexeTray no hereta entitlements del wrapper"
    fi

    # Final verification (strict, --deep here only inspects — does NOT re-sign)
    info "Verifying final bundle (strict + deep inspect)..."
    codesign --verify --strict --deep --verbose=2 "$APP_BUNDLE" 2>&1 || warn "codesign --verify ha reportat problemes"
else
    if [ "${NEXE_RELEASE:-0}" = "1" ]; then
        error "No signing identity found — aborting release build (B193): a release app bundle must never be unsigned"
    else
        warn "No signing identity found — app bundle will be unsigned"
    fi
fi

# ── Step 7: Build DMG ────────────────────────────────────────────
info "Building DMG..."

# Remove old DMG
[ -f "$DMG_PATH" ] && rm "$DMG_PATH"

# Detach any previous volume with same name
hdiutil detach "/Volumes/$DMG_VOLUME_NAME" -force 2>/dev/null || true

# Create staging dir with the app bundle
DMG_STAGING="$(mktemp -d)/dmg_staging"
mkdir -p "$DMG_STAGING"
cp -R "$APP_BUNDLE" "$DMG_STAGING/"

info "Building DMG..."
# create-dmg handles background, icons and DS_Store correctly on Sequoia
# ⚠️ VALIDATED POSITION — DO NOT CHANGE {260, 145} without reviewing the background (520x400)
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
if security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
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
            if ! spctl -a -t open --context context:primary-signature "$DMG_PATH" 2>&1; then
                if [ "${NEXE_RELEASE:-0}" = "1" ]; then
                    error "spctl post-staple verification failed — aborting release build (B193)"
                else
                    warn "spctl check failed (may need retry)"
                fi
            fi
        else
            if [ "${NEXE_RELEASE:-0}" = "1" ]; then
                error "Notarization keychain-profile 'nexe' not found — aborting release build (B193)"
            else
                warn "Notarization credentials not found — skipping"
            fi
        fi
    else
        if [ "${NEXE_RELEASE:-0}" = "1" ]; then
            error "Notarization skipped (--no-notarize) but NEXE_RELEASE=1 — a release DMG must be notarized (B193)"
        else
            info "Notarization skipped (--no-notarize). Run without flag for final release."
        fi
    fi
else
    if [ "${NEXE_RELEASE:-0}" = "1" ]; then
        error "No signing identity found — aborting release build (B193): a release DMG must never be unsigned"
    else
        warn "No signing identity found — DMG will be unsigned"
    fi
fi

# ── Release artifact assertion (belt & suspenders): a NEXE_RELEASE=1 DMG
# must be BOTH signed (some Developer ID TeamIdentifier) and stapled.
# The gates above should make this unreachable-on-failure; this is the
# final honest check on the artifact itself, not on the flow.
if [ "${NEXE_RELEASE:-0}" = "1" ]; then
    info "Release assertion: verifying DMG signature + notarization ticket..."
    codesign -dv "$DMG_PATH" 2>&1 | grep -Eq "TeamIdentifier=[A-Z0-9]{10}" \
        || error "Release assertion failed: DMG has no real TeamIdentifier (unsigned or ad-hoc)"
    xcrun stapler validate "$DMG_PATH" \
        || error "Release assertion failed: DMG has no valid notarization ticket"
    info "Release assertion OK (signed + stapled)"
fi

# ── Done ─────────────────────────────────────────────────────────
DMG_SIZE=$(du -h "$DMG_PATH" | cut -f1)
info "DMG built: $DMG_PATH ($DMG_SIZE)"
info "Done!"
