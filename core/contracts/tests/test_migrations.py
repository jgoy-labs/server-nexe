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
