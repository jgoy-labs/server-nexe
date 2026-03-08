#!/usr/bin/env bash
# Run the same unit test suite as GitHub Actions (Linux) using Docker.
# Outputs coverage.xml in the repo root.

set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "[linux-ci] ERROR: docker not found. Install Docker Desktop / Engine." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTEST_CMD='pytest core memory personality plugins -m "not integration and not e2e and not slow" --cov=core --cov=memory --cov=personality --cov=plugins --cov-report=term --cov-report=xml:coverage.xml --tb=short -q'

echo "[linux-ci] Repo: $REPO_ROOT"
echo "[linux-ci] Running unit tests + coverage via Docker..."

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e NEXE_ENV=testing \
  -e NEXE_PRIMARY_API_KEY=test-key-for-linux \
  -e NEXE_CSRF_SECRET=test-csrf-secret-for-linux \
  -v "$REPO_ROOT:/work" \
  -w /work \
  python:3.11 \
  bash -lc "
    set -euo pipefail
    python -m venv /tmp/venv-nexe
    source /tmp/venv-nexe/bin/activate
    python -m pip install -q -r requirements.txt
    $PYTEST_CMD
    ls -la coverage.xml || true
  "

echo "[linux-ci] Done."

