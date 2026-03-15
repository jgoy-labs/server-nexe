#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Nexe Server v0.8 - Bootstrapper
# ─────────────────────────────────────────────────────────────

set -e

# Colors
BLUE='\033[1;34m'
CYAN='\033[1;36m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Detect system language ────────────────────────────────────
SYS_LANG="${LANG:-en_US}"
case "$SYS_LANG" in
    ca_*|ca) _L="ca" ;;
    es_*|es) _L="es" ;;
    *)       _L="en" ;;
esac

# ── i18n strings ──────────────────────────────────────────────
if [ "$_L" = "ca" ]; then
    _VERIFYING="Verificant entorn..."
    _NO_PYTHON="No s'ha trobat Python 3.10 o superior."
    _BREW_FOUND="S'ha trobat Homebrew. Instal·lant Python 3.12 automàticament..."
    _CONTINUE="Continuar? [S/n]:"
    _NO_BREW="Homebrew no trobat. Instal·lant Homebrew + Python 3.12..."
    _ERROR_PYTHON="No s'ha pogut trobar Python 3.10+. Instal·la'l manualment:"
    _THEN_RUN="Després torna a executar: ./setup.sh"
    _DETECTED="detectat"
    _CLEANING_CACHE="Netejant cache Python..."
    _CACHE_CLEAN="Cache Python netejat"
    _PREV_DETECTED="Instal·lació anterior detectada."
    _FULL_CLEANUP="Vols fer una neteja completa abans d'instal·lar? (recomanat) [S/n]:"
    _CLEANING_PREV="Netejant instal·lació anterior..."
    _STOPPED="aturat"
    _DELETED="eliminat"
    _CLEANUP_DONE="Neteja completada."
    _CLEANUP_SKIP="Neteja omesa. Continuant instal·lació..."
    _VENV_REQUIRED="venv eliminat (requerit per la instal·lació)."
elif [ "$_L" = "es" ]; then
    _VERIFYING="Verificando entorno..."
    _NO_PYTHON="No se ha encontrado Python 3.10 o superior."
    _BREW_FOUND="Se ha encontrado Homebrew. Instalando Python 3.12 automáticamente..."
    _CONTINUE="¿Continuar? [S/n]:"
    _NO_BREW="Homebrew no encontrado. Instalando Homebrew + Python 3.12..."
    _ERROR_PYTHON="No se ha podido encontrar Python 3.10+. Instálalo manualmente:"
    _THEN_RUN="Después vuelve a ejecutar: ./setup.sh"
    _DETECTED="detectado"
    _CLEANING_CACHE="Limpiando caché Python..."
    _CACHE_CLEAN="Caché Python limpiada"
    _PREV_DETECTED="Instalación anterior detectada."
    _FULL_CLEANUP="¿Quieres hacer una limpieza completa antes de instalar? (recomendado) [S/n]:"
    _CLEANING_PREV="Limpiando instalación anterior..."
    _STOPPED="detenido"
    _DELETED="eliminado"
    _CLEANUP_DONE="Limpieza completada."
    _CLEANUP_SKIP="Limpieza omitida. Continuando instalación..."
    _VENV_REQUIRED="venv eliminado (requerido para la instalación)."
else
    _VERIFYING="Verifying environment..."
    _NO_PYTHON="Python 3.10 or higher not found."
    _BREW_FOUND="Homebrew found. Installing Python 3.12 automatically..."
    _CONTINUE="Continue? [Y/n]:"
    _NO_BREW="Homebrew not found. Installing Homebrew + Python 3.12..."
    _ERROR_PYTHON="Could not find Python 3.10+. Install it manually:"
    _THEN_RUN="Then run again: ./setup.sh"
    _DETECTED="detected"
    _CLEANING_CACHE="Cleaning Python cache..."
    _CACHE_CLEAN="Python cache cleaned"
    _PREV_DETECTED="Previous installation detected."
    _FULL_CLEANUP="Do you want to perform a full cleanup before installing? (recommended) [Y/n]:"
    _CLEANING_PREV="Cleaning previous installation..."
    _STOPPED="stopped"
    _DELETED="deleted"
    _CLEANUP_DONE="Cleanup complete."
    _CLEANUP_SKIP="Cleanup skipped. Continuing installation..."
    _VENV_REQUIRED="venv deleted (required for installation)."
fi

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
echo -e "${BLUE}[STEP]${NC} $_VERIFYING"

# Find Python >= 3.10
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
    echo -e "${YELLOW}[WARN]${NC} $_NO_PYTHON"

    if command -v brew &> /dev/null; then
        echo -e "${CYAN}→${NC} $_BREW_FOUND"
        echo -e "${CYAN}$_CONTINUE${NC} "
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
        echo -e "${YELLOW}→${NC} $_NO_BREW"
        echo -e "${CYAN}$_CONTINUE${NC} "
        read -r -n 1 _brew_response
        echo ""
        if [[ ! $_brew_response =~ ^[Nn]$ ]]; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
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
        echo -e "${RED}[ERROR]${NC} $_ERROR_PYTHON"
        echo -e "  ${CYAN}→${NC} brew install python@3.12"
        echo -e "  ${CYAN}→${NC} $_THEN_RUN"
        exit 1
    fi
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ${GREEN}✓${NC} Python ${PYTHON_VERSION} $_DETECTED ($PYTHON_BIN)"

# Python cache cleanup
echo -e "${BLUE}[CLEAN]${NC} $_CLEANING_CACHE"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
echo -e "  ${GREEN}✓${NC} $_CACHE_CLEAN"

echo ""
if [ -d "venv" ] || [ -f ".env" ] || [ -d "storage" ]; then
    echo -e "${YELLOW}[CLEAN]${NC} $_PREV_DETECTED"
    echo -e "${CYAN}$_FULL_CLEANUP${NC} "
    read -r -n 1 response
    echo ""
    if [[ ! $response =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}[CLEAN]${NC} $_CLEANING_PREV"

        pkill -f "qdrant.*disable-telemetry" 2>/dev/null && echo "  ✓ Qdrant $_STOPPED" || true
        pkill -f "ollama serve" 2>/dev/null && echo "  ✓ Ollama $_STOPPED" || true
        pkill -f "uvicorn.*nexe" 2>/dev/null && echo "  ✓ Nexe Server $_STOPPED" || true
        sleep 1

        [ -d "venv" ] && rm -rf venv && echo "  ✓ venv/ $_DELETED"
        [ -f ".env" ] && rm -f .env && echo "  ✓ .env $_DELETED"
        [ -d "storage" ] && rm -rf storage && echo "  ✓ storage/ $_DELETED"
        rm -f .qdrant-initialized 2>/dev/null
        rm -f COMMANDS.md 2>/dev/null

        echo -e "${GREEN}[OK]${NC} $_CLEANUP_DONE"
    else
        echo -e "${CYAN}[INFO]${NC} $_CLEANUP_SKIP"
        if [ -d "venv" ]; then
            rm -rf venv
            echo -e "${YELLOW}[CLEAN]${NC} $_VENV_REQUIRED"
        fi
    fi
fi
echo ""

# Run the Python installer (has its own i18n)
"$PYTHON_BIN" install_nexe.py "$@"
