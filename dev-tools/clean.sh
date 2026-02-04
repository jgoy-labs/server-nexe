#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Nexe Server v0.8 - Clean Installation Script
# Esborra tots els fitxers generats per fer una instal·lació neta
# ─────────────────────────────────────────────────────────────

set -e

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
CYAN='\033[1;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear
echo -e "${BOLD}${RED}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${RED}║                                                        ║${NC}"
echo -e "${BOLD}${RED}║         NEXE - NETEJA PER INSTAL·LACIÓ NETA           ║${NC}"
echo -e "${BOLD}${RED}║                                                        ║${NC}"
echo -e "${BOLD}${RED}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}⚠️  ATENCIÓ: Aquesta acció esborrarà:${NC}"
echo -e "   ${CYAN}•${NC} venv/ (entorn virtual Python)"
echo -e "   ${CYAN}•${NC} .env (configuració amb claus API)"
echo -e "   ${CYAN}•${NC} storage/ (base de dades, models, logs, vectors)"
echo -e "   ${CYAN}•${NC} __pycache__/ (cache Python)"
echo -e "   ${CYAN}•${NC} *.pyc (fitxers compilats)"
echo -e "   ${CYAN}•${NC} .qdrant-initialized (marker files)"
echo -e "   ${CYAN}•${NC} COMMANDS.md (generat automàticament)"
echo ""
echo -e "${GREEN}✅ Es mantindran:${NC}"
echo -e "   ${CYAN}•${NC} Codi font (core/, plugins/, memory/, etc.)"
echo -e "   ${CYAN}•${NC} Documents a knowledge/ (si n'hi ha)"
echo -e "   ${CYAN}•${NC} Configuració personality/server.toml"
echo -e "   ${CYAN}•${NC} Scripts d'instal·lació"
echo ""
read -p "$(echo -e ${BOLD}Vols continuar? [y/N]:${NC} )" -n 1 -r
echo
if [[ ! $REPLY =~ ^[YySs]$ ]]
then
    echo -e "${CYAN}Neteja cancel·lada.${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}[1/8]${NC} Aturant processos..."
if [ "${CLEAN_KILL_PROCESSES}" = "true" ]; then
    echo -e "  ${YELLOW}⚠️${NC} CLEAN_KILL_PROCESSES=true: aturant processos globals (pot afectar altres projectes)"
    pkill -f "qdrant.*disable-telemetry" 2>/dev/null && echo "  ✓ Qdrant aturat" || echo "  - Qdrant no estava corrent"
    pkill -f "ollama serve" 2>/dev/null && echo "  ✓ Ollama aturat" || echo "  - Ollama no estava corrent"
    pkill -f "uvicorn.*nexe" 2>/dev/null && echo "  ✓ Servidor Nexe aturat" || echo "  - Nexe no estava corrent"
    sleep 1
else
    echo -e "  ${CYAN}-${NC} Saltant aturada de processos (set CLEAN_KILL_PROCESSES=true per forcar-ho)"
fi

echo -e "${BLUE}[2/8]${NC} Esborrant venv..."
if [ -d "venv" ]; then
    rm -rf venv
    echo -e "  ${GREEN}✓${NC} venv/ esborrat"
else
    echo -e "  ${CYAN}-${NC} venv/ no existia"
fi

echo -e "${BLUE}[3/8]${NC} Esborrant .env..."
if [ -f ".env" ]; then
    rm -f .env
    echo -e "  ${GREEN}✓${NC} .env esborrat"
else
    echo -e "  ${CYAN}-${NC} .env no existia"
fi

echo -e "${BLUE}[4/8]${NC} Esborrant storage/..."
if [ -d "storage" ]; then
    rm -rf storage
    echo -e "  ${GREEN}✓${NC} storage/ esborrat (models, DB, logs)"
else
    echo -e "  ${CYAN}-${NC} storage/ no existia"
fi

echo -e "${BLUE}[5/8]${NC} Esborrant cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
echo -e "  ${GREEN}✓${NC} __pycache__/ i *.pyc esborrats"

echo -e "${BLUE}[6/8]${NC} Esborrant marker files..."
rm -f .qdrant-initialized 2>/dev/null
rm -f storage/.knowledge_ingested 2>/dev/null
echo -e "  ${GREEN}✓${NC} Marker files esborrats"

echo -e "${BLUE}[7/8]${NC} Esborrant fitxers generats..."
rm -f COMMANDS.md 2>/dev/null
rm -f core/cli/.module_cache.json 2>/dev/null
echo -e "  ${GREEN}✓${NC} Fitxers generats esborrats"

echo -e "${BLUE}[8/8]${NC} Verificant neteja..."
CLEAN=true
[ -d "venv" ] && echo -e "  ${RED}✗${NC} venv/ encara existeix" && CLEAN=false
[ -f ".env" ] && echo -e "  ${RED}✗${NC} .env encara existeix" && CLEAN=false
[ -d "storage" ] && echo -e "  ${RED}✗${NC} storage/ encara existeix" && CLEAN=false

if [ "$CLEAN" = true ]; then
    echo -e "  ${GREEN}✓${NC} Neteja completada correctament"
else
    echo -e "  ${YELLOW}⚠${NC}  Alguns fitxers no s'han pogut esborrar"
fi

echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║                                                        ║${NC}"
echo -e "${BOLD}${GREEN}║              NETEJA COMPLETADA AMB ÈXIT                ║${NC}"
echo -e "${BOLD}${GREEN}║                                                        ║${NC}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Següent pas:${NC}"
echo -e "  ${BOLD}./setup.sh${NC}  # Per fer una instal·lació neta"
echo ""
