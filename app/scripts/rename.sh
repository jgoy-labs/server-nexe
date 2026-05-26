#!/usr/bin/env bash
# rename.sh — Rename the starter from `nexe-app` to your app name.
#
# Replaces these 3 identifiers across all text files in the repo:
#   nexe-app        → your-app-name       (kebab-case, used in display/tray/paths)
#   nexe_app        → your_app_name       (snake_case, Rust lib name)
#   com.nexe.app    → com.your.app        (Tauri identifier, reverse-DNS)
#
# Also prompts for author/email/repo/homepage and optional branding hygiene.
#
# Usage:
#   ./scripts/rename.sh my-new-app
#
# After running, verify:
#   rg -n 'nexe-app|nexe_app|com\.nexe\.app' . | grep -v node_modules | grep -v target | grep -v dist
# Should return zero matches.

set -euo pipefail

# B7: helper to escape user-supplied strings for use as the RHS of a sed substitution
# using '|' as delimiter. Escapes: & | \ / and leading/trailing special chars.
# Without this, AUTHOR_NAME="foo|bar" or AUTHOR_EMAIL="a/b" would break the sed call.
escape_for_sed_rhs() {
    printf '%s' "$1" | sed -e 's/[&|\/\\]/\\&/g'
}

NEW_NAME="${1:-}"
if [[ -z "$NEW_NAME" ]]; then
    echo "Usage: $0 <new-app-name-kebab-case>"
    echo "Example: $0 my-awesome-app"
    exit 1
fi

# Validate kebab-case
if ! [[ "$NEW_NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
    echo "Error: '$NEW_NAME' must be lowercase kebab-case (a-z, 0-9, hyphens)"
    exit 1
fi

NEW_SNAKE="${NEW_NAME//-/_}"
# Remove hyphens for the reverse-DNS identifier
NEW_FLAT="${NEW_NAME//-/}"
NEW_IDENTIFIER="com.${NEW_FLAT}.app"

echo "Renaming:"
echo "  nexe-app     → $NEW_NAME"
echo "  nexe_app     → $NEW_SNAKE"
echo "  com.nexe.app → $NEW_IDENTIFIER"
echo ""

# Find text files (exclude binary/build/vcs dirs and this script family), do sed replace in place.
# scripts/rename.sh and scripts/verify-rename.sh are excluded because they need the
# placeholder literals to keep working on subsequent forks (and as a regression test).
find . -type f \
    \( -name '*.rs' -o -name '*.toml' -o -name '*.json' -o -name '*.md' \
      -o -name '*.js' -o -name '*.html' -o -name '*.css' -o -name '*.yaml' \
      -o -name '*.yml' -o -name '*.sh' \) \
    -not -path './node_modules/*' \
    -not -path './target/*' \
    -not -path './dist/*' \
    -not -path './.git/*' \
    -not -path './.claude/*' \
    -not -path './scripts/rename.sh' \
    -not -path './scripts/verify-rename.sh' \
    -exec sed -i.bak \
        -e "s/nexe-app/${NEW_NAME}/g" \
        -e "s/nexe_app/${NEW_SNAKE}/g" \
        -e "s/com\\.nexe\\.app/${NEW_IDENTIFIER}/g" \
        {} +

# Cleanup .bak files from BSD sed
find . -name '*.bak' \
    -not -path './node_modules/*' \
    -not -path './target/*' \
    -not -path './.git/*' \
    -delete

echo "Rename applied."
echo ""

# =============================================================================
# === Starter hygiene ===
# =============================================================================

echo "=== Starter hygiene ==="
read -rp "Author name: " AUTHOR_NAME
read -rp "Author email: " AUTHOR_EMAIL
read -rp "Repository URL (https://github.com/...): " REPO_URL
read -rp "Homepage (URL, empty = repo URL): " HOMEPAGE
HOMEPAGE="${HOMEPAGE:-$REPO_URL}"

echo ""
read -rp "Replace Tauri/JS branding logos with placeholders? [Y/n]: " REPLACE_LOGOS
REPLACE_LOGOS="${REPLACE_LOGOS:-Y}"

echo ""
read -rp "Remove RAG plugin spike (iframe)? [Y/n]: " REMOVE_SPIKE
REMOVE_SPIKE="${REMOVE_SPIKE:-Y}"

# Update Cargo.toml authors/repository/homepage
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CARGO_TOML="$SCRIPT_DIR/../src-tauri/Cargo.toml"

if [[ -f "$CARGO_TOML" ]]; then
    echo ""
    echo "Updating Cargo.toml metadata…"
    # B7: escape user-supplied values before embedding them in sed RHS.
    # Prevents breakage if AUTHOR_NAME/EMAIL/URL contain |, &, \, or /.
    AUTHOR_NAME_ESC=$(escape_for_sed_rhs "$AUTHOR_NAME")
    AUTHOR_EMAIL_ESC=$(escape_for_sed_rhs "$AUTHOR_EMAIL")
    REPO_URL_ESC=$(escape_for_sed_rhs "$REPO_URL")
    HOMEPAGE_ESC=$(escape_for_sed_rhs "$HOMEPAGE")
    sed -i.bak \
        -e "s|authors = \[\"The Authors\"\]|authors = [\"${AUTHOR_NAME_ESC} <${AUTHOR_EMAIL_ESC}>\"]|g" \
        -e "s|# repository = .*|repository = \"${REPO_URL_ESC}\"|g" \
        -e "s|# homepage = .*|homepage = \"${HOMEPAGE_ESC}\"|g" \
        "$CARGO_TOML"
    rm -f "${CARGO_TOML}.bak"
    echo "  → Cargo.toml: authors, repository, homepage set"
fi

# Replace logos if requested
if [[ "${REPLACE_LOGOS^^}" != "N" ]]; then
    echo ""
    echo "Replacing Tauri/JS branding logos with app-logo.svg placeholder…"
    # tauri.svg and javascript.svg are no longer referenced in the new index.html,
    # but leave the placeholder SVG for the icon link rel.
    for f in src/assets/tauri.svg src/assets/javascript.svg; do
        FPATH="$SCRIPT_DIR/../$f"
        if [[ -f "$FPATH" ]]; then
            echo "  → removing $f (Tauri/JS branding)"
            rm "$FPATH"
        fi
    done
    echo "  → src/assets/app-logo.svg kept as YOUR LOGO placeholder"
    echo "  → Replace it with your icon; also run: pnpm tauri icon path/to/icon.png"
fi

# Remove RAG spike if requested
if [[ "${REMOVE_SPIKE^^}" != "N" ]]; then
    echo ""
    echo "Removing RAG plugin spike…"
    INDEX_HTML="$SCRIPT_DIR/../src/index.html"
    if [[ -f "$INDEX_HTML" ]]; then
        # Remove the <section id="plugins">…</section> block
        python3 - "$INDEX_HTML" <<'PYEOF'
import sys, re
path = sys.argv[1]
content = open(path).read()
# Remove from <!-- Plugin spike comment down to closing </section> of #plugins
content = re.sub(
    r'\s*<!--[^>]*Plugin spike[^>]*-->.*?<section id="plugins">.*?</section>',
    '',
    content,
    flags=re.DOTALL
)
open(path, 'w').write(content)
print(f"  → removed <section id=\"plugins\"> from {path}")
PYEOF
    fi
    RAG_DIR="$SCRIPT_DIR/../plugins-dev/rag"
    if [[ -d "$RAG_DIR" ]]; then
        rm -rf "$RAG_DIR"
        echo "  → removed plugins-dev/rag/"
    fi
fi

echo ""
echo "Starter ready."
echo ""
echo "Next steps:"
echo "  1. Edit src-tauri/icons/ with your icon set: pnpm tauri icon path/to/icon.png"
echo "  2. Adapt src/index.html and src/main.js for your UI"
echo "  3. Review docs/adr/ — keep or adapt decisions relevant to your app"
echo "  4. rm TEMPLATE.md when you no longer need it"
echo ""

# Regression check — invoke verify-rename.sh if available (preferred).
if [[ -x "$SCRIPT_DIR/verify-rename.sh" ]]; then
    echo "Running regression check (verify-rename.sh)…"
    if "$SCRIPT_DIR/verify-rename.sh" "$NEW_NAME"; then
        echo ""
        echo "Rename complete and verified."
    else
        echo ""
        echo "verify-rename.sh reported issues — review output above and fix manually." >&2
        exit 1
    fi
else
    echo "Verify with:"
    echo "  rg -n 'nexe-app|nexe_app|com\\.nexe\\.app' . \\"
    echo "    -g '!node_modules/*' -g '!target/*' -g '!dist/*' -g '!.git/*'"
    echo ""
    echo "Should return zero matches. If non-zero, review and run sed manually."
fi
