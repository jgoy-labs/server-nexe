#!/bin/bash
# ────────────────────────────────────
# Instal·lar Nexe
# 1. Asks where to install
# 2. Copies project files there (out of Downloads quarantine)
# 3. Launches the GUI installer from the new location
# ────────────────────────────────────

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Detect language ───────────────────────────────────────────────────────
SYS_LANG=$(defaults read -g AppleLanguages 2>/dev/null | head -2 | tail -1 | tr -d '[:space:],"' || echo "en")

case "$SYS_LANG" in
    ca*) MSG_CHOOSE="Tria on vols instal·lar Nexe:"
         MSG_COPYING="Copiant fitxers..."
         MSG_ERROR="Error copiant els fitxers."
         MSG_NO_PYTHON="Cal Python 3.11+ amb tkinter.\n\nInstal·la'l amb:\n  brew install python@3.12 python-tk@3.12"
         ;;
    es*) MSG_CHOOSE="Elige dónde instalar Nexe:"
         MSG_COPYING="Copiando archivos..."
         MSG_ERROR="Error copiando los archivos."
         MSG_NO_PYTHON="Se necesita Python 3.11+ con tkinter.\n\nInstálalo con:\n  brew install python@3.12 python-tk@3.12"
         ;;
    *)   MSG_CHOOSE="Choose where to install Nexe:"
         MSG_COPYING="Copying files..."
         MSG_ERROR="Error copying files."
         MSG_NO_PYTHON="Python 3.11+ with tkinter is required.\n\nInstall with:\n  brew install python@3.12 python-tk@3.12"
         ;;
esac

# ── Ask install location ─────────────────────────────────────────────────
DEST=$(osascript -e "set d to choose folder with prompt \"$MSG_CHOOSE\" default location (path to home folder)" -e 'return POSIX path of d' 2>/dev/null) || {
    echo "Cancelled."
    exit 0
}

INSTALL_DIR="${DEST}server-nexe"

# ── Copy files ────────────────────────────────────────────────────────────
echo "$MSG_COPYING"

if [ -d "$INSTALL_DIR" ]; then
    # Already exists — update files but keep storage/, .env, venv/
    rsync -a --exclude='storage/' --exclude='.env' --exclude='venv/' --exclude='.venv/' "$SOURCE_DIR/" "$INSTALL_DIR/"
else
    mkdir -p "$INSTALL_DIR"
    rsync -a "$SOURCE_DIR/" "$INSTALL_DIR/"
fi

# Clear quarantine on the copied files
xattr -cr "$INSTALL_DIR" 2>/dev/null

# ── Find Python 3.11+ with tkinter ───────────────────────────────────────
PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$candidate" ]; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || continue
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            if "$candidate" -c "import tkinter" 2>/dev/null; then
                PYTHON_BIN="$candidate"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    osascript -e "display dialog \"$MSG_NO_PYTHON\" buttons {\"OK\"} with title \"Install Nexe\" with icon stop" 2>/dev/null
    exit 1
fi

# ── Launch GUI installer from the clean location ─────────────────────────
cd "$INSTALL_DIR"
"$PYTHON_BIN" -m installer.gui &

# Close this Terminal window
osascript -e 'tell application "Terminal" to close front window' 2>/dev/null &
