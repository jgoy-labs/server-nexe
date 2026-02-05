"""
Manifest Migrator per convertir manifests antics al format UnifiedManifest.
"""

import toml
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MigrationResult:
    """Resultat de migració d'un manifest"""
    success: bool
    original_path: Path
    migrated_path: Path
    warnings: List[str]
    errors: List[str]


class ManifestMigrator:
    """
    Migra manifests antics al format UnifiedManifest.

    Suporta formats:
    - Ollama (module.cli, module.endpoints, module.metadata)
    - Security (authentication, rate_limiting, module.security)
    - MLX (module.entry, module.router)
    """

    def migrate_manifest(self, manifest_path: Path, dry_run: bool = False) -> MigrationResult:
        """
        Migra un manifest al nou format.

        Args:
            manifest_path: Path al manifest.toml antic
            dry_run: Si True, no escriu el fitxer

        Returns:
            MigrationResult amb detalls de la migració
        """
        warnings = []
        errors = []

        if not manifest_path.exists():
            errors.append(f"Manifest not found: {manifest_path}")
            return MigrationResult(
                success=False,
                original_path=manifest_path,
                migrated_path=manifest_path,
                warnings=warnings,
                errors=errors
            )

        # Llegir manifest antic
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                old_data = toml.load(f)
        except Exception as e:
            errors.append(f"Failed to load manifest: {e}")
            return MigrationResult(
                success=False,
                original_path=manifest_path,
                migrated_path=manifest_path,
                warnings=warnings,
                errors=errors
            )

        # Migrar
        try:
            new_data = self._migrate_data(old_data, warnings)
        except Exception as e:
            errors.append(f"Migration failed: {e}")
            return MigrationResult(
                success=False,
                original_path=manifest_path,
                migrated_path=manifest_path,
                warnings=warnings,
                errors=errors
            )

        # Validar amb Pydantic
        try:
            from core.contracts.models import validate_manifest_dict
            manifest = validate_manifest_dict(new_data)
            warnings.append(f"✓ Validated successfully: {manifest.module.name} v{manifest.module.version}")
        except Exception as e:
            errors.append(f"Validation failed: {e}")
            return MigrationResult(
                success=False,
                original_path=manifest_path,
                migrated_path=manifest_path,
                warnings=warnings,
                errors=errors
            )

        # Escriure nou manifest
        migrated_path = manifest_path.parent / "manifest.toml.new"

        if not dry_run:
            try:
                with open(migrated_path, 'w', encoding='utf-8') as f:
                    toml.dump(new_data, f)
            except Exception as e:
                errors.append(f"Failed to write migrated manifest: {e}")
                return MigrationResult(
                    success=False,
                    original_path=manifest_path,
                    migrated_path=migrated_path,
                    warnings=warnings,
                    errors=errors
                )

        return MigrationResult(
            success=True,
            original_path=manifest_path,
            migrated_path=migrated_path,
            warnings=warnings,
            errors=errors
        )

    def _migrate_data(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """
        Migra les dades del manifest antic al nou format.

        Args:
            old_data: Dades del manifest antic
            warnings: Llista per afegir warnings

        Returns:
            Dades en format UnifiedManifest
        """
        new_data: Dict[str, Any] = {
            "manifest_version": "1.0"
        }

        # [module] section (obligatori)
        new_data["module"] = self._migrate_module_section(old_data, warnings)

        # [capabilities] section
        new_data["capabilities"] = self._migrate_capabilities(old_data, warnings)

        # [dependencies] section
        new_data["dependencies"] = self._migrate_dependencies(old_data, warnings)

        # [api] section (si has_api)
        if new_data["capabilities"].get("has_api"):
            new_data["api"] = self._migrate_api_section(old_data, warnings)

        # [ui] section (si has_ui)
        if new_data["capabilities"].get("has_ui"):
            new_data["ui"] = self._migrate_ui_section(old_data, warnings)

        # [cli] section (si has_cli)
        if new_data["capabilities"].get("has_cli"):
            new_data["cli"] = self._migrate_cli_section(old_data, warnings)

        # [i18n] section (si existeix)
        if "module" in old_data and "i18n" in old_data["module"]:
            new_data["i18n"] = old_data["module"]["i18n"]
        elif "i18n" in old_data:
            new_data["i18n"] = old_data["i18n"]

        # [storage] section (si existeix)
        if "module" in old_data and "storage" in old_data["module"]:
            new_data["storage"] = old_data["module"]["storage"]

        # [metadata] - custom data (tot el que no és estàndard)
        new_data["metadata"] = self._collect_custom_metadata(old_data, warnings)

        return new_data

    def _migrate_module_section(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Migra la secció [module]"""
        module = old_data.get("module", {})

        # Normalitzar version (afegir .0 si falta)
        version = module.get("version", "1.0.0")
        if version.count('.') == 1:
            version = f"{version}.0"
            warnings.append(f"Version normalized: {module.get('version')} → {version}")

        result = {
            "name": module.get("name", "unknown"),
            "version": version,
            "type": "module",  # Normalitzar a "module"
            "description": module.get("description", ""),
            "enabled": True,
            "auto_start": False,
            "priority": 10
        }

        # Author (pot estar a module o module.metadata)
        if "author" in module:
            result["author"] = module["author"]
        elif "metadata" in module and "author" in module["metadata"]:
            result["author"] = module["metadata"]["author"]

        # License
        if "license" in module:
            result["license"] = module["license"]

        return result

    def _migrate_capabilities(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Migra la secció [capabilities]"""
        module = old_data.get("module", {})
        caps = module.get("capabilities", {})

        result = {
            "has_api": caps.get("has_api", False),
            "has_ui": caps.get("has_ui", False),
            "has_cli": "cli" in module,  # Detectar si existeix module.cli
            "has_tests": caps.get("has_tests", False),
            "streaming": caps.get("streaming", False),
            "real_time": caps.get("real_time", False)
        }

        # Custom capabilities
        custom = {}
        for key, value in caps.items():
            if key not in result and isinstance(value, bool):
                custom[key] = value

        if custom:
            result["custom"] = custom
            warnings.append(f"Custom capabilities preserved: {list(custom.keys())}")

        return result

    def _migrate_dependencies(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Migra la secció [dependencies]"""
        module = old_data.get("module", {})
        deps = module.get("dependencies", {})

        # També pot estar a top-level
        if not deps and "dependencies" in old_data:
            deps = old_data["dependencies"]

        result = {
            "modules": deps.get("modules", []),
            "optional_modules": deps.get("optional_modules", []),
            "external_services": deps.get("external_services", []),
            "python_packages": deps.get("python", [])
        }

        return result

    def _migrate_api_section(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Migra la secció [api]"""
        module = old_data.get("module", {})
        endpoints = module.get("endpoints", {})

        # Prefix
        prefix = endpoints.get("router_prefix", "/unknown")
        if "router" in module and "prefix" in module["router"]:
            prefix = module["router"]["prefix"]

        result = {
            "enabled": True,
            "prefix": prefix,
            "tags": [],
            "public_routes": endpoints.get("public_routes", []),
            "protected_routes": endpoints.get("protected_routes", []),
            "admin_routes": endpoints.get("admin_routes", [])
        }

        # Rate limiting
        if "module" in old_data and "security" in old_data["module"]:
            security = old_data["module"]["security"]
            if "scan_limit" in security:
                result["rate_limit"] = security["scan_limit"]
        elif "rate_limiting" in old_data:
            rl = old_data["rate_limiting"]
            if "scan_limit" in rl:
                result["rate_limit"] = rl["scan_limit"]

        return result

    def _migrate_ui_section(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Migra la secció [ui]"""
        module = old_data.get("module", {})
        ui = module.get("ui", {})
        endpoints = module.get("endpoints", {})

        result = {
            "enabled": True,
            "path": "ui",
            "main_file": ui.get("main_entry", "index.html"),
            "framework": ui.get("framework", "vanilla-js"),
            "theme_support": ui.get("theme_support", True),
            "responsive": ui.get("responsive", True)
        }

        # Route from endpoints.ui_path
        if "ui_path" in endpoints:
            result["route"] = endpoints["ui_path"]

        return result

    def _migrate_cli_section(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Migra la secció [cli]"""
        module = old_data.get("module", {})
        cli = module.get("cli", {})

        if not cli:
            warnings.append("No CLI section found, but has_cli was detected")
            return {
                "enabled": False,
                "command_name": "unknown",
                "entry_point": "unknown"
            }

        result = {
            "enabled": True,
            "command_name": cli.get("command_name", cli.get("alias", "unknown")),
            "entry_point": cli.get("entry_point", "unknown"),
            "description": cli.get("description", ""),
            "commands": cli.get("commands", []),
            "framework": cli.get("framework", "click")
        }

        return result

    def _collect_custom_metadata(self, old_data: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        """Recull metadata custom (seccions no estàndard)"""
        metadata = {}

        # Seccions estàndard que ja hem migrat
        standard_sections = [
            "module", "dependencies", "paths", "discovery",
            "logging", "i18n", "monitoring", "config", "components"
        ]

        # Recollir seccions custom
        for key, value in old_data.items():
            if key not in standard_sections and not key.startswith("_"):
                metadata[key] = value
                warnings.append(f"Custom section preserved in metadata: [{key}]")

        # Afegir metadata original del module
        if "module" in old_data and "metadata" in old_data["module"]:
            original_meta = old_data["module"]["metadata"]
            for key, value in original_meta.items():
                if key not in ["author"]:  # Author ja està a module
                    metadata[f"original_{key}"] = value

        # Info migració
        metadata["_migration"] = {
            "migrated_at": datetime.now().isoformat(),
            "migrated_by": "ManifestMigrator v1.0",
            "original_format": self._detect_format(old_data)
        }

        return metadata

    def _detect_format(self, old_data: Dict[str, Any]) -> str:
        """Detecta el format del manifest antic"""
        module = old_data.get("module", {})

        if "entry" in module and "router" in module:
            return "mlx_format"
        elif "security" in module or "authentication" in old_data:
            return "security_format"
        elif "cli" in module and "endpoints" in module:
            return "ollama_format"
        else:
            return "unknown_format"

    def migrate_all_plugins(self, plugins_dir: Path, dry_run: bool = False) -> List[MigrationResult]:
        """
        Migra tots els plugins d'un directori.

        Args:
            plugins_dir: Path al directori plugins/
            dry_run: Si True, no escriu fitxers

        Returns:
            Llista de MigrationResult
        """
        results = []

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            manifest_path = plugin_dir / "manifest.toml"
            if not manifest_path.exists():
                continue

            result = self.migrate_manifest(manifest_path, dry_run=dry_run)
            results.append(result)

        return results
