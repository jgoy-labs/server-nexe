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
echo -e "${BLUE}[STEP]${NC} Verificant entorn..."

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
    echo -e "${YELLOW}[WARN]${NC} No s'ha trobat Python 3.10 o superior."

    # Try to install via Homebrew
    if command -v brew &> /dev/null; then
        echo -e "${CYAN}→${NC} S'ha trobat Homebrew. Instal·lant Python 3.12 automàticament..."
        echo -e "${CYAN}Continuar? [Y/n]:${NC} "
        read -r -n 1 _py_response
        echo ""
        if [[ ! $_py_response =~ ^[Nn]$ ]]; then
            brew install python@3.12
            for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3.12; do
                if command -v "$candidate" &> /dev/null; then
                    PYTHON_BIN="$candidate"
                    break
                fi
            done
        fi
    else
        echo -e "${YELLOW}→${NC} Homebrew no trobat. Instal·lant Homebrew + Python 3.12..."
        echo -e "${CYAN}Continuar? [Y/n]:${NC} "
        read -r -n 1 _brew_response
        echo ""
        if [[ ! $_brew_response =~ ^[Nn]$ ]]; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Add brew to PATH for this session
            [ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
            [ -f /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
            brew install python@3.12
            for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3.12; do
                if command -v "$candidate" &> /dev/null; then
                    PYTHON_BIN="$candidate"
                    break
                fi
            done
        fi
    fi

    if [ -z "$PYTHON_BIN" ]; then
        echo -e "${RED}[ERROR]${NC} No s'ha pogut trobar Python 3.10+. Instal·la'l manualment:"
        echo -e "  ${CYAN}→${NC} brew install python@3.12"
        echo -e "  ${CYAN}→${NC} Després torna a executar: ./setup.sh"
        exit 1
    fi
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ${GREEN}✓${NC} Python ${PYTHON_VERSION} detectat ($PYTHON_BIN)"

# AUTOMATIC PYTHON CACHE CLEANUP (always, no prompt)
# Necessary when copying directory between locations
echo -e "${BLUE}[CLEAN]${NC} Netejant cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
echo -e "  ${GREEN}✓${NC} Cache Python netejat"

# Automatic cleanup: Remove generated files to avoid conflicts
echo ""
if [ -d "venv" ] || [ -f ".env" ] || [ -d "storage" ]; then
    echo -e "${YELLOW}[CLEAN]${NC} Instal·lació anterior detectada."
    echo -e "${CYAN}Vols fer una neteja completa abans d'instal·lar? (recomanat) [S/n]:${NC} "
    read -r -n 1 response
    echo ""
    if [[ ! $response =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}[CLEAN]${NC} Netejant instal·lació anterior..."

        # Aturar processos
        pkill -f "qdrant.*disable-telemetry" 2>/dev/null && echo "  ✓ Qdrant aturat" || true
        pkill -f "ollama serve" 2>/dev/null && echo "  ✓ Ollama aturat" || true
        pkill -f "uvicorn.*nexe" 2>/dev/null && echo "  ✓ Nexe Server aturat" || true
        sleep 1

        # Delete generated files
        [ -d "venv" ] && rm -rf venv && echo "  ✓ venv/ eliminat"
        [ -f ".env" ] && rm -f .env && echo "  ✓ .env eliminat"
        [ -d "storage" ] && rm -rf storage && echo "  ✓ storage/ eliminat"
        rm -f .qdrant-initialized 2>/dev/null
        rm -f COMMANDS.md 2>/dev/null

        echo -e "${GREEN}[OK]${NC} Neteja completada."
    else
        echo -e "${CYAN}[INFO]${NC} Neteja omesa. Continuant instal·lació..."
        # Mínim requerit: venv sempre s'ha d'eliminar
        if [ -d "venv" ]; then
            rm -rf venv
            echo -e "${YELLOW}[CLEAN]${NC} venv eliminat (requerit per la instal·lació)."
        fi
    fi
fi
echo ""

# Run the actual Python installer
"$PYTHON_BIN" install_nexe.py "$@"
