#!/bin/bash
# ────────────────────────────────────────────────────────────────────────
# build-sidecar.sh
# POC: Build a self-contained Python sidecar using python-build-standalone
# (via uv) without requiring system Python or a pre-existing venv.
#
# Approach: PBS + uv (evolution of server-nexe's build-python-bundle.sh)
# ADR-0016 documents the decision.
# ────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Linux portability (FL-L1, 2026-05-21):
# Detecta OS/ARCH per resoldre el triplet PBS correcte. uv venv descarrega PBS
# automàticament segons host, però aquesta variable serveix per logs i per a
# futurs steps que necessitin saber el target (cross-build, etc.). No modifica
# Step 5.5 (PBS copy) — `realpath venv/bin/python` ja resol el directori real
# que uv ha baixat, independentment de la plataforma.
OS=$(uname -s)
ARCH=$(uname -m)
case "$OS-$ARCH" in
    Darwin-arm64)   PBS_TRIPLE="aarch64-apple-darwin" ;;
    Darwin-x86_64)  PBS_TRIPLE="x86_64-apple-darwin" ;;
    Linux-aarch64)  PBS_TRIPLE="aarch64-unknown-linux-gnu" ;;
    Linux-x86_64)   PBS_TRIPLE="x86_64-unknown-linux-gnu" ;;
    *) echo "Unsupported platform: $OS-$ARCH" >&2; exit 1 ;;
esac
echo "Detected: $OS/$ARCH → PBS_TRIPLE=$PBS_TRIPLE"

# ── Config ────────────────────────────────────────────────────────────
PY_VERSION="3.12"
SIDECAR_DIR="${SIDECAR_DIR:-$PROJECT_ROOT/target/sidecar}"
REQUIREMENTS="${REQUIREMENTS:-$SCRIPT_DIR/poc-sidecar/requirements.txt}"
APP_MODULE="${APP_MODULE:-poc-sidecar/app.py}"
# APP_SOURCE_DIR: if set, copies entire directory to app/ (multi-file apps like
# server-nexe). Overrides APP_MODULE. Example:
#   APP_SOURCE_DIR=/path/to/server-nexe REQUIREMENTS=/path/to/requirements.txt \
#   scripts/build-sidecar.sh
APP_SOURCE_DIR="${APP_SOURCE_DIR:-}"

# ── Pre-checks ────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

echo "==> build-sidecar.sh — PBS + uv packaging POC"
echo "    Python target: $PY_VERSION"
echo "    Output dir:    $SIDECAR_DIR"
echo "    Architecture:  $(uname -m)"
echo ""

# ── Step 1: Clean previous build ─────────────────────────────────────
if [ -d "$SIDECAR_DIR" ]; then
    echo "==> Cleaning previous build..."
    rm -rf "$SIDECAR_DIR"
fi
mkdir -p "$SIDECAR_DIR"

# ── Step 2: Create venv with PBS Python via uv ───────────────────────
# --managed-python: força uv a usar PBS portable (managed-installations),
# evitant que reutilitzi un Python system. A Mac uv ja baixa PBS perquè 3.12
# no és system. A Linux (Ubuntu 24.04 ARM64) `/usr/bin/python3.12` existeix
# i uv el reutilitzaria → Step 5.5 rsync tot /usr → peta permisos sssd/netplan
# i el bundle no és portable. Validat empíric Holodeck 2026-05-22 vespre.
echo "==> Creating venv with Python $PY_VERSION (PBS via uv, managed)..."
START_VENV=$(date +%s)
uv venv "$SIDECAR_DIR/venv" --python "$PY_VERSION" --managed-python --quiet
END_VENV=$(date +%s)
echo "    Venv created in $((END_VENV - START_VENV))s"

# Verify the Python is from PBS (not system)
VENV_PY="$SIDECAR_DIR/venv/bin/python3"
PY_PREFIX=$("$VENV_PY" -c "import sys; print(sys.base_prefix)")
echo "    Python prefix: $PY_PREFIX"
echo "    Python version: $("$VENV_PY" --version)"

# ── Step 3: Install dependencies ─────────────────────────────────────
echo "==> Installing dependencies..."
START_DEPS=$(date +%s)
if [ -f "$REQUIREMENTS" ]; then
    uv pip install --python "$VENV_PY" -r "$REQUIREMENTS" --quiet

    # F5.5 — Platform-specific deps. Si APP_SOURCE_DIR està set i conté un
    # requirements-macos.txt (server-nexe pattern: MLX-lm, MLX-vlm, etc.),
    # l'instal·lem també. Sense això, els inference engines MLX + llama_cpp
    # no estan disponibles al sidecar productiu i les UI dropdowns només
    # mostren Ollama. Aplicable només a macOS arm64 (host detection).
    if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] && [ -n "${APP_SOURCE_DIR:-}" ]; then
        REQ_MACOS="$APP_SOURCE_DIR/requirements-macos.txt"
        if [ -f "$REQ_MACOS" ]; then
            echo "    Installing macOS-specific inference engine deps (MLX, etc.)..."
            uv pip install --python "$VENV_PY" -r "$REQ_MACOS" --quiet
        fi
        # llama-cpp-python ships its own arm64 wheel with Metal — install it
        # explicitly here (no platform marker in requirements.txt because Linux
        # builds use a different installation path).
        echo "    Installing llama-cpp-python (arm64 macOS wheel with Metal)..."
        uv pip install --python "$VENV_PY" "llama-cpp-python==0.3.19" --quiet
        # torch + torchvision — required at runtime by Qwen3.5 VL family and
        # other multimodal MLX models (Qwen3_5ForConditionalGeneration needs
        # torchvision for image preprocessing even in text-only fallback path).
        # macOS arm64 wheels do NOT include CUDA/cuDNN libs (~92MB net).
        echo "    Installing torch + torchvision (VLM support)..."
        uv pip install --python "$VENV_PY" "torch==2.11.0" "torchvision==0.26.0" --quiet
    elif [ "$(uname -s)" = "Linux" ] && [ -n "${APP_SOURCE_DIR:-}" ]; then
        # D2 1r release Linux: Ollama-only. llama-cpp-python al release 1.1.
        # MLX no aplica (Apple-only). Si APP_SOURCE_DIR exposa requirements-linux.txt
        # (variant futur de server-nexe), instal·la els extres Linux-only allà;
        # altrament, requirements.txt base ja inclou ollama_module + fastembed.
        REQ_LINUX="$APP_SOURCE_DIR/requirements-linux.txt"
        if [ -f "$REQ_LINUX" ]; then
            echo "    Installing Linux-specific inference engine deps (Ollama-only D2)..."
            uv pip install --python "$VENV_PY" -r "$REQ_LINUX" --quiet
        else
            echo "    No requirements-linux.txt found at $REQ_LINUX — skipping Linux extras (Ollama-only via base requirements)"
        fi
        # TODO release 1.1 Linux: avaluar llama-cpp-python wheel Linux (CPU + opcional CUDA/Vulkan).
        # No s'instal·la al 1r release per mantenir bundle petit + decisió arquitectural Ollama-only.
    fi
else
    # Minimal deps for POC
    uv pip install --python "$VENV_PY" fastapi "uvicorn[standard]" --quiet
fi
END_DEPS=$(date +%s)
echo "    Dependencies installed in $((END_DEPS - START_DEPS))s"

# ── Step 3b: Remove hf_xet (F5.6 Bloc 8) ──────────────────────────────
# Belt-and-braces defence against the silent stalled-download bug. The Rust
# launcher already sets HF_HUB_DISABLE_XET=1 before spawning Python, so
# huggingface_hub never enters the xet code path; uninstalling hf_xet at
# build time ensures that even if a future regression drops the env var,
# `is_xet_available()` returns False because the package literally isn't
# importable. hf_xet is an optional dep of huggingface_hub (nothing else in
# the sidecar — fastembed, MLX, llama.cpp, Ollama — relies on it).
if uv pip list --python "$VENV_PY" 2>/dev/null | grep -qi "^hf-xet\|^hf_xet "; then
    echo "==> Removing hf_xet from bundle (F5.6 Bloc 8 belt-and-braces)..."
    uv pip uninstall --python "$VENV_PY" hf_xet --quiet || true
fi

# ── Step 4: Copy application code ────────────────────────────────────
echo "==> Copying application code..."
mkdir -p "$SIDECAR_DIR/app"
if [ -n "$APP_SOURCE_DIR" ]; then
    # Multi-file mode (server-nexe): copy entire source directory.
    # BUG-NF-29 (F1.3): rsync amb excludes per evitar privacy leak.
    #
    # F5.6 BUG-NEW-3 root cause — la inestabilitat recurrent entre F5.1 i F5.6
    # smoke ve de DEV contamination dins el bundle: .test_venv/ Python venv
    # de tests, node_modules/, scripts/, docs/, knowledge/, README*.md i
    # pytest configs s'inclouien al sidecar/app/. El .test_venv en particular
    # exposava .pth files al sys.path que feien que el module_manager
    # descobrís els plugins a /Users/.../nat/dev/server-nexe/plugins/ enlloc
    # del sidecar extret. Cada fix de NEW-* destapava una capa nova.
    #
    # Leading slash a /pattern = anchored a $APP_SOURCE_DIR; sense slash
    # match a qualsevol profunditat (per això sense slash exclou también
    # memory/memory/storage/, que és un mòdul Python real i NO ho volem).
    rsync -a \
        --exclude='/storage' --exclude='.env' --exclude='/.git' \
        --exclude='__pycache__' --exclude='/venv' --exclude='/diari' \
        --exclude='/tests' --exclude='/InstallNexe.app' --exclude='/Nexe.app' \
        --exclude='/.muthur' --exclude='/dev-tools' \
        --exclude='/.test_venv' --exclude='/.venv' \
        --exclude='/node_modules' --exclude='/.pytest_cache' --exclude='/.mypy_cache' \
        --exclude='/.coverage' --exclude='.DS_Store' --exclude='._*' \
        --exclude='/docs' --exclude='/specialists' \
        --exclude='/scripts' --exclude='/SetupNexe.command' --exclude='/setup.sh' \
        --exclude='/eslint.config.js' --exclude='/package.json' --exclude='/package-lock.json' \
        --exclude='/pytest.ini' --exclude='/pytest-full.ini' --exclude='/conftest.py' \
        --exclude='*.egg-info' \
        --exclude='/README*.md' --exclude='/CHANGELOG.md' --exclude='/LICENSE' \
        --exclude='/SECURITY.md' --exclude='/THREAT_MODEL.md' \
        --exclude='/CODE_OF_CONDUCT.md' --exclude='/CONTRIBUTING.md' \
        --exclude='/COMMANDS.md' --exclude='/index_server-nexe.md' \
        --exclude='.module_cache.json' \
        --exclude='/installer/swift-wizard' \
        --exclude='/installer/NexeTray.app' \
        --exclude='/installer/tray_icons' \
        --exclude='/installer/build_dmg.sh' \
        --exclude='/installer/build-embedding-bundle.sh' \
        --exclude='/installer/build-ollama-bundle.sh' \
        --exclude='/installer/build-python-bundle.sh' \
        --exclude='/installer/build-wheels-bundle.sh' \
        --exclude='/installer/sign-wheels-bundle.sh' \
        --exclude='/installer/install.py' \
        --exclude='/installer/install_headless.py' \
        --exclude='/installer/tray.py' \
        --exclude='/installer/tray_monitor.py' \
        --exclude='/installer/tray_translations.py' \
        --exclude='/installer/tray_uninstaller.py' \
        --exclude='/installer/nexe_launcher.swift' \
        --exclude='/installer/make_dmg_ds_store.py' \
        --exclude='/installer/dmg_background.png' \
        --exclude='/installer/logo.png' \
        --exclude='/installer/ollama-checksums.txt' \
        --exclude='/installer/wheels-checksums.txt' \
        "$APP_SOURCE_DIR/." "$SIDECAR_DIR/app/"
    # F5.6 Bloc 0: incloem els mòduls Python d'installer/ que el sidecar
    # importa runtime — installer_ollama_install (Bloc 3: ensure_ollama_installed),
    # download_verify (Bloc 6: verify_download_integrity), installer_catalog_data
    # (MODEL_WEIGHT_SHA256), installer_hardware, installer_setup_env (Bloc 4 preseed),
    # installer_setup_models (Bloc 1 patró download).
    #
    # IMPORTANT: el graf de deps obliga a mantenir TOTA la família installer_*.py
    # perquè ollama_install i tota la resta importen .installer_display + .installer_i18n,
    # i installer_i18n importa .installer_translations*. Excloure qualsevol trenca
    # els imports en cadena. Pesen pocs KB (terminal print + strings), neutral.
    #
    # Excloem swift-wizard (278 MB, notarytool log 4d42c92d), NexeTray.app legacy,
    # tray_*.py i wheels-checksums.txt (legacy CLI), build_*.sh scripts, imatges DMG
    # i CLI standalone (install.py + install_headless.py). Tot té equivalent a
    # nexe-app/Tauri (wizard HTML + tray nadiu + scripts propis).
    echo "    Source dir: $APP_SOURCE_DIR"
else
    # Single-file mode (poc-sidecar default): copy one .py file as app.py.
    cp "$SCRIPT_DIR/$APP_MODULE" "$SIDECAR_DIR/app/app.py"
fi

# ── Step 4.5: Pre-seed fastembed embedder cache (F5.6 Bloc 4 — F04+Bug A) ──
# Sense aquest preseed, el primer chat post-wizard fallava silenciosament
# perquè fastembed intentava descarregar el model paraphrase-multilingual-
# mpnet-base-v2 al primer TextEmbedding() call. Amb HF_HUB_OFFLINE=1 forçat
# pel lifespan, la descàrrega petava (Bug A del log F5.3.1 G10).
#
# Estratègia:
# - Pre-seed durant build a app/.fastembed_cache/ (staging dins bundle).
# - Al primer launch del sidecar (Step 5.9 del launcher), copy de bundle a
#   ~/.cache/fastembed/ (writable) — vegi's `_seed_fastembed_cache()` original
#   a installer/installer_setup_env.py:207 per la lògica equivalent.
# - NO setem FASTEMBED_CACHE_DIR al launcher: fastembed escriu
#   `files_metadata.json` al primer load → causaria PermissionError en read-only.
#
# Graceful: si el host build no té internet, warning i continuem. La descàrrega
# es farà online al primer chat (com abans, però amb logs clars).
if [ -n "${APP_SOURCE_DIR:-}" ]; then
    echo "==> Pre-seeding fastembed embedder cache..."
    START_FE=$(date +%s)
    FASTEMBED_STAGING="$SIDECAR_DIR/app/.fastembed_cache"
    mkdir -p "$FASTEMBED_STAGING"
    # IMPORTANT 1: fastembed library NO respecta FASTEMBED_CACHE_DIR env var
    # (verificat empíricament 2026-05-20). Cal passar cache_dir explícit al
    # constructor TextEmbedding(model, cache_dir=...).
    # IMPORTANT 2: Step 4.5 corre ABANS del PBS copy (Step 5.5), per tant
    # python-runtime/ encara NO existeix al bundle. NO settem PYTHONHOME —
    # deixem que el venv usi el seu PBS natural (uv default).
    PYTHONNOUSERSITE=1 \
      FASTEMBED_STAGING_PATH="$FASTEMBED_STAGING" \
      "$VENV_PY" -c "import os; from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-mpnet-base-v2', cache_dir=os.environ['FASTEMBED_STAGING_PATH'])" \
      || echo "    WARN: fastembed preseed failed (offline build?) — model will be downloaded at first chat"
    END_FE=$(date +%s)
    if [ -d "$FASTEMBED_STAGING" ] && [ -n "$(ls -A "$FASTEMBED_STAGING" 2>/dev/null)" ]; then
        FE_SIZE=$(du -sh "$FASTEMBED_STAGING" | cut -f1)
        echo "    Pre-seed completed in $((END_FE - START_FE))s ($FE_SIZE)"
    else
        echo "    Pre-seed dir empty (offline build) — bundle ships without embedder cache"
    fi
fi

# ── Step 5: Create launcher script ───────────────────────────────────
cat > "$SIDECAR_DIR/nexe-sidecar" << 'LAUNCHER'
#!/bin/bash
# Launcher for nexe-sidecar — self-contained Python server
# This script is what Tauri's externalBin / Command would invoke.
set -euo pipefail

SIDECAR_DIR="${NEXE_SIDECAR_DIR:-$(cd "$(dirname "$0")" && pwd)}"
VENV_PY="$SIDECAR_DIR/venv/bin/python3"

# Ensure no system Python contamination
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
# F5.2.1: PBS portable safety net. Si pyvenv.cfg `home=relatiu` falla per algun
# motiu (Python rebutja el path, build futur amb PBS estructura diferent),
# PYTHONHOME explicit garanteix que sys.base_prefix apunti al PBS dins el bundle.
export PYTHONHOME="$SIDECAR_DIR/python-runtime"
# Unbuffered I/O: emit logs in real time (no stdout/stderr buffering).
# Required so Rust spawner can capture sidecar logs as they happen,
# especially during early-fail scenarios before /health/ready binds.
export PYTHONUNBUFFERED=1

# F5.6 Bloc 4 (F04+Bug A): seed fastembed cache to ~/.cache/fastembed/ at
# first launch. El bundle porta el cache pre-seedat a app/.fastembed_cache/
# (read-only dins l'app signada). fastembed escriu files_metadata.json al
# primer load → si el cache fos read-only, PermissionError. Solucio:
# copiar al user cache (writable) al primer launch nomes. Reprodueix la
# logica de installer/installer_setup_env.py:_seed_fastembed_cache().
# Opció B.
EMBEDDER_DIR="$HOME/.cache/fastembed/models--sentence-transformers--paraphrase-multilingual-mpnet-base-v2"
if [ -d "$SIDECAR_DIR/app/.fastembed_cache" ] && [ ! -d "$EMBEDDER_DIR" ]; then
    echo "First launch: seeding fastembed cache to ~/.cache/fastembed/..." >&2
    mkdir -p "$HOME/.cache/fastembed"
    cp -R "$SIDECAR_DIR/app/.fastembed_cache/." "$HOME/.cache/fastembed/" 2>/dev/null || \
        echo "WARN: fastembed seed failed (will download at first chat)" >&2
fi

# Read auth token from stdin (NOT env var) so it never appears in
# /proc/<pid>/environ nor in `ps eww` output. The Rust spawner (lib.rs setup)
# writes "<token>\n" to stdin then closes the pipe.
#
# We read the first line, store it in a local shell var, and pass it to the
# Python child via a non-deterministic env var name + scrub the obvious
# `NEXE_AUTH_TOKEN` slot if anything inherited it. The Python sidecar reads
# `NEXE_TOKEN_INTERNAL`. (Yes this still surfaces in environ, but with a
# different name and we've removed the well-known leak vector.)
#
# Future hardening: pass via dup'd FD (read directly into Python without ever
# touching env). For now stdin-then-export is the pragmatic mid.
read -r -t 5 NEXE_TOKEN_VALUE || { echo "ERROR: stdin token read timeout" >&2; exit 1; }
unset NEXE_AUTH_TOKEN  # belt + suspenders if Rust spawner ever sets both
export NEXE_TOKEN_INTERNAL="$NEXE_TOKEN_VALUE"
unset NEXE_TOKEN_VALUE

HOST="${NEXE_HOST:-127.0.0.1}"
# Default port unified with lib.rs SIDECAR_PORT (single source of truth);
# Tauri spawn passes NEXE_PORT=8765 explicitly.
PORT="${NEXE_PORT:-8765}"

exec "$VENV_PY" -m uvicorn core.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 --lifespan on \
    --no-access-log \
    --app-dir "$SIDECAR_DIR/app"
LAUNCHER
chmod +x "$SIDECAR_DIR/nexe-sidecar"

# ── Step 5.5: Copy Python Build Standalone into bundle (F5.2.1) ──────
# Bug arrel descobert F5.2.1 2026-05-18: `uv venv` crea symlinks absoluts al
# PBS de l'usuari de build (~/.local/share/uv/python/cpython-3.12.11-.../bin/
# python3.12). Al Mac destinatari (usuari diferent), el symlink queda trencat i
# el launcher line 39 falla amb "No such file or directory". Solucio: copiar
# el PBS sencer dins el bundle, fer els symlinks relatius, fer pyvenv.cfg
# relocatable. Validat amb consultoria externa raonament agentic 2026-05-18.
echo "==> Copying PBS runtime into bundle (portable)..."
# Resol el directori PBS real des del symlink absolut creat per uv venv:
# venv/bin/python -> .../bin/python3.12, dos dirname per arribar al PBS root.
PBS_REAL=$(realpath "$SIDECAR_DIR/venv/bin/python")
PBS_DIR=$(dirname "$(dirname "$PBS_REAL")")
echo "    PBS source: $PBS_DIR"
mkdir -p "$SIDECAR_DIR/python-runtime"
# rsync -a preserva symlinks intra-PBS i permisos. Exclou include/ (~8 MB
# headers per compilacio, no calen runtime) i share/ (~1 MB doc).
rsync -a --delete \
    --exclude='include/' \
    --exclude='share/' \
    "$PBS_DIR/" "$SIDECAR_DIR/python-runtime/"
PBS_SIZE=$(du -sh "$SIDECAR_DIR/python-runtime" | cut -f1)
echo "    PBS copied: $PBS_SIZE"

# ── Step 5.6: Rewrite venv symlinks relatively (F5.2.1) ──────────────
# Els 3 symlinks del venv/bin/ (python, python3, python3.12) apunten ara al
# PBS absolut del build machine. Cal substituir-los per symlinks RELATIUS al
# python-runtime/ que acabem de copiar. Aixi, quan Tauri extreu el tarball a
# ~/Library/Application Support/com.nexe.app/sidecar/, els symlinks resolen
# correctament dins el directori extret.
echo "==> Rewriting venv symlinks to relative PBS paths..."
( cd "$SIDECAR_DIR/venv/bin" && \
    rm -f python python3 python3.12 && \
    ln -sf ../../python-runtime/bin/python3.12 python3.12 && \
    ln -sf ../../python-runtime/bin/python3.12 python3 && \
    ln -sf python3 python )
echo "    Symlinks: python, python3, python3.12 -> ../../python-runtime/bin/python3.12"

# ── Step 5.7: Rewrite pyvenv.cfg relocatable (F5.2.1) ────────────────
# Substitueix `home = /Users/jgoy/.local/share/uv/python/.../bin` per un path
# relatiu (../../python-runtime/bin) i activa `relocatable = true`. Python 3.12
# resol `home` relatiu respecte al directori del pyvenv.cfg (venv/), via site.py.
# `relocatable = true` forca recalcular sys.prefix des de la ubicacio real del
# venv (no des de `home` absolut hardcoded), cobrint el cas que `home` falli a
# resoldre. Combinat amb PYTHONHOME al launcher (Step 5), es la configuracio
# mes robusta (font: consultoria externa + CPython Lib/site.py).
echo "==> Rewriting pyvenv.cfg for relocatable PBS..."
UV_VERSION_STR=$(uv --version 2>/dev/null | awk '{print $2}')
# home= és RELATIU al directori del pyvenv.cfg (CPython Lib/site.py resol amb
# os.path.join(os.path.dirname(cfg_path), home)). pyvenv.cfg viu a
# target/sidecar/venv/pyvenv.cfg → directori del cfg = venv/ → `..` és
# target/sidecar/ → `../python-runtime/bin` apunta al PBS germà. NOMÉS un
# nivell `..` (no dos), perquè el cfg viu a venv/, no a venv/bin/.
cat > "$SIDECAR_DIR/venv/pyvenv.cfg" <<PYVENV
home = ../python-runtime/bin
implementation = CPython
uv = ${UV_VERSION_STR}
version_info = 3.12.11
include-system-site-packages = false
relocatable = true
PYVENV
echo "    pyvenv.cfg rewritten with relative home + relocatable"

# ── Step 5.8: Portability verification (Gates G1-G6) ─────────────────
echo "==> Portability verification..."

# G1: no absolute symlinks anywhere in the bundle
ABS_SYMLINKS=$(find "$SIDECAR_DIR" -type l -lname '/*' 2>/dev/null | wc -l | tr -d ' ')
if [ "$ABS_SYMLINKS" -ne 0 ]; then
    echo "    G1 FAIL: $ABS_SYMLINKS absolute symlinks found:"
    find "$SIDECAR_DIR" -type l -lname '/*' 2>/dev/null
    exit 1
fi
echo "    G1 PASS: no absolute symlinks"

# G2: venv/bin/python3 resolves to a real Mach-O (macOS) / ELF (Linux).
# Cross-platform gate via $OS detected at top. NOTE: $OS is HOST OS; for future
# cross-build (Mac → Linux target), introduce $TARGET_OS explicitly.
VENV_PY_LINK="$SIDECAR_DIR/venv/bin/python3"
if ! command -v file &>/dev/null; then
    echo "    G2 FAIL: 'file' command not found (install: apt-get install -y file / brew install file)"
    exit 1
fi
PY_TYPE=$(file -L "$VENV_PY_LINK" 2>/dev/null)
case "$OS" in
    Darwin)
        if ! echo "$PY_TYPE" | grep -q "Mach-O 64-bit executable arm64"; then
            echo "    G2 FAIL: venv/bin/python3 is not a Mach-O arm64 executable"
            echo "    file: $PY_TYPE"
            exit 1
        fi
        echo "    G2 PASS: venv/bin/python3 resolves to Mach-O arm64"
        ;;
    Linux)
        if ! echo "$PY_TYPE" | grep -qE "ELF 64-bit LSB.*executable.*(ARM aarch64|x86-64)"; then
            echo "    G2 FAIL: venv/bin/python3 is not an ELF 64-bit aarch64/x86_64 executable"
            echo "    file: $PY_TYPE"
            exit 1
        fi
        echo "    G2 PASS: venv/bin/python3 resolves to ELF 64-bit ($ARCH)"
        ;;
esac

# G3: sys.executable resolves to a path inside the bundle.
# Simula el launcher real: PYTHONHOME apunta al PBS dins el bundle. Sense
# PYTHONHOME, el PBS de uv té un prefix hardcoded (/install) que falla. El
# launcher SEMPRE el defineix (Step 5), per això el test també.
SYS_EXEC=$(PYTHONHOME="$SIDECAR_DIR/python-runtime" "$VENV_PY_LINK" -c "import sys; print(sys.executable)")
case "$SYS_EXEC" in
    "$SIDECAR_DIR"/*)
        echo "    G3 PASS: sys.executable inside bundle: $SYS_EXEC"
        ;;
    *)
        echo "    G3 FAIL: sys.executable points outside bundle: $SYS_EXEC"
        exit 1
        ;;
esac

# G5: portability test - copy sidecar to /tmp/ and verify python3 still works.
# Tornem a definir PYTHONHOME apuntat al python-runtime/ del CÒPIA (simulant
# el que faria el launcher al Mac destinatari, on PYTHONHOME es deriva
# dinàmicament de $SIDECAR_DIR/python-runtime).
# Linux: minimal copy (~50 MB) per a builders space-constrained (Holodeck UTM
# pot tenir <500 MB lliures abans del resize). Mac: full copy històric (~400 MB).
PORT_TEST_DIR="/tmp/nexe-sidecar-portable-test-$$"
echo "==> G5 portability test (copy to $PORT_TEST_DIR)..."
rm -rf "$PORT_TEST_DIR"
mkdir -p "$PORT_TEST_DIR"
case "$OS" in
    Darwin)
        cp -R "$SIDECAR_DIR/." "$PORT_TEST_DIR/"
        ;;
    Linux)
        # Suficient per validar que el Python copiat arrenca + stdlib C ext OK.
        mkdir -p "$PORT_TEST_DIR/python-runtime" "$PORT_TEST_DIR/venv"
        cp -R "$SIDECAR_DIR/python-runtime/." "$PORT_TEST_DIR/python-runtime/"
        cp -R "$SIDECAR_DIR/venv/bin" "$PORT_TEST_DIR/venv/"
        ;;
esac
if ! PYTHONHOME="$PORT_TEST_DIR/python-runtime" "$PORT_TEST_DIR/venv/bin/python3" --version >/dev/null 2>&1; then
    echo "    G5 FAIL: python3 from copied bundle does not run"
    PYTHONHOME="$PORT_TEST_DIR/python-runtime" "$PORT_TEST_DIR/venv/bin/python3" --version 2>&1 || true
    rm -rf "$PORT_TEST_DIR"
    exit 1
fi
if ! PYTHONHOME="$PORT_TEST_DIR/python-runtime" "$PORT_TEST_DIR/venv/bin/python3" -c "import ssl, socket, hashlib" >/dev/null 2>&1; then
    echo "    G5 FAIL: stdlib C extensions not importable from copied bundle"
    PYTHONHOME="$PORT_TEST_DIR/python-runtime" "$PORT_TEST_DIR/venv/bin/python3" -c "import ssl, socket, hashlib" 2>&1 || true
    rm -rf "$PORT_TEST_DIR"
    exit 1
fi
rm -rf "$PORT_TEST_DIR"
echo "    G5 PASS: copied bundle python3 works + stdlib C extensions OK"

# G6: no builder home references in TEXT content of the bundle.
# Tolera matches a egg-info/RECORD (metadades inofensives, no afecten runtime).
# Linux: $HOME cobreix /root, LDAP (/export/home/...), NixOS, Docker (/app),
# WSL i altres homes personalitzats. Mac: /Users/$BUILDER preserva el comportament
# històric (a macOS $HOME = /Users/$USER sempre, semànticament equivalent).
BUILDER=$(whoami)
case "$OS" in
    Darwin) BUILDER_HOME_PREFIX="/Users/$BUILDER" ;;
    Linux)  BUILDER_HOME_PREFIX="$HOME" ;;
esac
GREP_HITS=$(grep -rI "$BUILDER_HOME_PREFIX" "$SIDECAR_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$GREP_HITS" -ne 0 ]; then
    echo "    G6 WARN: $GREP_HITS references to $BUILDER_HOME_PREFIX found (first 5):"
    # `|| true` neutralitza exit 141 (SIGPIPE) que es dispara quan head -5 tanca
    # la pipe abans que grep acabi. set -e pipefail (línia 10) no perdona 141,
    # aborta el script. A Mac amb pocs hits no es notava; a Linux amb 26+
    # refs (activate scripts venv) el SIGPIPE és garantit.
    grep -rI "$BUILDER_HOME_PREFIX" "$SIDECAR_DIR" 2>/dev/null | head -5 || true
else
    echo "    G6 PASS: no $BUILDER_HOME_PREFIX references in text files"
fi

# ── Step 6: Trim unnecessary files ───────────────────────────────────
echo "==> Trimming unnecessary files..."
TRIMMED=0
# Remove __pycache__
FOUND=$(find "$SIDECAR_DIR/venv" -type d -name "__pycache__" | wc -l | tr -d ' ')
find "$SIDECAR_DIR/venv" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
TRIMMED=$((TRIMMED + FOUND))

# Remove pip/setuptools cache
rm -rf "$SIDECAR_DIR/venv/lib/python${PY_VERSION}/site-packages/pip" 2>/dev/null
rm -rf "$SIDECAR_DIR/venv/lib/python${PY_VERSION}/site-packages/setuptools" 2>/dev/null

# Remove test directories inside site-packages
find "$SIDECAR_DIR/venv/lib" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$SIDECAR_DIR/venv/lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true

echo "    Trimmed $TRIMMED __pycache__ dirs + pip/setuptools/test dirs"

# ── Step 6.5: Sign Mach-O binaries in venv (F5.2b) ───────────────────
# Per a notarytzació Apple cal que TOTS els .so/.dylib del venv portin
# Developer ID + secure timestamp + hardened runtime. Si APPLE_SIGNING_IDENTITY
# està set, signa ~330 binaris (~1-3 min). Sense identity, salta amb avís
# (dev build local sense cert). El smoke test posterior valida que els
# binaris signats encara importen correctament.
if [ "$OS" = "Darwin" ] && [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
    bash "$SCRIPT_DIR/sign-sidecar-binaries.sh" "$SIDECAR_DIR"
elif [ "$OS" = "Darwin" ]; then
    echo "==> Sign step skipped (APPLE_SIGNING_IDENTITY unset — dev build)"
else
    echo "==> Sign step skipped (Linux — codesign no aplica)"
fi

# ── Step 6b: Copy launcher to src-tauri/binaries/ for Tauri externalBin ─
# Tauri 2 externalBin expects: src-tauri/binaries/<name>-<host-triple>
echo "==> Copying launcher to src-tauri/binaries/ for Tauri externalBin..."
HOST_TRIPLE="$(rustc -vV 2>/dev/null | grep '^host:' | awk '{print $2}')"
if [ -z "$HOST_TRIPLE" ]; then
    echo "    WARNING: rustc not found, skipping externalBin copy step"
else
    BINARIES_DIR="$PROJECT_ROOT/src-tauri/binaries"
    mkdir -p "$BINARIES_DIR"
    cp "$SIDECAR_DIR/nexe-sidecar" "$BINARIES_DIR/nexe-sidecar-$HOST_TRIPLE"
    chmod +x "$BINARIES_DIR/nexe-sidecar-$HOST_TRIPLE"
    echo "    Copied to: $BINARIES_DIR/nexe-sidecar-$HOST_TRIPLE"
fi

# ── Step 7: Validate ─────────────────────────────────────────────────
# F5.2.1: PBS de uv té prefix hardcoded /install — PYTHONHOME OBLIGATORI per
# trobar el mòdul `encodings` al bootstrap (init_fs_encoding). El pyvenv.cfg
# `home` només s'aplica post-bootstrap (site-packages discovery del venv).
# Validat empíricament 2026-05-18 build run 1: sense PYTHONHOME falla amb
# "Fatal Python error: init_fs_encoding: failed... No module named 'encodings'".
# El launcher (Step 5) sempre defineix PYTHONHOME, igual que els tests aquí.
echo "==> Validating sidecar..."
PYTHONHOME="$SIDECAR_DIR/python-runtime" "$VENV_PY" -c "import fastapi; print(f'  FastAPI {fastapi.__version__}')"
PYTHONHOME="$SIDECAR_DIR/python-runtime" "$VENV_PY" -c "import uvicorn; print(f'  uvicorn {uvicorn.__version__}')"

# Authenticated smoke test: generate a real UUID token + dynamic port so the
# test mirrors the actual Tauri spawn contract (token via stdin, port via env).
# An empty token would cause app.py to call os._exit(1) immediately.
echo "==> Smoke test (boot + authenticated health check)..."
SMOKE_TOKEN=$(PYTHONHOME="$SIDECAR_DIR/python-runtime" "$VENV_PY" -c "import uuid; print(uuid.uuid4())")
SMOKE_PORT=$(PYTHONHOME="$SIDECAR_DIR/python-runtime" "$VENV_PY" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); p=s.getsockname()[1]; s.close(); print(p)")

# F1 (BUG-NF-30b ad-hoc): endpoint health depèn de l'app del sidecar.
# - POC default (poc-sidecar/app.py): /api/v1/system/health
# - server-nexe real: /admin/system/health (registrat a system.py:246)
# Detecció via APP_SOURCE_DIR (empty=POC, set=multi-file → assumim server-nexe).
# Quan F2 (M0-bis) refactori la unificació, aquest condicional desapareix.
if [ -n "$APP_SOURCE_DIR" ]; then
    HEALTH_PATH="/admin/system/health"
    # server-nexe arrenca lent (RAG + memory + tray + fastembed pre-warm)
    SMOKE_BOOT_MAX_WAIT=30
else
    HEALTH_PATH="/api/v1/system/health"
    SMOKE_BOOT_MAX_WAIT=5
fi

# Env vars que Tauri (lib.rs spawn_sidecar_process) injecta en producció.
# Repliquem aquí al smoke per coherència — sense això, validate_production_security
# (factory_security.py) tira ValueError abans d'arribar a uvicorn.
echo "$SMOKE_TOKEN" | \
    NEXE_PORT="$SMOKE_PORT" \
    NEXE_SIDECAR=1 \
    NEXE_ENV=production \
    NEXE_PRIMARY_API_KEY="$SMOKE_TOKEN" \
    NEXE_APPROVED_MODULES="security,memory,rag,embeddings,mlx_module,llama_cpp_module,ollama_module" \
    NEXE_HOME="$SIDECAR_DIR/app" \
    NEXE_LOGS_DIR="$SIDECAR_DIR/logs" \
    NEXE_DATA_DIR="$SIDECAR_DIR/data" \
    NEXE_CACHE_DIR="$SIDECAR_DIR/cache" \
    NEXE_QDRANT_PATH="$SIDECAR_DIR/vectors" \
    NEXE_PARENT_PID="$$" \
    NEXE_TRAY_PID="$$" \
    "$SIDECAR_DIR/nexe-sidecar" >/tmp/F1-sidecar-boot.log 2>&1 &
SIDECAR_PID=$!

# Polling adaptat — server-nexe triga 15-25s a estar ready (memory + fastembed pre-warm).
# Sortim del bucle al primer 200 o quan superem el màxim.
# Desactivem set -e localment: curl -sf retorna codi != 0 quan el sidecar encara no
# accepta connexions (ECONNREFUSED), i amb set -e actiu això mata el script.
set +e
HEALTH="FAIL"
SMOKE_ELAPSED=0
while [ "$SMOKE_ELAPSED" -lt "$SMOKE_BOOT_MAX_WAIT" ]; do
    sleep 1
    SMOKE_ELAPSED=$((SMOKE_ELAPSED + 1))
    if ! kill -0 "$SIDECAR_PID" 2>/dev/null; then
        echo "    Sidecar process died at ${SMOKE_ELAPSED}s — boot failed"
        break
    fi
    RESP=$(curl -sf -H "Authorization: Bearer $SMOKE_TOKEN" "http://127.0.0.1:$SMOKE_PORT${HEALTH_PATH}" 2>/dev/null)
    if echo "$RESP" | grep -qE '"status":\s*"(ok|healthy)"'; then
        HEALTH="$RESP"
        echo "    Sidecar ready after ${SMOKE_ELAPSED}s"
        break
    fi
done
set -e

kill "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true

# F5.2a: clean storage created during the smoke test. NEXE_HOME=app/ above
# makes the smoke server fall back to $NEXE_HOME/storage/ for memory + vectors
# + system_core.db + system-logs. Same DEV→bundle contamination pattern as
# .module_cache.json caught in F5.6. At runtime the Rust spawner sets
# NEXE_STORAGE_PATH to the user-writable location, so this scratch storage
# must never reach the tarball.
rm -rf "$SIDECAR_DIR/app/storage" 2>/dev/null || true

# F5.2a: also re-strip __pycache__ from venv/ — the smoke test imports
# uvicorn + FastAPI + sidecar modules, and CPython writes fresh .pyc files
# into site-packages/**/__pycache__/ even though Step 6 trimmed them earlier.
# These .pyc are not a notarytool issue (Apple accepted them) but bloat the
# tarball and violate G1 (no transient artifacts in payload).
find "$SIDECAR_DIR/venv" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Match condicional: POC retorna {"status":"ok"}, server-nexe retorna {"status":"healthy"...}
if echo "$HEALTH" | grep -qE '"status":\s*"(ok|healthy)"'; then
    echo "    Health check: PASS (authenticated, endpoint $HEALTH_PATH)"
else
    echo "    Health check: FAIL (endpoint $HEALTH_PATH)"
    echo "    Response: $HEALTH"
    echo "    Sidecar boot log: /tmp/F1-sidecar-boot.log (últimes 20 línies):"
    tail -20 /tmp/F1-sidecar-boot.log 2>/dev/null
    exit 1
fi

# ── Step 8: Report ────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  POC SIDECAR BUILD COMPLETE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Output:     $SIDECAR_DIR"
echo "  Launcher:   $SIDECAR_DIR/nexe-sidecar"
echo "  Python:     $("$VENV_PY" --version)"
echo "  Arch:       $(uname -m)"
echo "  Bundle size:"
du -sh "$SIDECAR_DIR/venv"
du -sh "$SIDECAR_DIR/app"
du -sh "$SIDECAR_DIR" | awk '{print "  TOTAL: " $1}'
echo ""
echo "  To run manually:"
echo "    $SIDECAR_DIR/nexe-sidecar"
echo ""
echo "  Tauri integration (Fase 2):"
echo "    externalBin or Command::new(\"nexe-sidecar\")"
echo "    with env NEXE_AUTH_TOKEN=<token>"
echo "════════════════════════════════════════════════════════════════"
