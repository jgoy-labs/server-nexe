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
from personality.i18n.resolve import t_modular


def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"scripts.migrate.{key}", fallback, **kwargs)


def print_result(result: MigrationResult):
    """Print migration result"""
    print(f"\n{'='*60}")
    print(_t("plugin", "Plugin: {name}", name=result.original_path.parent.name))
    status = _t("status_success", "✓ SUCCESS") if result.success else _t("status_failed", "✗ FAILED")
    print(_t("status_line", "Status: {status}", status=status))
    print(f"{'='*60}")

    if result.warnings:
        print(_t("warnings_title", "\nWarnings:"))
        for warning in result.warnings:
            print(_t("warning_item", "  ⚠️  {warning}", warning=warning))

    if result.errors:
        print(_t("errors_title", "\nErrors:"))
        for error in result.errors:
            print(_t("error_item", "  ❌ {error}", error=error))

    if result.success:
        print(_t("migrated_written", "\nMigrated manifest written to:"))
        print(_t("migrated_path", "  {path}", path=result.migrated_path))


def main():
    parser = argparse.ArgumentParser(description="Migrate plugin manifests")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files")
    parser.add_argument("--plugin", type=str, help="Migrate specific plugin")
    args = parser.parse_args()

    plugins_dir = project_root / "plugins"

    if not plugins_dir.exists():
        print(_t("plugins_dir_not_found", "❌ Plugins directory not found: {path}", path=plugins_dir))
        return 1

    migrator = ManifestMigrator()

    # Migrate specific plugin or all
    if args.plugin:
        plugin_dir = plugins_dir / args.plugin
        if not plugin_dir.exists():
            print(_t("plugin_not_found", "❌ Plugin not found: {path}", path=plugin_dir))
            return 1

        manifest_path = plugin_dir / "manifest.toml"
        if not manifest_path.exists():
            print(_t("manifest_not_found", "❌ Manifest not found: {path}", path=manifest_path))
            return 1

        result = migrator.migrate_manifest(manifest_path, dry_run=args.dry_run)
        print_result(result)

        return 0 if result.success else 1

    else:
        # Migrate all
        results = migrator.migrate_all_plugins(plugins_dir, dry_run=args.dry_run)

        # Print summary
        print(f"\n{'='*60}")
        print(_t("summary_title", "MIGRATION SUMMARY"))
        print(f"{'='*60}")
        print(_t("summary_total", "Total plugins: {count}", count=len(results)))
        print(_t("summary_successful", "Successful: {count}", count=sum(1 for r in results if r.success)))
        print(_t("summary_failed", "Failed: {count}", count=sum(1 for r in results if not r.success)))

        # Print individual results
        for result in results:
            print_result(result)

        # Return code
        return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
