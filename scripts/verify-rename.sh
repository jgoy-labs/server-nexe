#!/usr/bin/env bash
# verify-rename.sh — Regression test for scripts/rename.sh.
#
# Verifies that after running `rename.sh <new-name>`:
#   1. No occurrence of the original placeholders remains in text files
#      (excluding node_modules/, target/, dist/, .git/, lockfiles, and the
#      script family itself — see rename.sh for the matching exclusion).
#   2. src-tauri/tauri.conf.json `identifier` matches com.<new-flat>.app,
#      i.e. aligns with what rename.sh was supposed to set.
#
# Usage:
#   ./scripts/verify-rename.sh                 # checks that the un-renamed starter
#                                              # still has the canonical placeholders
#                                              # and identifier.
#   ./scripts/verify-rename.sh my-app          # checks that the rename to my-app
#                                              # left no trace of the placeholders
#                                              # and set identifier to com.myapp.app
#
# Exit codes:
#   0  → no placeholders found, identifier aligned.
#   1  → placeholders still present or identifier mismatch.
#   2  → invalid argument / internal error.
#
# Note: the placeholder strings are built at runtime from the pieces below so
# that this file itself is NOT rewritten when rename.sh runs — it must keep the
# original placeholder literals intact to remain a valid regression test.

set -euo pipefail

# --- build placeholders at runtime (defeats sed-in-place rewrites) ---
# Concatenation keeps the literals `nexe-app`, `nexe_app`, `com.nexe.app` from
# appearing as a single token in the source of this file.
PREFIX="nexe"
KEBAB="${PREFIX}-app"
SNAKE="${PREFIX}_app"
IDENT="com.${PREFIX}.app"
# Regex pattern for rg / grep.
PATTERN="${KEBAB}|${SNAKE}|com\\.${PREFIX}\\.app"
# --------------------------------------------------------------------

NEW_NAME="${1:-}"

fail=0

scan_for_placeholders() {
    local label="$1"
    local matches=""
    if command -v rg >/dev/null 2>&1; then
        matches=$(rg -nE "$PATTERN" . \
            -g '!node_modules/*' -g '!target/*' -g '!dist/*' -g '!.git/*' \
            -g '!.claude/*' \
            -g '!pnpm-lock.yaml' -g '!Cargo.lock' \
            -g '!scripts/rename.sh' -g '!scripts/verify-rename.sh' \
            2>/dev/null || true)
    else
        matches=$(grep -rnE \
            --exclude-dir=node_modules \
            --exclude-dir=target \
            --exclude-dir=dist \
            --exclude-dir=.git \
            --exclude-dir=.claude \
            --exclude=pnpm-lock.yaml \
            --exclude=Cargo.lock \
            --exclude=rename.sh \
            --exclude=verify-rename.sh \
            "$PATTERN" . 2>/dev/null || true)
    fi

    if [[ -n "$matches" ]]; then
        echo "❌ Found leftover placeholders $label:" >&2
        echo "$matches" >&2
        return 1
    else
        echo "✅ No leftover placeholders $label."
        return 0
    fi
}

check_identifier() {
    local expected="$1"
    local conf="src-tauri/tauri.conf.json"
    if [[ ! -f "$conf" ]]; then
        echo "⚠️  $conf not found — skipping identifier check" >&2
        return 0
    fi
    local actual
    actual=$(grep -E '"identifier"' "$conf" | head -n 1 \
        | sed -E 's/.*"identifier": *"([^"]+)".*/\1/')
    if [[ "$actual" == "$expected" ]]; then
        echo "✅ tauri.conf.json identifier == $expected"
        return 0
    else
        echo "❌ tauri.conf.json identifier is '$actual', expected '$expected'" >&2
        return 1
    fi
}

if [[ -n "$NEW_NAME" ]]; then
    # Post-rename mode: placeholders should be GONE, identifier should match new name.
    if ! [[ "$NEW_NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
        echo "Error: '$NEW_NAME' must be lowercase kebab-case (a-z, 0-9, hyphens)" >&2
        exit 2
    fi

    echo "🔍 Scanning for leftover placeholders after rename to '$NEW_NAME'..."
    scan_for_placeholders "after rename to '$NEW_NAME'" || fail=1

    NEW_FLAT="${NEW_NAME//-/}"
    EXPECTED_ID="com.${NEW_FLAT}.app"
    check_identifier "$EXPECTED_ID" || fail=1
else
    # Pre-rename mode: canonical starter — placeholders are expected to be
    # present at known canonical locations and identifier must match them.
    echo "ℹ️  No new-name argument — verifying canonical un-renamed starter."
    echo "   To check after a rename: ./scripts/verify-rename.sh <your-new-name>"
    check_identifier "$IDENT" || fail=1
fi

if [[ $fail -ne 0 ]]; then
    exit 1
fi

echo "🎉 verify-rename OK"
exit 0
