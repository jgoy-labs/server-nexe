#!/bin/bash
# Apply migrated manifests
# Backup old manifests to .old and rename .new to .toml

set -e

PLUGINS_DIR="plugins"

echo "=================================================="
echo "Apply Manifest Migrations"
echo "=================================================="
echo ""

# Check if .new files exist
NEW_COUNT=$(find "$PLUGINS_DIR" -name "manifest.toml.new" 2>/dev/null | wc -l | tr -d ' ')

if [ "$NEW_COUNT" -eq 0 ]; then
    echo "❌ No .new manifests found. Run migrate_manifests.py first."
    exit 1
fi

echo "Found $NEW_COUNT migrated manifests"
echo ""

# Confirm
read -p "This will backup old manifests to .old and apply new ones. Continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Applying migrations..."
echo ""

# Apply each migration
for NEW_FILE in $(find "$PLUGINS_DIR" -name "manifest.toml.new"); do
    DIR=$(dirname "$NEW_FILE")
    PLUGIN=$(basename "$DIR")
    OLD_FILE="$DIR/manifest.toml"
    BACKUP_FILE="$DIR/manifest.toml.old"

    echo "  - $PLUGIN"

    # Backup old manifest
    if [ -f "$OLD_FILE" ]; then
        cp "$OLD_FILE" "$BACKUP_FILE"
        echo "    ✓ Backed up to .old"
    fi

    # Apply new manifest
    mv "$NEW_FILE" "$OLD_FILE"
    echo "    ✓ Applied new manifest"
done

echo ""
echo "=================================================="
echo "✓ Migrations applied successfully!"
echo "=================================================="
echo ""
echo "Old manifests backed up to .old"
echo "To rollback: for f in plugins/*/manifest.toml.old; do mv \"\$f\" \"\${f%.old}\"; done"
