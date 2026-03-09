#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# dev-tools/run_all_day.sh
# GPU All-Day Test Orchestrator — Nexe Server
#
# Executa totes les fases de test mentre la GPU és disponible:
#   Fase 0 — Tests unitaris (sense GPU, sempre primers)
#   Fase 1 — Integració Ollama  (phi3:mini o model configurat)
#   Fase 2 — Integració MLX     (model llama local en ARM64)
#   Fase 3 — Integració llama.cpp (GGUF model local)
#   Fase 4 — Tests E2E complets (amb millor backend disponible)
#   Fase 5 — Coverage final + informe
#
# Ús:
#   ./dev-tools/run_all_day.sh                     # totes les fases
#   ./dev-tools/run_all_day.sh --unit-only         # només fase 0
#   ./dev-tools/run_all_day.sh --skip-mlx          # skip MLX
#   ./dev-tools/run_all_day.sh --skip-llamacpp     # skip llama.cpp
#   ./dev-tools/run_all_day.sh --fast              # 1 iteració (no loop)
#   ./dev-tools/run_all_day.sh --loops N           # N iteracions
#
# Models locals (sense descàrrega):
#   Ollama:      phi3:mini  (ja instal·lat)
#   MLX:         /Users/jgoy/NatSytem/DEV/NAT7-DEV/crom/models/Meta-Llama-3.1-8B-Instruct-4bit
#   llama.cpp:   /Users/jgoy/NatSytem/DEV/NAT7-DEV/crom/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
MAGENTA='\033[0;35m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }
phase()   { echo -e "\n${BOLD}${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n  $*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
section() { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

# ── Paths ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/all_day_${TIMESTAMP}.log"
COVERAGE_DIR="$ROOT/coverage_html"
SUMMARY_FILE="$LOG_DIR/all_day_summary_${TIMESTAMP}.txt"
mkdir -p "$LOG_DIR"
cd "$ROOT"

# ── Flags ───────────────────────────────────────────────────
UNIT_ONLY=false
SKIP_MLX=false
SKIP_LLAMACPP=false
FAST=false
MAX_LOOPS=999
for arg in "$@"; do
  case $arg in
    --unit-only)   UNIT_ONLY=true ;;
    --skip-mlx)    SKIP_MLX=true ;;
    --skip-llamacpp) SKIP_LLAMACPP=true ;;
    --fast)        FAST=true; MAX_LOOPS=1 ;;
    --loops)       shift; MAX_LOOPS="${1:-1}" ;;
  esac
done

# ── Python ──────────────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
  error "python3 not found"; exit 1
fi

# ── Notification (macOS) ─────────────────────────────────────
notify() {
  local title="$1"; local msg="$2"
  if command -v osascript &>/dev/null; then
    osascript -e "display notification \"$msg\" with title \"$title\"" 2>/dev/null || true
  fi
}

# ── Resultats acumulats ──────────────────────────────────────
declare -A PHASE_RESULTS
GLOBAL_EXIT=0

record() {
  local phase="$1"; local result="$2"; local extra="${3:-}"
  PHASE_RESULTS["$phase"]="$result${extra:+ ($extra)}"
  if [[ "$result" == "FAIL" ]]; then
    GLOBAL_EXIT=1
  fi
}

# ════════════════════════════════════════════════════════════
# BANNER
# ════════════════════════════════════════════════════════════
echo -e "\n${BOLD}${GREEN}"
echo "  ███╗   ██╗███████╗██╗  ██╗███████╗"
echo "  ████╗  ██║██╔════╝╚██╗██╔╝██╔════╝"
echo "  ██╔██╗ ██║█████╗   ╚███╔╝ █████╗  "
echo "  ██║╚██╗██║██╔══╝   ██╔██╗ ██╔══╝  "
echo "  ██║ ╚████║███████╗██╔╝ ██╗███████╗"
echo "  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝╚══════╝"
echo -e "  GPU All-Day Test Runner — $(date)${NC}\n"

info "Root:       $ROOT"
info "Python:     $($PYTHON --version)"
info "Log:        $LOG_FILE"
info "Max loops:  $MAX_LOOPS"
info "Platform:   $(uname -s) $(uname -m)"

# ════════════════════════════════════════════════════════════
# DETECCIÓ DE BACKENDS
# ════════════════════════════════════════════════════════════
section "Detecció de backends"

HAS_OLLAMA=false
HAS_MLX=false
HAS_LLAMACPP=false
OLLAMA_MODEL="${NEXE_OLLAMA_MODEL:-phi3:mini}"
MLX_MODEL="${NEXE_MLX_MODEL:-/Users/jgoy/NatSytem/DEV/NAT7-DEV/crom/models/Meta-Llama-3.1-8B-Instruct-4bit}"
LLAMA_MODEL="${NEXE_LLAMA_MODEL:-/Users/jgoy/NatSytem/DEV/NAT7-DEV/crom/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf}"

# Ollama
if curl -sf --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  HAS_OLLAMA=true
  ok "Ollama: actiu"
elif command -v ollama &>/dev/null; then
  info "Iniciant Ollama..."
  ollama serve >/dev/null 2>&1 &
  for i in $(seq 1 20); do
    sleep 0.5
    if curl -sf --max-time 1 http://localhost:11434/api/tags >/dev/null 2>&1; then
      HAS_OLLAMA=true; ok "Ollama: iniciat"; break
    fi
  done
  [[ "$HAS_OLLAMA" == "false" ]] && warn "Ollama no ha arrencat"
else
  warn "Ollama: no instal·lat"
fi

# Comprovar que el model Ollama existeix (NO descarregar)
if [[ "$HAS_OLLAMA" == "true" ]]; then
  if ! ollama list 2>/dev/null | grep -q "^${OLLAMA_MODEL%%:*}"; then
    warn "Model Ollama '$OLLAMA_MODEL' no trobat — skip fase Ollama"
    HAS_OLLAMA=false
  else
    ok "Model Ollama disponible: $OLLAMA_MODEL"
  fi
fi

# MLX (Mac ARM64)
OS="$(uname -s)"; ARCH="$(uname -m)"
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]] && ! $SKIP_MLX; then
  if $PYTHON -c "import mlx_lm" 2>/dev/null; then
    if [[ -d "$MLX_MODEL" || -f "$MLX_MODEL" ]]; then
      HAS_MLX=true
      ok "MLX: disponible → $MLX_MODEL"
    else
      warn "MLX: model no trobat a $MLX_MODEL"
    fi
  else
    warn "MLX: mlx_lm no instal·lat"
  fi
else
  [[ "$SKIP_MLX" == "true" ]] && info "MLX: skip (--skip-mlx)"
fi

# llama.cpp
if ! $SKIP_LLAMACPP; then
  if $PYTHON -c "import llama_cpp" 2>/dev/null; then
    if [[ -f "$LLAMA_MODEL" ]]; then
      HAS_LLAMACPP=true
      ok "llama.cpp: disponible → $LLAMA_MODEL"
    else
      warn "llama.cpp: GGUF no trobat a $LLAMA_MODEL"
    fi
  else
    warn "llama.cpp: no instal·lat"
  fi
else
  info "llama.cpp: skip (--skip-llamacpp)"
fi

echo ""
info "Backends actius → Ollama:$HAS_OLLAMA  MLX:$HAS_MLX  llama.cpp:$HAS_LLAMACPP"

# ════════════════════════════════════════════════════════════
# VARIABLES D'ENTORN BASE
# ════════════════════════════════════════════════════════════
export NEXE_ENV=testing
export NEXE_AUTOSTART_QDRANT=false
export NEXE_AUTOSTART_OLLAMA=false
export NEXE_AUTO_INGEST_KNOWLEDGE=false
export NEXE_PRIMARY_API_KEY="${NEXE_PRIMARY_API_KEY:-nexe-all-day-test-$(date +%s)}"
export NEXE_CSRF_SECRET="${NEXE_CSRF_SECRET:-nexe-csrf-test-$(date +%s)}"
export NEXE_DEV_MODE=true

# ════════════════════════════════════════════════════════════
# ALLIBERAR GPU (Ollama)
# ════════════════════════════════════════════════════════════
free_ollama_gpu() {
  if [[ "$HAS_OLLAMA" == "true" ]]; then
    local loaded
    loaded=$(curl -sf http://localhost:11434/api/ps 2>/dev/null | \
      $PYTHON -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for m in d.get('models', []):
        print(m['name'])
except Exception:
    pass
" 2>/dev/null || true)

    if [[ -n "$loaded" ]]; then
      while IFS= read -r model; do
        curl -sf -X POST http://localhost:11434/api/generate \
          -H "Content-Type: application/json" \
          -d "{\"model\":\"$model\",\"keep_alive\":0}" >/dev/null 2>&1 || true
      done <<< "$loaded"
      sleep 2
      info "GPU alliberada (models descarregats)"
    fi
  fi
}

# ════════════════════════════════════════════════════════════
# FUNCIÓ PRINCIPAL: executar una fase de pytest
# ════════════════════════════════════════════════════════════
run_pytest() {
  local phase_name="$1"; shift
  local start; start=$(date +%s)

  info "Iniciant: $phase_name"
  set +e
  $PYTHON -m pytest "$@" --tb=short -q 2>&1 | tee -a "$LOG_FILE"
  local exit_code=${PIPESTATUS[0]}
  set -e

  local elapsed=$(( $(date +%s) - start ))

  if [[ $exit_code -eq 0 ]]; then
    ok "$phase_name completat en ${elapsed}s ✓"
    record "$phase_name" "OK" "${elapsed}s"
  else
    warn "$phase_name ha fallat (exit $exit_code) en ${elapsed}s"
    record "$phase_name" "FAIL" "${elapsed}s / exit $exit_code"
    notify "Nexe Tests" "$phase_name FALLÓ (exit $exit_code)"
  fi
  return $exit_code
}

# ════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ════════════════════════════════════════════════════════════
LOOP=1
GRAND_START=$(date +%s)

while [[ $LOOP -le $MAX_LOOPS ]]; do
  echo -e "\n${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━  ITERACIÓ $LOOP / $MAX_LOOPS  ━━━━━━━━━━━━━━━━━━${NC}"
  date

  # ────────────────────────────────────────────────────────
  # FASE 0 — Tests unitaris (sense GPU)
  # ────────────────────────────────────────────────────────
  phase "FASE 0 · Tests unitaris (sense GPU)"
  run_pytest "F0-Unit" \
    core memory personality plugins \
    -m "not integration and not e2e and not slow and not gpu" \
    --cov=core --cov=memory --cov=personality --cov=plugins \
    --cov-report=term-missing \
    --cov-report=html:"$COVERAGE_DIR/unit" \
    || true

  if $UNIT_ONLY; then
    info "Mode --unit-only: sortint després de fase 0"
    break
  fi

  # ────────────────────────────────────────────────────────
  # FASE 1 — Integració Ollama
  # ────────────────────────────────────────────────────────
  if [[ "$HAS_OLLAMA" == "true" ]]; then
    phase "FASE 1 · Integració Ollama ($OLLAMA_MODEL)"
    free_ollama_gpu

    export NEXE_MODEL_ENGINE=ollama
    export NEXE_OLLAMA_MODEL="$OLLAMA_MODEL"
    export NEXE_OLLAMA_HOST="${NEXE_OLLAMA_HOST:-http://localhost:11434}"

    run_pytest "F1-Ollama" \
      plugins/web_ui_module/tests/integration \
      core/endpoints/tests \
      -m "integration" \
      --cov=plugins/web_ui_module --cov=core/endpoints \
      --cov-report=html:"$COVERAGE_DIR/ollama" \
      -v || true

    free_ollama_gpu
  else
    warn "FASE 1 — Ollama: skip (backend no disponible)"
    record "F1-Ollama" "SKIP"
  fi

  # ────────────────────────────────────────────────────────
  # FASE 2 — Integració MLX
  # ────────────────────────────────────────────────────────
  if [[ "$HAS_MLX" == "true" ]]; then
    phase "FASE 2 · Integració MLX ($MLX_MODEL)"
    free_ollama_gpu  # alliberar per si MLX necessita memòria

    export NEXE_MODEL_ENGINE=mlx
    export NEXE_MLX_MODEL="$MLX_MODEL"

    run_pytest "F2-MLX" \
      plugins/web_ui_module/tests/integration \
      -m "integration and gpu" \
      --cov=plugins/web_ui_module \
      --cov-report=html:"$COVERAGE_DIR/mlx" \
      -v || true
  else
    warn "FASE 2 — MLX: skip (backend no disponible)"
    record "F2-MLX" "SKIP"
  fi

  # ────────────────────────────────────────────────────────
  # FASE 3 — Integració llama.cpp
  # ────────────────────────────────────────────────────────
  if [[ "$HAS_LLAMACPP" == "true" ]]; then
    phase "FASE 3 · Integració llama.cpp ($LLAMA_MODEL)"

    export NEXE_MODEL_ENGINE=llama_cpp
    export NEXE_LLAMA_MODEL="$LLAMA_MODEL"

    run_pytest "F3-llama.cpp" \
      plugins/web_ui_module/tests/integration \
      -m "integration and gpu" \
      --cov=plugins/web_ui_module \
      --cov-report=html:"$COVERAGE_DIR/llamacpp" \
      -v || true
  else
    warn "FASE 3 — llama.cpp: skip (backend no disponible)"
    record "F3-llama.cpp" "SKIP"
  fi

  # ────────────────────────────────────────────────────────
  # FASE 4 — Suite E2E completa (millor backend disponible)
  # ────────────────────────────────────────────────────────
  phase "FASE 4 · Suite E2E completa"

  # Seleccionar millor backend per E2E
  if [[ "$HAS_MLX" == "true" ]]; then
    export NEXE_MODEL_ENGINE=mlx
    export NEXE_MLX_MODEL="$MLX_MODEL"
    E2E_BACKEND="mlx"
  elif [[ "$HAS_OLLAMA" == "true" ]]; then
    export NEXE_MODEL_ENGINE=ollama
    export NEXE_OLLAMA_MODEL="$OLLAMA_MODEL"
    E2E_BACKEND="ollama"
    free_ollama_gpu
  elif [[ "$HAS_LLAMACPP" == "true" ]]; then
    export NEXE_MODEL_ENGINE=llama_cpp
    export NEXE_LLAMA_MODEL="$LLAMA_MODEL"
    E2E_BACKEND="llama.cpp"
  else
    warn "FASE 4 — E2E: skip (cap backend disponible)"
    record "F4-E2E" "SKIP"
    E2E_BACKEND=""
  fi

  if [[ -n "$E2E_BACKEND" ]]; then
    run_pytest "F4-E2E ($E2E_BACKEND)" \
      core memory personality plugins \
      --cov=core --cov=memory --cov=personality --cov=plugins \
      --cov-report=term-missing \
      --cov-report=html:"$COVERAGE_DIR/e2e" \
      --cov-report=xml:"$ROOT/coverage.xml" \
      || true
  fi

  # ────────────────────────────────────────────────────────
  # PAUSA entre iteracions (evita sobrecàlrrega contínua)
  # ────────────────────────────────────────────────────────
  if [[ $LOOP -lt $MAX_LOOPS ]]; then
    PAUSE=120
    info "Pausa de ${PAUSE}s entre iteracions..."
    sleep "$PAUSE"
  fi

  LOOP=$((LOOP + 1))
done

# ════════════════════════════════════════════════════════════
# FASE 5 — Coverage final + informe
# ════════════════════════════════════════════════════════════
phase "FASE 5 · Coverage final"

# Coverage total (sense GPU — ràpid)
set +e
$PYTHON -m pytest \
  core memory personality plugins \
  -m "not integration and not e2e and not slow and not gpu" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term-missing \
  --cov-report=html:"$COVERAGE_DIR" \
  --cov-report=xml:"$ROOT/coverage.xml" \
  --tb=no -q 2>&1 | tee -a "$LOG_FILE"
FINAL_EXIT=${PIPESTATUS[0]}
set -e

# ════════════════════════════════════════════════════════════
# RESUM FINAL
# ════════════════════════════════════════════════════════════
GRAND_ELAPSED=$(( $(date +%s) - GRAND_START ))
GRAND_MINUTES=$(( GRAND_ELAPSED / 60 ))

{
  echo "═══════════════════════════════════════════════════════"
  echo "  NEXE ALL-DAY TEST RUNNER — RESUM FINAL"
  echo "  $(date)"
  echo "  Temps total: ${GRAND_MINUTES}m (${GRAND_ELAPSED}s)"
  echo "═══════════════════════════════════════════════════════"
  echo ""
  echo "Resultats per fase:"
  for k in "${!PHASE_RESULTS[@]}"; do
    printf "  %-20s  %s\n" "$k" "${PHASE_RESULTS[$k]}"
  done | sort
  echo ""
  TOTAL=$(grep "^TOTAL" "$LOG_FILE" 2>/dev/null | tail -1 | awk '{print $NF}' || echo "?")
  echo "Coverage total:  $TOTAL"
  echo "Coverage HTML:   $COVERAGE_DIR/index.html"
  echo "Log complet:     $LOG_FILE"
  echo ""
  if [[ $GLOBAL_EXIT -eq 0 ]]; then
    echo "  ✓  Tots els tests han passat"
  else
    echo "  ✗  Alguns tests han fallat (vegeu log)"
  fi
  echo "═══════════════════════════════════════════════════════"
} | tee "$SUMMARY_FILE"

# Notificació macOS final
if [[ $GLOBAL_EXIT -eq 0 ]]; then
  notify "Nexe Tests ✓" "Tots els tests OK — Coverage: $TOTAL"
else
  notify "Nexe Tests ✗" "Alguns tests han fallat — vegeu $LOG_FILE"
fi

info "Resum desat a: $SUMMARY_FILE"

exit $GLOBAL_EXIT
