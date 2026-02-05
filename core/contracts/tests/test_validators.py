"""Tests per ContractValidator"""
import pytest
from pathlib import Path
import tempfile
import shutil
import toml

from core.contracts.validators import (
    ContractValidator,
    get_validator,
    ValidationResult,
    ValidationIssue,
    ValidationLevel,
    ValidationSeverity
)
from core.contracts.models import UnifiedManifest, ModuleSection, CapabilitiesSection
from core.contracts.base import ContractMetadata, ContractType, HealthResult, HealthStatus


class TestContractValidator:
    """Tests per ContractValidator"""

    @pytest.fixture
    def validator(self):
        """Fixture per crear validator"""
        return ContractValidator()

    @pytest.fixture
    def temp_plugin_dir(self):
        """Fixture per crear directori temporal de plugin"""
        temp_dir = tempfile.mkdtemp()
        plugin_dir = Path(temp_dir) / "test_plugin"
        plugin_dir.mkdir()
        yield plugin_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def minimal_manifest(self):
        """Manifest mínim vàlid"""
        return UnifiedManifest(
            module=ModuleSection(
                name="test_plugin",
                version="1.0.0"
            )
        )

    @pytest.fixture
    def mock_contract(self):
        """Mock d'un contracte vàlid"""
        class MockContract:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test",
                    contract_type=ContractType.MODULE,
                    name="Test",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(
                    status=HealthStatus.HEALTHY,
                    message="OK"
                )

        return MockContract()

    def test_get_validator_singleton(self):
        """Test que get_validator retorna singleton"""
        validator1 = get_validator()
        validator2 = get_validator()
        assert validator1 is validator2

    def test_validation_result_creation(self):
        """Test creació de ValidationResult"""
        result = ValidationResult(
            valid=True,
            issues=[],
            contract_id="test"
        )
        assert result.valid is True
        assert len(result.issues) == 0
        assert result.contract_id == "test"

    def test_validation_result_with_errors(self):
        """Test ValidationResult amb errors"""
        issues = [
            ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.ERROR,
                message="Error 1"
            ),
            ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.ERROR,
                message="Error 2"
            )
        ]
        result = ValidationResult(
            valid=False,
            issues=issues
        )
        assert result.valid is False
        assert len(result.issues) == 2
        assert result.has_errors() is True

    def test_validate_manifest_schema_valid(self, validator, temp_plugin_dir):
        """Test validació schema amb manifest vàlid"""
        # Crear manifest vàlid
        manifest_path = temp_plugin_dir / "manifest.toml"
        manifest_data = {
            "manifest_version": "1.0",
            "module": {
                "name": "test_plugin",
                "version": "1.0.0",
                "type": "module"
            },
            "capabilities": {
                "has_api": False
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(manifest_data, f)

        result = validator.validate_manifest_schema(manifest_path)

        assert result.valid is True
        assert len(result.issues) == 0

    def test_validate_manifest_schema_missing_file(self, validator):
        """Test validació amb fitxer inexistent"""
        fake_path = Path("/tmp/nonexistent/manifest.toml")
        result = validator.validate_manifest_schema(fake_path)

        assert result.valid is False
        assert len(result.issues) > 0

    def test_validate_manifest_schema_invalid_toml(self, validator, temp_plugin_dir):
        """Test validació amb TOML invàlid"""
        manifest_path = temp_plugin_dir / "manifest.toml"
        with open(manifest_path, "w") as f:
            f.write("invalid toml {[}")

        result = validator.validate_manifest_schema(manifest_path)

        assert result.valid is False
        assert len(result.issues) > 0

    def test_validate_manifest_schema_invalid_pydantic(self, validator, temp_plugin_dir):
        """Test validació amb dades invàlides per Pydantic"""
        manifest_path = temp_plugin_dir / "manifest.toml"
        manifest_data = {
            "module": {
                "name": "test with spaces",  # Invalid!
                "version": "1.0.0"
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(manifest_data, f)

        result = validator.validate_manifest_schema(manifest_path)

        assert result.valid is False
        assert len(result.issues) > 0

    def test_validate_contract_runtime_valid(self, validator, mock_contract):
        """Test validació runtime amb contracte vàlid"""
        result = validator.validate_contract_runtime(mock_contract)

        # Valid pot ser True fins i tot amb warnings
        assert result.valid is True
        # Pot tenir warnings (com no implementar ModuleContract completament)
        assert not result.has_errors()

    def test_validate_contract_runtime_invalid(self, validator):
        """Test validació runtime amb objecte invàlid"""
        invalid_object = {"not": "a contract"}
        result = validator.validate_contract_runtime(invalid_object)

        assert result.valid is False
        assert len(result.issues) > 0

    def test_validate_contract_runtime_missing_method(self, validator):
        """Test validació amb mètode faltant"""
        class IncompleteContract:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test",
                    contract_type=ContractType.MODULE,
                    name="Test",
                    version="1.0.0"
                )
            # Falta initialize, shutdown, health_check

        instance = IncompleteContract()
        result = validator.validate_contract_runtime(instance)

        assert result.valid is False

    def test_validate_file_structure_minimal(self, validator, temp_plugin_dir, minimal_manifest):
        """Test validació estructura fitxers mínima"""
        # Crear __init__.py
        (temp_plugin_dir / "__init__.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, minimal_manifest)

        assert result.valid is True

    def test_validate_file_structure_missing_init(self, validator, temp_plugin_dir, minimal_manifest):
        """Test validació sense __init__.py (genera warning)"""
        result = validator.validate_file_structure(temp_plugin_dir, minimal_manifest)

        # Valid pot ser True amb warnings
        assert len(result.issues) > 0  # Ha de tenir issues

    def test_validate_file_structure_with_api(self, validator, temp_plugin_dir):
        """Test validació amb API"""
        from core.contracts.models import APISection

        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_api=True),
            api=APISection(prefix="/test")
        )

        # Crear fitxers necessaris
        (temp_plugin_dir / "__init__.py").touch()
        (temp_plugin_dir / "module.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        assert result.valid is True

    def test_validate_file_structure_missing_module_py(self, validator, temp_plugin_dir):
        """Test validació API sense module.py (genera warning)"""
        from core.contracts.models import APISection

        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_api=True),
            api=APISection(prefix="/test")
        )

        (temp_plugin_dir / "__init__.py").touch()
        # NO crear module.py

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        # Genera warnings
        assert len(result.issues) > 0

    def test_validate_file_structure_with_ui(self, validator, temp_plugin_dir):
        """Test validació amb UI"""
        from core.contracts.models import UISection

        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_ui=True),
            ui=UISection(path="ui", main_file="index.html", route="/test/ui")
        )

        # Crear fitxers necessaris
        (temp_plugin_dir / "__init__.py").touch()
        ui_dir = temp_plugin_dir / "ui"
        ui_dir.mkdir()
        (ui_dir / "index.html").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        assert result.valid is True

    def test_validate_file_structure_missing_ui_dir(self, validator, temp_plugin_dir):
        """Test validació UI sense directori ui/ (genera warning)"""
        from core.contracts.models import UISection

        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_ui=True),
            ui=UISection(path="ui", main_file="index.html", route="/test/ui")
        )

        (temp_plugin_dir / "__init__.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        # Genera warnings
        assert len(result.issues) > 0

    def test_validate_file_structure_with_tests(self, validator, temp_plugin_dir):
        """Test validació amb tests"""
        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_tests=True)
        )

        # Crear fitxers necessaris
        (temp_plugin_dir / "__init__.py").touch()
        tests_dir = temp_plugin_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        assert result.valid is True

    def test_validate_file_structure_missing_tests_dir(self, validator, temp_plugin_dir):
        """Test validació tests sense directori tests/ (genera warning)"""
        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_tests=True)
        )

        (temp_plugin_dir / "__init__.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        # Genera warnings
        assert len(result.issues) > 0

    def test_validate_all_success(self, validator, temp_plugin_dir):
        """Test validate_all amb plugin vàlid complet"""
        # Crear manifest
        manifest_path = temp_plugin_dir / "manifest.toml"
        manifest_data = {
            "manifest_version": "1.0",
            "module": {
                "name": "test_plugin",
                "version": "1.0.0"
            },
            "capabilities": {
                "has_api": False
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(manifest_data, f)

        # Crear __init__.py
        (temp_plugin_dir / "__init__.py").touch()

        result = validator.validate_all(temp_plugin_dir)

        # Retorna un sol ValidationResult
        assert isinstance(result, ValidationResult)
        # Pot tenir warnings però no errors
        assert not result.has_errors()

    def test_validate_all_with_errors(self, validator, temp_plugin_dir):
        """Test validate_all amb errors"""
        # Crear manifest invàlid
        manifest_path = temp_plugin_dir / "manifest.toml"
        with open(manifest_path, "w") as f:
            f.write("invalid toml {[}")

        result = validator.validate_all(temp_plugin_dir)

        # Ha de tenir errors
        assert isinstance(result, ValidationResult)
        assert result.has_errors()

    def test_validator_caches_instance(self):
        """Test que validator és singleton amb cache"""
        validator1 = get_validator()
        validator2 = get_validator()

        assert validator1 is validator2
        assert id(validator1) == id(validator2)

    def test_validate_contract_runtime_with_module_contract(self, validator):
        """Test validació runtime amb ModuleContract complet"""
        class FullModuleContract:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="full_module",
                    contract_type=ContractType.MODULE,
                    name="Full Module",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

            def get_router(self):
                return None

            def get_router_prefix(self):
                return "/full"

        module = FullModuleContract()
        result = validator.validate_contract_runtime(module)

        # Ha de validar sense warnings perquè implementa tot
        assert result.valid is True

    def test_validate_file_structure_with_cli(self, validator, temp_plugin_dir):
        """Test validació amb CLI"""
        from core.contracts.models import CLISection

        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(has_cli=True),
            cli=CLISection(
                command_name="test",
                entry_point="test.cli",
                commands=["cmd1"]
            )
        )

        (temp_plugin_dir / "__init__.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        # CLI no requereix fitxers específics, només __init__.py
        assert result.valid is True

    def test_validate_file_structure_with_all_features(self, validator, temp_plugin_dir):
        """Test validació amb totes les features"""
        from core.contracts.models import APISection, UISection, CLISection

        manifest = UnifiedManifest(
            module=ModuleSection(name="test", version="1.0.0"),
            capabilities=CapabilitiesSection(
                has_api=True,
                has_ui=True,
                has_cli=True,
                has_tests=True
            ),
            api=APISection(prefix="/test"),
            ui=UISection(path="ui", main_file="index.html", route="/test/ui"),
            cli=CLISection(command_name="test", entry_point="test.cli", commands=[])
        )

        # Crear tots els fitxers necessaris
        (temp_plugin_dir / "__init__.py").touch()
        (temp_plugin_dir / "module.py").touch()
        ui_dir = temp_plugin_dir / "ui"
        ui_dir.mkdir()
        (ui_dir / "index.html").touch()
        tests_dir = temp_plugin_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").touch()

        result = validator.validate_file_structure(temp_plugin_dir, manifest)

        assert result.valid is True
        # Pot tenir alguns warnings però no errors
        assert not result.has_errors()

    def test_validate_all_with_warnings(self, validator, temp_plugin_dir):
        """Test validate_all amb warnings pero sense errors"""
        # Crear manifest vàlid
        manifest_path = temp_plugin_dir / "manifest.toml"
        manifest_data = {
            "manifest_version": "1.0",
            "module": {
                "name": "test_plugin",
                "version": "1.0.0"
            },
            "capabilities": {
                "has_api": False
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(manifest_data, f)

        # No crear __init__.py per generar warning

        result = validator.validate_all(temp_plugin_dir)

        # Valid pot ser True amb warnings
        assert isinstance(result, ValidationResult)
        # Té issues (warnings)
        assert len(result.issues) > 0

    def test_validation_issue_attributes(self):
        """Test atributs de ValidationIssue"""
        issue = ValidationIssue(
            level=ValidationLevel.SCHEMA,
            severity=ValidationSeverity.ERROR,
            message="Test error",
            details="Error details"
        )

        assert issue.level == ValidationLevel.SCHEMA
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.message == "Test error"
        assert issue.details == "Error details"

    def test_validation_result_has_errors_method(self):
        """Test mètode has_errors de ValidationResult"""
        # Amb errors
        result_with_errors = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.RUNTIME,
                    severity=ValidationSeverity.ERROR,
                    message="Error"
                )
            ]
        )
        assert result_with_errors.has_errors() is True

        # Només warnings
        result_with_warnings = ValidationResult(
            valid=True,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.INTEGRATION,
                    severity=ValidationSeverity.WARNING,
                    message="Warning"
                )
            ]
        )
        assert result_with_warnings.has_errors() is False

        # Sense issues
        result_clean = ValidationResult(valid=True, issues=[])
        assert result_clean.has_errors() is False

    def test_validate_manifest_schema_with_complex_manifest(self, validator, temp_plugin_dir):
        """Test validació amb manifest complex complet"""
        manifest_path = temp_plugin_dir / "manifest.toml"
        manifest_data = {
            "manifest_version": "1.0",
            "module": {
                "name": "complex_plugin",
                "version": "2.5.10",
                "type": "module",
                "description": "Complex test plugin",
                "author": "Test Author",
                "license": "MIT",
                "enabled": True,
                "auto_start": False,
                "priority": 50
            },
            "capabilities": {
                "has_api": True,
                "has_ui": True,
                "has_cli": True,
                "has_tests": True,
                "streaming": True,
                "real_time": False
            },
            "api": {
                "prefix": "/complex",
                "tags": ["test", "complex"],
                "public_routes": ["/public"],
                "protected_routes": ["/protected"],
                "admin_routes": ["/admin"]
            },
            "ui": {
                "path": "ui",
                "main_file": "app.html",
                "route": "/complex/ui",
                "framework": "vue",
                "theme_support": True,
                "responsive": True
            },
            "cli": {
                "command_name": "complex",
                "entry_point": "complex.cli",
                "description": "Complex CLI",
                "commands": ["start", "stop", "status"],
                "framework": "click"
            },
            "dependencies": {
                "modules": ["base_module"],
                "optional_modules": ["optional"],
                "external_services": ["redis"],
                "python_packages": ["requests"]
            },
            "i18n": {
                "enabled": True,
                "default_locale": "en-US",
                "supported_locales": ["en-US", "ca-ES"]
            }
        }
        with open(manifest_path, "w") as f:
            toml.dump(manifest_data, f)

        result = validator.validate_manifest_schema(manifest_path)

        assert result.valid is True
        assert len(result.issues) == 0

    def test_validation_result_has_warnings(self):
        """Test mètode has_warnings de ValidationResult"""
        # Amb warnings
        result_with_warnings = ValidationResult(
            valid=True,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.INTEGRATION,
                    severity=ValidationSeverity.WARNING,
                    message="Warning"
                )
            ]
        )
        assert result_with_warnings.has_warnings() is True

        # Sense warnings
        result_no_warnings = ValidationResult(valid=True, issues=[])
        assert result_no_warnings.has_warnings() is False

    def test_validation_result_get_errors(self):
        """Test mètode get_errors de ValidationResult"""
        issues = [
            ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.ERROR,
                message="Error 1"
            ),
            ValidationIssue(
                level=ValidationLevel.INTEGRATION,
                severity=ValidationSeverity.WARNING,
                message="Warning 1"
            ),
            ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.CRITICAL,
                message="Critical 1"
            )
        ]
        result = ValidationResult(valid=False, issues=issues)

        errors = result.get_errors()
        assert len(errors) == 2  # Error + Critical
        assert all(e.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL] for e in errors)

    def test_validation_result_get_warnings(self):
        """Test mètode get_warnings de ValidationResult"""
        issues = [
            ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.ERROR,
                message="Error 1"
            ),
            ValidationIssue(
                level=ValidationLevel.INTEGRATION,
                severity=ValidationSeverity.WARNING,
                message="Warning 1"
            ),
            ValidationIssue(
                level=ValidationLevel.INTEGRATION,
                severity=ValidationSeverity.WARNING,
                message="Warning 2"
            )
        ]
        result = ValidationResult(valid=False, issues=issues)

        warnings = result.get_warnings()
        assert len(warnings) == 2
        assert all(w.severity == ValidationSeverity.WARNING for w in warnings)

    def test_validation_result_to_dict(self):
        """Test mètode to_dict de ValidationResult"""
        issues = [
            ValidationIssue(
                level=ValidationLevel.SCHEMA,
                severity=ValidationSeverity.ERROR,
                message="Test error",
                details="Error details"
            )
        ]
        result = ValidationResult(
            valid=False,
            issues=issues,
            contract_id="test_contract"
        )

        result_dict = result.to_dict()

        assert result_dict["valid"] is False
        assert result_dict["contract_id"] == "test_contract"
        assert len(result_dict["issues"]) == 1
        assert result_dict["issues"][0]["level"] == "schema"
        assert result_dict["issues"][0]["severity"] == "error"
        assert result_dict["issues"][0]["message"] == "Test error"
