#!/usr/bin/env bash
#
# Server Nexe — scripts/install_precompute_hook.sh
# Author: Jordi Goy
#
# Installs a git pre-commit hook that regenerates the precomputed KB
# artefacts whenever `knowledge/**`, `core/ingest/chunking.py`, or
# `core/ingest/ingest_knowledge.py` are about to be committed. Keeps
# the on-disk manifest in sync with the code that produces it, so the
# CI precompute-check never fails on a forgetful commit.
#
# Usage:
#   scripts/install_precompute_hook.sh             # install
#   scripts/install_precompute_hook.sh --uninstall # remove
#
# The hook is local to this clone. Re-run after `git clone`.

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOK_PATH="$REPO_ROOT/.git/hooks/pre-commit"
MARKER="# server-nexe bug #16 precompute hook"

if [[ "${1:-}" == "--uninstall" ]]; then
  if [[ -f "$HOOK_PATH" ]] && grep -q "$MARKER" "$HOOK_PATH"; then
    rm "$HOOK_PATH"
    echo "uninstalled: $HOOK_PATH"
  else
    echo "no server-nexe hook found at $HOOK_PATH"
  fi
  exit 0
fi

if [[ -f "$HOOK_PATH" ]] && ! grep -q "$MARKER" "$HOOK_PATH"; then
  echo "error: $HOOK_PATH exists and is not managed by this script."
  echo "       remove it manually or back it up before re-running."
  exit 1
fi

cat > "$HOOK_PATH" <<HOOK
#!/usr/bin/env bash
$MARKER
#
# Automatically regenerate knowledge/.embeddings/ when relevant files
# are staged. Keeps bug #16 pre-computed artefacts in sync with the
# source of truth without having to remember to run the script.

set -euo pipefail

REPO_ROOT=\$(git rev-parse --show-toplevel)
cd "\$REPO_ROOT"

# Files whose change invalidates the precomputed vectors.
STAGED=\$(git diff --cached --name-only --diff-filter=ACMR || true)

NEEDS_REGEN=0
while IFS= read -r f; do
  [[ -z "\$f" ]] && continue
  case "\$f" in
    knowledge/.embeddings/*) ;;  # ignore the artefacts themselves
    knowledge/*.md|knowledge/**/*.md)           NEEDS_REGEN=1 ;;
    core/ingest/chunking.py)                    NEEDS_REGEN=1 ;;
    core/ingest/ingest_knowledge.py)            NEEDS_REGEN=1 ;;
    memory/memory/precomputed_loader.py)        NEEDS_REGEN=1 ;;
    scripts/precompute_kb.py)                   NEEDS_REGEN=1 ;;
  esac
done <<< "\$STAGED"

if [[ "\$NEEDS_REGEN" -eq 0 ]]; then
  exit 0
fi

echo "[pre-commit] regenerating knowledge/.embeddings/ (bug #16) ..."

# Prefer the project venv python if present; fall back to system.
PY="\$REPO_ROOT/venv/bin/python"
[[ -x "\$PY" ]] || PY="python3"

"\$PY" scripts/precompute_kb.py

git add knowledge/.embeddings/

echo "[pre-commit] precomputed artefacts updated and staged."
HOOK

chmod +x "$HOOK_PATH"
echo "installed: $HOOK_PATH"
echo "to remove: $(basename "$0") --uninstall"
