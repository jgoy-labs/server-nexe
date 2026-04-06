#!/bin/bash
# Script de verificació de fixes MLX

echo "🔍 Verificant fixes a l'instal·lador principal..."
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

check_file() {
    local file=$1
    local pattern=$2
    local description=$3
    
    if grep -q "$pattern" "$file" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $description"
        return 0
    else
        echo -e "${RED}✗${NC} $description"
        return 1
    fi
}

total=0
passed=0

# Check 1: install_nexe.py - Metal validation
((total++))
if check_file "install_nexe.py" "mx.metal.is_available()" "Metal validation en install_nexe.py"; then
    ((passed++))
fi

# Check 2: module.py - return False
((total++))
if check_file "plugins/mlx_module/module.py" "return False.*Metal is not available" "Return False quan Metal no disponible"; then
    ((passed++))
fi

# Check 3: module_manager.py - register all modules
((total++))
if check_file "personality/module_manager/module_manager.py" "registered as backend module" "Registrar mòduls backend"; then
    ((passed++))
fi

# Check 4: chat_cli.py - query /status
((total++))
if check_file "core/cli/chat_cli.py" "/status" "Query /status en CLI"; then
    ((passed++))
fi

# Check 5: root.py - /status endpoint
((total++))
if check_file "core/endpoints/root.py" "@router.get\(\"/status\"\)" "Endpoint /status"; then
    ((passed++))
fi

# Check 6: generate_helpers.py - stop_words
((total++))
if check_file "plugins/mlx_module/generate_helpers.py" "stop_words.*<\|end\|>" "Stop tokens configurats"; then
    ((passed++))
fi

# Check 7: server.toml - concise prompt
((total++))
if check_file "personality/server.toml" "BREU i DIRECTA" "System prompt concís"; then
    ((passed++))
fi

echo ""
echo "════════════════════════════════════════"
echo "RESULTAT: $passed/$total fixes verificats"
echo "════════════════════════════════════════"

if [ $passed -eq $total ]; then
    echo -e "${GREEN}✅ TOTS ELS FIXES APLICATS CORRECTAMENT${NC}"
    exit 0
else
    echo -e "${RED}❌ ALGUNS FIXES FALTEN${NC}"
    exit 1
fi
