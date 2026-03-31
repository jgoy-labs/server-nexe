#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-python-bundle.sh
# Downloads python-build-standalone, trims it, and places it inside
# Install Nexe.app so the GUI launcher works without any system Python.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
# Use InstallNexe.app (no spaces — macOS Sequoia provenance fix 2026-03-29)
APP_DIR="$PROJECT_ROOT/InstallNexe.app"
RESOURCES="$APP_DIR/Contents/Resources"
FRAMEWORKS="$APP_DIR/Contents/Frameworks"

PY_VERSION="3.12"
PY_FULL="3.12.8"
PBS_TAG="20250106"

# Allow architecture override: TARGET_ARCH=x86_64 bash dev-tools/build-python-bundle.sh
ARCH="${TARGET_ARCH:-$(uname -m)}"
case "$ARCH" in
    arm64|aarch64) PBS_ARCH="aarch64" ;;
    x86_64)        PBS_ARCH="x86_64"  ;;
    *)
        echo "ERROR: Unsupported architecture: $ARCH" >&2
        exit 1
        ;;
esac

PBS_FILENAME="cpython-${PY_FULL}+${PBS_TAG}-${PBS_ARCH}-apple-darwin-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_FILENAME}"

TMPDIR_BUILD="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_BUILD"' EXIT

echo "==> Downloading python-build-standalone ($PBS_ARCH)..."
echo "    $PBS_URL"
curl -fSL --retry 3 -o "$TMPDIR_BUILD/$PBS_FILENAME" "$PBS_URL"

echo "==> Extracting..."
tar xzf "$TMPDIR_BUILD/$PBS_FILENAME" -C "$TMPDIR_BUILD"

# The tarball extracts to python/install/ or just python/
EXTRACTED="$TMPDIR_BUILD/python"
if [ -d "$EXTRACTED/install" ]; then
    EXTRACTED="$EXTRACTED/install"
fi

if [ ! -x "$EXTRACTED/bin/python3" ] && [ ! -x "$EXTRACTED/bin/python${PY_VERSION}" ]; then
    echo "ERROR: Could not find python3 binary in extracted archive" >&2
    ls -la "$EXTRACTED/bin/" >&2
    exit 1
fi

# ── Step 3: Trim unnecessary modules ────────────────────────────────────
echo "==> Trimming unnecessary modules..."
STDLIB="$EXTRACTED/lib/python${PY_VERSION}"
TRIM_DIRS=(
    "test"
    "tests"
    # NOT trimming ensurepip — needed by venv module to bootstrap pip
    "idlelib"
    "turtledemo"
    "lib2to3"
    "pydoc_data"
    "distutils"
    "__pycache__"
    "unittest/test"
    "tkinter/test"
)
for d in "${TRIM_DIRS[@]}"; do
    if [ -d "$STDLIB/$d" ]; then
        rm -rf "$STDLIB/$d"
        echo "    Removed $d"
    fi
done

# Remove __pycache__ recursively
find "$EXTRACTED" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ── Step 4: Place files into app bundle ─────────────────────────────────
echo "==> Installing into app bundle..."

# Clean previous bundle
rm -rf "$RESOURCES/python" "$RESOURCES/tcl-tk" "$FRAMEWORKS"
mkdir -p "$RESOURCES/python" "$RESOURCES/tcl-tk/lib" "$FRAMEWORKS"

# Copy Python tree
cp -a "$EXTRACTED/"* "$RESOURCES/python/"

# Ensure python3 symlink exists
if [ ! -e "$RESOURCES/python/bin/python3" ] && [ -x "$RESOURCES/python/bin/python${PY_VERSION}" ]; then
    ln -sf "python${PY_VERSION}" "$RESOURCES/python/bin/python3"
fi

# Locate Tcl/Tk data directories and libraries
TCL_VER=""
for v in 8.6 9.0; do
    if [ -d "$RESOURCES/python/lib/tcl$v" ]; then
        TCL_VER="$v"
        break
    fi
done

if [ -z "$TCL_VER" ]; then
    # Try inside share/
    for v in 8.6 9.0; do
        if [ -d "$RESOURCES/python/share/tcl$v" ]; then
            TCL_VER="$v"
            # Move from share to lib for consistency
            cp -a "$RESOURCES/python/share/tcl$v" "$RESOURCES/python/lib/tcl$v"
            [ -d "$RESOURCES/python/share/tk$v" ] && cp -a "$RESOURCES/python/share/tk$v" "$RESOURCES/python/lib/tk$v"
            break
        fi
    done
fi

if [ -n "$TCL_VER" ]; then
    echo "    Tcl/Tk version: $TCL_VER"
    # Copy Tcl/Tk data to Resources/tcl-tk/lib/
    [ -d "$RESOURCES/python/lib/tcl$TCL_VER" ] && cp -a "$RESOURCES/python/lib/tcl$TCL_VER" "$RESOURCES/tcl-tk/lib/"
    [ -d "$RESOURCES/python/lib/tk$TCL_VER" ]  && cp -a "$RESOURCES/python/lib/tk$TCL_VER"  "$RESOURCES/tcl-tk/lib/"
else
    echo "WARNING: Could not find Tcl/Tk data directories" >&2
fi

# Copy dylibs to Frameworks/
echo "==> Copying dylibs to Frameworks/..."
for lib in "$RESOURCES/python/lib/"lib{tcl,tk,python}*.dylib; do
    [ -f "$lib" ] && cp -a "$lib" "$FRAMEWORKS/"
done

# Also check in lib/ subdirectory patterns
for lib in "$RESOURCES/python/lib/"*.dylib; do
    [ -f "$lib" ] || continue
    basename_lib="$(basename "$lib")"
    case "$basename_lib" in
        libtcl*|libtk*|libpython*)
            [ ! -f "$FRAMEWORKS/$basename_lib" ] && cp -a "$lib" "$FRAMEWORKS/"
            ;;
    esac
done

# ── Step 5: Fix @rpath for _tkinter ────────────────────────────────────
echo "==> Fixing _tkinter.so rpath..."
TKINTER_SO="$(find "$RESOURCES/python/lib/python${PY_VERSION}/lib-dynload" -name '_tkinter*.so' 2>/dev/null | head -1)"
if [ -n "$TKINTER_SO" ]; then
    echo "    Found: $TKINTER_SO"

    # Update dylib references to use @rpath
    for dep in $(otool -L "$TKINTER_SO" | awk '/libtcl|libtk/ {print $1}'); do
        basename_dep="$(basename "$dep")"
        install_name_tool -change "$dep" "@rpath/$basename_dep" "$TKINTER_SO" 2>/dev/null || true
    done

    # Add rpath entries pointing to Frameworks/ and Resources/python/lib/
    # From lib-dynload: ../=python3.12, ../../=lib, ../../../=python, ../../../../=Resources, ../../../../../=Contents
    install_name_tool -add_rpath "@loader_path/../../../../../Frameworks" "$TKINTER_SO" 2>/dev/null || true
    install_name_tool -add_rpath "@loader_path/../../" "$TKINTER_SO" 2>/dev/null || true
else
    echo "WARNING: _tkinter.so not found — tkinter may not work" >&2
fi

# Also fix libpython if referenced by _tkinter
if [ -n "$TKINTER_SO" ]; then
    for dep in $(otool -L "$TKINTER_SO" | awk '/libpython/ {print $1}'); do
        basename_dep="$(basename "$dep")"
        install_name_tool -change "$dep" "@rpath/$basename_dep" "$TKINTER_SO" 2>/dev/null || true
    done
fi

# ── Step 6: Validate ───────────────────────────────────────────────────
echo "==> Validating bundled Python..."
BUNDLED_PY="$RESOURCES/python/bin/python3"

export PYTHONNOUSERSITE=1
# Note: NOT setting PYTHONHOME — the launcher doesn't set it either.
# python-build-standalone install_only builds are relocatable and find stdlib
# relative to the binary. Setting PYTHONHOME could mask runtime failures.
export DYLD_FALLBACK_LIBRARY_PATH="$FRAMEWORKS${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"

# Set TCL/TK env vars
for v in 9.0 8.6; do
    if [ -d "$RESOURCES/tcl-tk/lib/tcl$v" ]; then
        export TCL_LIBRARY="$RESOURCES/tcl-tk/lib/tcl$v"
        break
    fi
done
for v in 9.0 8.6; do
    if [ -d "$RESOURCES/tcl-tk/lib/tk$v" ]; then
        export TK_LIBRARY="$RESOURCES/tcl-tk/lib/tk$v"
        break
    fi
done

"$BUNDLED_PY" -c "import sys; print(f'  Python {sys.version}')"
"$BUNDLED_PY" -c "import encodings; print('  encodings: OK')"
"$BUNDLED_PY" -c "import tkinter, _tkinter; print(f'  tkinter: OK (Tk {_tkinter.TK_VERSION})')"

echo "  All validations passed."

# ── Step 7: Copy installer packages into app bundle ────────────────────
DEV_MODE="${1:-}"
echo "==> Copying installer packages into app bundle..."

rm -rf "$RESOURCES/installer" "$RESOURCES/personality"

if [ "$DEV_MODE" = "--dev" ]; then
    echo "    DEV MODE: creating symlinks (changes apply instantly)"
    ln -sf "$PROJECT_ROOT/installer" "$RESOURCES/installer"
    [ -d "$PROJECT_ROOT/personality" ] && ln -sf "$PROJECT_ROOT/personality" "$RESOURCES/personality"
else
    cp -R "$PROJECT_ROOT/installer" "$RESOURCES/installer"
    [ -d "$PROJECT_ROOT/personality" ] && cp -R "$PROJECT_ROOT/personality" "$RESOURCES/personality"

    # Clean copied packages
    find "$RESOURCES/installer" "$RESOURCES/personality" \
        \( -type d -name "__pycache__" -o -name ".DS_Store" -o -name "*.pyc" \) \
        -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true
    echo "    Copied and cleaned installer + personality"
fi

# ── Step 8: Ad-hoc codesign ────────────────────────────────────────────
echo "==> Codesigning binaries and dylibs..."
SIGN_COUNT=0
while IFS= read -r f; do
    codesign --force --sign - "$f" 2>/dev/null && SIGN_COUNT=$((SIGN_COUNT + 1))
done < <(find "$RESOURCES/python" "$FRAMEWORKS" \( -name '*.dylib' -o -name '*.so' -o -perm +111 -type f \) 2>/dev/null)
echo "    Signed $SIGN_COUNT files."

# Final deep verify
echo "==> Verifying app signature..."
codesign --verify --deep --strict "$APP_DIR" 2>&1 || echo "WARNING: Deep codesign verification failed (may need full signing identity)"

# Size report
echo ""
echo "==> Bundle size:"
du -sh "$RESOURCES/python"
du -sh "$RESOURCES/tcl-tk"
du -shL "$RESOURCES/installer"
du -sh "$FRAMEWORKS"
echo ""
echo "Done. Bundled Python ${PY_FULL} (${PBS_ARCH}) into Install Nexe.app"
