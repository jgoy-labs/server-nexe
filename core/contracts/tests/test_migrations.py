"""Tests per ManifestMigrator"""
import pytest
from pathlib import Path
import tempfile
import shutil
import toml

from core.contracts.migrations.manifest_migrator import (
    ManifestMigrator,
    MigrationResult
)


class TestManifestMigrator:
    """Tests per ManifestMigrator"""

    @pytest.fixture
    def migrator(self):
        """Fixture per crear migrator"""
        return ManifestMigrator()

    @pytest.fixture
    def temp_plugin_dir(self):
        """Fixture per crear directori temporal de plugin"""
        temp_dir = tempfile.mkdtemp()
        plugin_dir = Path(temp_dir) / "test_plugin"
        plugin_dir.mkdir()
        yield plugin_dir
        shutil.rmtree(temp_dir)

    def test_detect_format_unknown(self, migrator):
        """Test detectar format desconegut (per defecte)"""
        data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "capabilities": {
                    "has_api": True
                }
            }
        }
        format_type = migrator._detect_format(data)
        assert format_type == "unknown_format"

    def test_detect_format_ollama(self, migrator):
        """Test detectar format Ollama (cli + endpoints)"""
        data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "cli": {"command_name": "test"},
                "endpoints": ["/chat", "/models"]
            }
        }
        format_type = migrator._detect_format(data)
        assert format_type == "ollama_format"

    def test_detect_format_security(self, migrator):
        """Test detectar format Security"""
        data = {
            "module": {"name": "test", "version": "1.0.0"},
            "authentication": {"enabled": True}
        }
        format_type = migrator._detect_format(data)
        assert format_type == "security_format"

    def test_detect_format_mlx(self, migrator):
        """Test detectar format MLX (entry + router)"""
        data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "entry": {"module": "test.module"},
                "router": {"prefix": "/test"}
            }
        }
        format_type = migrator._detect_format(data)
        assert format_type == "mlx_format"

    def test_migrate_data_adds_manifest_version(self, migrator):
        """Test que migració afegeix manifest_version"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0"
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        assert "manifest_version" in new_data
        assert new_data["manifest_version"] == "1.0"

    def test_migrate_data_adds_capabilities(self, migrator):
        """Test que migració afegeix secció capabilities"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0"
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        assert "capabilities" in new_data
        assert isinstance(new_data["capabilities"], dict)

    def test_migrate_data_preserves_module_info(self, migrator):
        """Test que migració preserva info del module"""
        old_data = {
            "module": {
                "name": "test_plugin",
                "version": "1.2.3",
                "description": "Test description"
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        assert new_data["module"]["name"] == "test_plugin"
        assert new_data["module"]["version"] == "1.2.3"
        assert new_data["module"]["description"] == "Test description"

    def test_migrate_manifest_success(self, migrator, temp_plugin_dir):
        """Test migració exitosa"""
        # Crear manifest antic
        manifest_path = temp_plugin_dir / "manifest.toml"
        old_data = {
            "module": {
                "name": "test_plugin",
                "version": "1.0.0"
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(old_data, f)

        # Migrar
        result = migrator.migrate_manifest(manifest_path, dry_run=False)

        assert result.success is True
        assert result.original_path == manifest_path
        # Crea manifest.toml.new
        assert result.migrated_path == temp_plugin_dir / "manifest.toml.new"
        assert result.migrated_path.exists()

    def test_migrate_manifest_dry_run(self, migrator, temp_plugin_dir):
        """Test migració en dry-run mode"""
        # Crear manifest antic
        manifest_path = temp_plugin_dir / "manifest.toml"
        old_data = {
            "module": {
                "name": "test_plugin",
                "version": "1.0.0"
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(old_data, f)

        # Migrar en dry-run
        result = migrator.migrate_manifest(manifest_path, dry_run=True)

        assert result.success is True
        # Dry-run no escriu fitxer
        new_path = temp_plugin_dir / "manifest.toml.new"
        assert not new_path.exists()

    def test_migrate_manifest_handles_missing_file(self, migrator):
        """Test error amb fitxer inexistent"""
        fake_path = Path("/tmp/nonexistent/manifest.toml")
        result = migrator.migrate_manifest(fake_path, dry_run=False)

        assert result.success is False
        assert len(result.errors) > 0

    def test_migrate_manifest_invalid_toml(self, migrator, temp_plugin_dir):
        """Test error amb TOML invàlid"""
        manifest_path = temp_plugin_dir / "manifest.toml"
        with open(manifest_path, "w") as f:
            f.write("invalid toml {[}")

        result = migrator.migrate_manifest(manifest_path, dry_run=False)

        assert result.success is False
        assert len(result.errors) > 0

    def test_migration_result_attributes(self):
        """Test atributs MigrationResult"""
        result = MigrationResult(
            success=True,
            original_path=Path("/test/manifest.toml"),
            migrated_path=Path("/test/manifest.toml.new"),
            warnings=["Warning 1"],
            errors=[]
        )

        assert result.success is True
        assert result.original_path == Path("/test/manifest.toml")
        assert result.migrated_path == Path("/test/manifest.toml.new")
        assert len(result.warnings) == 1
        assert len(result.errors) == 0

    def test_migration_result_with_errors(self):
        """Test MigrationResult amb errors"""
        result = MigrationResult(
            success=False,
            original_path=Path("/test/manifest.toml"),
            migrated_path=Path("/test/manifest.toml"),
            warnings=[],
            errors=["Error 1", "Error 2"]
        )

        assert result.success is False
        assert len(result.errors) == 2

    def test_migrate_all_plugins(self, migrator):
        """Test migració de múltiples plugins"""
        plugins_dir = Path("plugins")
        if not plugins_dir.exists():
            pytest.skip("Directory plugins/ not found")

        results = migrator.migrate_all_plugins(plugins_dir, dry_run=True)

        # Ha de retornar resultats
        assert isinstance(results, list)
        assert all(isinstance(r, MigrationResult) for r in results)

    def test_migrate_ollama_format(self, migrator):
        """Test migració específica de format Ollama"""
        old_data = {
            "module": {
                "name": "ollama",
                "version": "0.5.0",
                "cli": {
                    "command_name": "ollama"
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Ha d'afegir capabilities.has_cli
        assert new_data["capabilities"]["has_cli"] is True
        # Preservar info CLI
        assert "cli" in new_data
        assert new_data["cli"]["command_name"] == "ollama"

    def test_migrate_security_format(self, migrator):
        """Test migració específica de format Security"""
        old_data = {
            "module": {
                "name": "security",
                "version": "0.2"
            },
            "authentication": {
                "enabled": True
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Version normalitzada
        assert new_data["module"]["version"] == "0.2.0"
        # Metadata preservada
        assert "metadata" in new_data

    def test_migrate_mlx_format(self, migrator):
        """Test migració específica de format MLX amb capabilities explícites"""
        old_data = {
            "module": {
                "name": "mlx",
                "version": "0.8.0",
                "capabilities": {
                    "has_api": True
                },
                "router": {
                    "prefix": "/mlx"
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Verifica que capabilities i API section es preserven
        assert new_data["capabilities"]["has_api"] is True
        assert "api" in new_data
        assert new_data["api"]["prefix"] == "/mlx"

    def test_migrate_manifest_validation_error(self, migrator, temp_plugin_dir):
        """Test error en validació Pydantic després de migració"""
        # Crear manifest que migra però no valida
        manifest_path = temp_plugin_dir / "manifest.toml"
        # Això migrarà però la validació pot fallar si falta algun camp crític
        old_data = {
            "module": {
                # Nom invàlid que passarà migració però fallarà validació
                "name": "test plugin with spaces",
                "version": "1.0.0"
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(old_data, f)

        result = migrator.migrate_manifest(manifest_path, dry_run=False)

        # Ha de fallar en validació
        assert result.success is False
        assert len(result.errors) > 0

    def test_migrate_with_custom_sections(self, migrator):
        """Test preservació de seccions custom"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0"
            },
            "custom_section": {
                "key1": "value1",
                "key2": "value2"
            },
            "another_custom": "data"
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Seccions custom preservades a metadata
        assert "metadata" in new_data
        assert "custom_section" in new_data["metadata"]

    def test_migrate_with_i18n(self, migrator):
        """Test migració amb secció i18n"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "i18n": {
                    "enabled": True,
                    "default_locale": "ca-ES"
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # i18n preservada
        assert "i18n" in new_data
        assert new_data["i18n"]["enabled"] is True

    def test_migrate_with_storage(self, migrator):
        """Test migració amb secció storage"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "storage": {
                    "paths": [{"path": "data", "type": "data"}]
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # storage preservada
        assert "storage" in new_data

    def test_migrate_with_ui_section(self, migrator):
        """Test migració amb UI"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "capabilities": {
                    "has_ui": True
                },
                "ui": {
                    "path": "ui",
                    "main_file": "index.html"
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # UI section preservada
        assert new_data["capabilities"]["has_ui"] is True
        assert "ui" in new_data
        assert new_data["ui"]["path"] == "ui"

    def test_migrate_with_dependencies(self, migrator):
        """Test migració amb dependencies"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "dependencies": {
                    "modules": ["module1", "module2"],
                    "optional_modules": ["optional1"]
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Dependencies preservades
        assert "dependencies" in new_data
        assert len(new_data["dependencies"]["modules"]) == 2

    def test_migrate_with_author_in_metadata(self, migrator):
        """Test migració amb author a module.metadata"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "metadata": {
                    "author": "Test Author",
                    "custom_field": "value"
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Author extret de metadata
        assert new_data["module"]["author"] == "Test Author"

    def test_migrate_with_license(self, migrator):
        """Test migració amb license"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "license": "MIT"
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # License preservada
        assert new_data["module"]["license"] == "MIT"

    def test_migrate_with_custom_capabilities(self, migrator):
        """Test migració amb custom capabilities"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "capabilities": {
                    "has_api": True,
                    "custom_feature": True,
                    "another_custom": False,
                    "non_bool_field": "string"  # No és bool, no es preserva
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Capabilities custom preservades
        assert "custom" in new_data["capabilities"]
        assert new_data["capabilities"]["custom"]["custom_feature"] is True
        assert new_data["capabilities"]["custom"]["another_custom"] is False
        # Non-bool no es preserva
        assert "non_bool_field" not in new_data["capabilities"].get("custom", {})

    def test_migrate_with_endpoints(self, migrator):
        """Test migració amb endpoints (format Ollama)"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "endpoints": ["/chat", "/models"],
                "cli": {"command_name": "test"}
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Format detectat com ollama
        assert migrator._detect_format(old_data) == "ollama_format"
        # Migració completa
        assert "metadata" in new_data

    def test_migrate_with_router(self, migrator):
        """Test migració amb router (format MLX)"""
        old_data = {
            "module": {
                "name": "test",
                "version": "1.0.0",
                "capabilities": {
                    "has_api": True
                },
                "router": {
                    "prefix": "/test",
                    "custom_field": "value"
                }
            }
        }
        warnings = []
        new_data = migrator._migrate_data(old_data, warnings)

        # Router transformat a API section
        assert "api" in new_data
        assert new_data["api"]["prefix"] == "/test"
