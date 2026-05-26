#!/usr/bin/env bash
# check-audit-dates.sh — Verifica que cap review-date del audit.toml ha passat.
# C18: audit.toml 19 CVEs ignorats sense expiració automàtica.
# Usage: ./scripts/check-audit-dates.sh
# Exit 1 si alguna review-date ha passat (cal revisar els ignores).
#
# B20: Current limitation — all 19 CVE ignores share a single review-date (2026-10-01).
# This means every CVE expires on the same day, making early partial reviews impossible
# and creating a big-bang review burden. Recommended improvement:
#   - Split ignore blocks into groups by expected upstream fix timeline:
#       * Near-term (fix expected ≤3 months):   review-date: 2026-06-01
#       * Mid-term  (fix expected ≤6 months):   review-date: 2026-08-01
#       * Long-term (no upstream fix expected):  review-date: 2027-01-01
#   - Check each CVE page (https://rustsec.org/advisories/RUSTSEC-YYYY-NNNN.html)
#     for "patched" or "unaffected" versions; bump review-date when a fix is available.
# TODO Sprint 0.19: stagger review-dates per CVE group.

set -euo pipefail
cd "$(dirname "$0")/.."

AUDIT_FILE="src-tauri/.cargo/audit.toml"
TODAY=$(date +%Y-%m-%d)
FAIL=0

echo "=== Audit date check (today: $TODAY) ==="

while IFS= read -r line; do
  if echo "$line" | grep -qE "review-date:[[:space:]]*([0-9-]+)"; then
    DATE=$(echo "$line" | grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2}" | head -1)
    if [[ "$DATE" < "$TODAY" ]]; then
      echo "EXPIRED: $line (was $DATE, today $TODAY)"
      FAIL=1
    fi
  fi
done < "$AUDIT_FILE"

if [[ $FAIL -eq 0 ]]; then
  echo "OK — all review-dates are current or future."
fi

exit $FAIL
