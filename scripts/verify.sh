#!/usr/bin/env bash
# verify.sh — Run the same checks as CI, locally.
# Usage: ./scripts/verify.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== pnpm install ==="
pnpm install --frozen-lockfile

echo ""
echo "=== vitest ==="
pnpm test

echo ""
echo "=== vite build ==="
pnpm run build

echo ""
echo "=== pnpm audit (all deps incl. dev, warning-only — mirrors CI) ==="
# Mirrors CI check.yml: pnpm audit --audit-level=moderate (continue-on-error in CI)
# Dev deps (vite/vitest/tauri-cli) don't go to production — audit is informational.
pnpm audit --audit-level=moderate || true

cd src-tauri

echo ""
echo "=== cargo fmt --check ==="
cargo fmt -- --check

echo ""
echo "=== cargo clippy -D warnings ==="
cargo clippy --locked -- -D warnings

echo ""
echo "=== cargo test ==="
cargo test --locked

echo ""
echo "=== cargo audit --deny warnings ==="
cargo audit --deny warnings

echo ""
echo "=== Audit expire-date check (C18) ==="
cd ..
bash scripts/check-audit-dates.sh
cd src-tauri

echo ""
echo "=== Duplicate deps check (C37) ==="
COUNT=$(cargo tree --duplicates 2>/dev/null | grep -cE "^[a-z]")
echo "Duplicate top-level crates: $COUNT"
# Threshold: fail if > 80 (baseline actual 73 raw lines, 2026-04-21)
# See docs/supply-chain/duplicate-deps.md. Adjust down as tauri-utils/kuchikiki resolve upstream.
if [[ $COUNT -gt 80 ]]; then
  echo "WARNING: duplicate crates exceeded threshold ($COUNT > 80)"
  exit 1
fi
echo "OK — duplicate crate count within threshold."

echo ""
echo "✅ All verification checks passed."
