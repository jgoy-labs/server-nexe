#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Nexe Server v0.8 - Bootstrapper
# ─────────────────────────────────────────────────────────────

set -e

# Installer metadata
BLUE='\033[1;34m'
CYAN='\033[1;36m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

clear
echo -e "${RED}"
echo "    -                                                                 "
echo "   ####           :#########.   :#######*   .###-  *##+   =#######+  "
echo "     ####=        :###.   ###  *##+    ###    ###* ##:   ###+   .###  "
echo "       *###*      :##*     ##.:###########*    ####.    +###########+ "
echo "       .####      :##+     ##..###:.           #####.   =###:.        "
echo "     =####        :##+     ##. =###+  =##    :###-###=   *###=  +##   "
echo "   ####=          :##+     ##.   =######-   *###   -###    +######.   "
echo "   .#.                                                                 "
echo -e "${NC}"
echo -e "${BLUE}[STEP]${NC} Verifying environment..."

# Find Python >= 3.10 (checks python3.11, python3.12, python3.10, brew paths, then python3)
PYTHON_BIN=""
for candidate in \
    python3.12 python3.11 python3.10 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /opt/homebrew/bin/python3.10 \
    /usr/local/bin/python3.11 \
    /usr/local/bin/python3.10 \
    python3
do
    if command -v "$candidate" &> /dev/null; then
        _MAJOR=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        _MINOR=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$_MAJOR" -eq 3 ] && [ "$_MINOR" -ge 10 ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR]${NC} No s'ha trobat Python 3.10 o superior."
    echo -e "  ${CYAN}→${NC} brew install python@3.11"
    echo -e "  ${CYAN}→${NC} Després torna a executar: ./setup.sh"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ${GREEN}✓${NC} Python ${PYTHON_VERSION} detectat ($PYTHON_BIN)"

# AUTOMATIC PYTHON CACHE CLEANUP (always, no prompt)
# Necessary when copying directory between locations
echo -e "${BLUE}[CLEAN]${NC} Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
echo -e "  ${GREEN}✓${NC} Python cache cleaned"

# Automatic cleanup: Remove generated files to avoid conflicts
echo ""
if [ -d "venv" ] || [ -f ".env" ] || [ -d "storage" ]; then
    echo -e "${YELLOW}[CLEAN]${NC} Previous installation detected."
    echo -e "${CYAN}Do you want to perform a full cleanup before installing? (recommended) [Y/n]:${NC} "
    read -r -n 1 response
    echo ""
    if [[ ! $response =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}[CLEAN]${NC} Cleaning previous installation..."

        # Stop processes
        pkill -f "qdrant.*disable-telemetry" 2>/dev/null && echo "  ✓ Qdrant stopped" || true
        pkill -f "ollama serve" 2>/dev/null && echo "  ✓ Ollama stopped" || true
        pkill -f "uvicorn.*nexe" 2>/dev/null && echo "  ✓ Nexe Server stopped" || true
        sleep 1

        # Delete generated files
        [ -d "venv" ] && rm -rf venv && echo "  ✓ venv/ deleted"
        [ -f ".env" ] && rm -f .env && echo "  ✓ .env deleted"
        [ -d "storage" ] && rm -rf storage && echo "  ✓ storage/ deleted"
        rm -f .qdrant-initialized 2>/dev/null
        rm -f COMMANDS.md 2>/dev/null

        echo -e "${GREEN}[OK]${NC} Cleanup complete."
    else
        echo -e "${CYAN}[INFO]${NC} Cleanup skipped. Continuing installation..."
        # Minimum required: venv must always be deleted
        if [ -d "venv" ]; then
            rm -rf venv
            echo -e "${YELLOW}[CLEAN]${NC} Venv deleted (required for installation)."
        fi
    fi
fi
echo ""

# Run the actual Python installer
"$PYTHON_BIN" install_nexe.py "$@"
