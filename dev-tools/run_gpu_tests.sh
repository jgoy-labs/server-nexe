#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# dev-tools/run_gpu_tests.sh
# GPU Integration Test Runner — Nexe Server
#
# Detecta el backend disponible (MLX / Ollama / llama.cpp),
# allibera la GPU de models carregats i executa el suite complet
# d'integració amb coverage.
#
# Ús:
#   ./dev-tools/run_gpu_tests.sh              # auto-detect backend
#   ./dev-tools/run_gpu_tests.sh --ollama     # forçar Ollama
#   ./dev-tools/run_gpu_tests.sh --mlx        # forçar MLX (Mac ARM64)
#   ./dev-tools/run_gpu_tests.sh --unit-only  # només tests unitaris (sense GPU)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }
section() { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

# ── Flags ───────────────────────────────────────────────────
FORCE_OLLAMA=false
FORCE_MLX=false
UNIT_ONLY=false
for arg in "$@"; do
  case $arg in
    --ollama)    FORCE_OLLAMA=true ;;
    --mlx)       FORCE_MLX=true ;;
    --unit-only) UNIT_ONLY=true ;;
  esac
done

# ── Paths ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COVERAGE_DIR="$ROOT/coverage_html"
LOG_FILE="$SCRIPT_DIR/last_gpu_test_run.log"
cd "$ROOT"

# ── Python ──────────────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
  error "python3 not found"; exit 1
fi

section "Nexe GPU Test Runner"
info "Platform: $(uname -s) $(uname -m)"
info "Python:   $($PYTHON --version)"
info "Root:     $ROOT"

# ════════════════════════════════════════════════════════════
# UNIT-ONLY MODE
# ════════════════════════════════════════════════════════════
if $UNIT_ONLY; then
  section "Unit Tests (sense GPU)"
  $PYTHON -m pytest core memory personality plugins \
    -m "not integration and not e2e and not slow" \
    --cov=core --cov=memory --cov=personality --cov=plugins \
    --cov-report=term-missing \
    --cov-report=html:"$COVERAGE_DIR" \
    --tb=short -q 2>&1 | tee "$LOG_FILE"
  ok "Report: $COVERAGE_DIR/index.html"
  exit 0
fi

# ════════════════════════════════════════════════════════════
# BACKEND DETECTION
# ════════════════════════════════════════════════════════════
section "Detecció de backend"

OS="$(uname -s)"
ARCH="$(uname -m)"
BACKEND=""
TEST_MODEL=""

detect_ollama() {
  if curl -sf --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

start_ollama() {
  if ! command -v ollama &>/dev/null; then
    return 1
  fi
  info "Iniciant Ollama..."
  ollama serve >/dev/null 2>&1 &
  for i in $(seq 1 20); do
    sleep 0.5
    if detect_ollama; then
      ok "Ollama llest (${i}x0.5s)"; return 0
    fi
  done
  warn "Ollama no ha arrencat en 10s"
  return 1
}

# ── MLX (Mac ARM64) ─────────────────────────────────────────
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]] && ( $FORCE_MLX || ! $FORCE_OLLAMA ); then
  if $PYTHON -c "import mlx_lm" 2>/dev/null; then
    BACKEND="mlx"
    TEST_MODEL="${NEXE_MLX_MODEL:-mlx-community/Qwen2.5-0.5B-Instruct-4bit}"
    ok "Backend: MLX (Apple Silicon)"
  else
    warn "mlx_lm no instal·lat — provant Ollama"
  fi
fi

# ── Ollama (Mac + Linux) ─────────────────────────────────────
if [[ -z "$BACKEND" ]]; then
  if detect_ollama; then
    BACKEND="ollama"
    TEST_MODEL="${NEXE_OLLAMA_MODEL:-qwen2:0.5b}"
    ok "Backend: Ollama (ja corrent)"
  elif start_ollama; then
    BACKEND="ollama"
    TEST_MODEL="${NEXE_OLLAMA_MODEL:-qwen2:0.5b}"
    ok "Backend: Ollama (arrencat)"
  fi
fi

# ── llama.cpp (fallback) ─────────────────────────────────────
if [[ -z "$BACKEND" ]]; then
  if $PYTHON -c "import llama_cpp" 2>/dev/null; then
    BACKEND="llama_cpp"
    TEST_MODEL="${NEXE_LLAMA_MODEL:-}"
    ok "Backend: llama.cpp"
    if [[ -z "$TEST_MODEL" ]]; then
      warn "NEXE_LLAMA_MODEL no definit — alguns tests poden fallar"
    fi
  fi
fi

if [[ -z "$BACKEND" ]]; then
  error "Cap backend disponible (MLX / Ollama / llama.cpp)"
  error "Instal·la Ollama: https://ollama.com/download"
  exit 1
fi

info "Backend seleccionat: $BACKEND"
info "Model de test: ${TEST_MODEL:-<per defecte del backend>}"

# ════════════════════════════════════════════════════════════
# ALLIBERAR GPU
# ════════════════════════════════════════════════════════════
section "Alliberant GPU"

if [[ "$BACKEND" == "ollama" ]]; then
  # Obtenir models carregats i descarregar-los
  LOADED=$(curl -sf http://localhost:11434/api/ps 2>/dev/null | \
    $PYTHON -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for m in d.get('models', []):
        print(m['name'])
except Exception:
    pass
" 2>/dev/null || true)

  if [[ -n "$LOADED" ]]; then
    while IFS= read -r model; do
      info "Descarregant: $model"
      curl -sf -X POST http://localhost:11434/api/generate \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"$model\",\"keep_alive\":0}" >/dev/null 2>&1 || true
    done <<< "$LOADED"
    sleep 1
    ok "GPU alliberada"
  else
    ok "Cap model carregat — GPU ja lliure"
  fi

  # Assegurar que el model de test és disponible
  section "Model de test"
  if ! ollama list 2>/dev/null | grep -q "^${TEST_MODEL%%:*}"; then
    info "Descarregant $TEST_MODEL (~350MB per qwen2:0.5b)..."
    ollama pull "$TEST_MODEL"
    ok "Model descarregat: $TEST_MODEL"
  else
    ok "Model disponible: $TEST_MODEL"
  fi

elif [[ "$BACKEND" == "mlx" ]]; then
  ok "MLX: carrega i descarrega per petició — GPU sempre lliure entre tests"
fi

# ════════════════════════════════════════════════════════════
# VARIABLES D'ENTORN
# ════════════════════════════════════════════════════════════
section "Configuració"

export NEXE_ENV=testing
export NEXE_MODEL_ENGINE="$BACKEND"
export NEXE_PRIMARY_API_KEY="${NEXE_PRIMARY_API_KEY:-nexe-gpu-test-$(date +%s)}"
export NEXE_CSRF_SECRET="${NEXE_CSRF_SECRET:-nexe-csrf-test-$(date +%s)}"
export NEXE_AUTOSTART_QDRANT=false
export NEXE_AUTOSTART_OLLAMA=false
export NEXE_AUTO_INGEST_KNOWLEDGE=false

case "$BACKEND" in
  ollama)
    export NEXE_OLLAMA_MODEL="$TEST_MODEL"
    export NEXE_OLLAMA_HOST="${NEXE_OLLAMA_HOST:-http://localhost:11434}"
    export NEXE_AUTOSTART_OLLAMA=false  # ja corrent
    ;;
  mlx)
    export NEXE_MLX_MODEL="$TEST_MODEL"
    ;;
  llama_cpp)
    [[ -n "$TEST_MODEL" ]] && export NEXE_LLAMA_MODEL="$TEST_MODEL"
    ;;
esac

info "NEXE_MODEL_ENGINE = $BACKEND"
info "NEXE_OLLAMA_MODEL = ${NEXE_OLLAMA_MODEL:-N/A}"
info "NEXE_MLX_MODEL    = ${NEXE_MLX_MODEL:-N/A}"

# ════════════════════════════════════════════════════════════
# EXECUCIÓ DE TESTS
# ════════════════════════════════════════════════════════════
section "Executant tests"

START_TIME=$(date +%s)

$PYTHON -m pytest \
  core memory personality plugins \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term-missing \
  --cov-report=html:"$COVERAGE_DIR" \
  --cov-report=xml:"$ROOT/coverage.xml" \
  --tb=short -q \
  2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

# ════════════════════════════════════════════════════════════
# RESUM
# ════════════════════════════════════════════════════════════
section "Resum"
info "Temps total: ${ELAPSED}s"
info "Log: $LOG_FILE"
info "Coverage HTML: $COVERAGE_DIR/index.html"

# Extreure coverage total del log
TOTAL=$(grep "^TOTAL" "$LOG_FILE" | awk '{print $NF}' || echo "?")
if [[ -n "$TOTAL" ]]; then
  echo -e "\n${BOLD}Coverage total: ${GREEN}${TOTAL}${NC}"
fi

if [[ $EXIT_CODE -eq 0 ]]; then
  ok "Tots els tests han passat ✓"
else
  warn "Alguns tests han fallat (exit code: $EXIT_CODE)"
fi

exit $EXIT_CODE
