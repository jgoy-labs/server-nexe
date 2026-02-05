#!/usr/bin/env python3
"""
Script per migrar manifests de plugins al format UnifiedManifest.

Usage:
    python scripts/migrate_manifests.py [--dry-run] [--plugin PLUGIN_NAME]
"""

import sys
from pathlib import Path
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.contracts.migrations.manifest_migrator import ManifestMigrator, MigrationResult


def print_result(result: MigrationResult):
    """Print migration result"""
    print(f"\n{'='*60}")
    print(f"Plugin: {result.original_path.parent.name}")
    print(f"Status: {'✓ SUCCESS' if result.success else '✗ FAILED'}")
    print(f"{'='*60}")

    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  ⚠️  {warning}")

    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  ❌ {error}")

    if result.success:
        print(f"\nMigrated manifest written to:")
        print(f"  {result.migrated_path}")


def main():
    parser = argparse.ArgumentParser(description="Migrate plugin manifests")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files")
    parser.add_argument("--plugin", type=str, help="Migrate specific plugin")
    args = parser.parse_args()

    plugins_dir = project_root / "plugins"

    if not plugins_dir.exists():
        print(f"❌ Plugins directory not found: {plugins_dir}")
        return 1

    migrator = ManifestMigrator()

    # Migrate specific plugin or all
    if args.plugin:
        plugin_dir = plugins_dir / args.plugin
        if not plugin_dir.exists():
            print(f"❌ Plugin not found: {plugin_dir}")
            return 1

        manifest_path = plugin_dir / "manifest.toml"
        if not manifest_path.exists():
            print(f"❌ Manifest not found: {manifest_path}")
            return 1

        result = migrator.migrate_manifest(manifest_path, dry_run=args.dry_run)
        print_result(result)

        return 0 if result.success else 1

    else:
        # Migrate all
        results = migrator.migrate_all_plugins(plugins_dir, dry_run=args.dry_run)

        # Print summary
        print(f"\n{'='*60}")
        print("MIGRATION SUMMARY")
        print(f"{'='*60}")
        print(f"Total plugins: {len(results)}")
        print(f"Successful: {sum(1 for r in results if r.success)}")
        print(f"Failed: {sum(1 for r in results if not r.success)}")

        # Print individual results
        for result in results:
            print_result(result)

        # Return code
        return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
