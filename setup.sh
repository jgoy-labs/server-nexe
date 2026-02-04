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
NC='\033[0m' # No Color

clear
echo -e "${RED}"
echo "      _                                               "
echo "     / /  ___  ___ _ ____   _____ _ __    _ __   _____  __  ___ "
echo "    / /  / __|/ _ \ '__\ \ / / _ \ '__|  | '_ \ / _ \ \ \/ / _ \\"
echo "   / /   \__ \  __/ |   \ V /  __/ |  _  | | | |  __/>  <  __/ "
echo "  /_/    |___/\___|_|    \_/ \___|_| (_) |_| |_|\___/_/\_\\___| "
echo -e "${NC}"
echo -e "${BLUE}[STEP]${NC} Verifying environment..."

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    echo -e "${RED}[ERROR]${NC} Python3 not found. Please install Python 3.9 or higher."
    exit 1
fi

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
python3 install_nexe.py "$@"
