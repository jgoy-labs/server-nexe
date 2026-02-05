"""Tests for Pydantic models"""
import pytest
from pydantic import ValidationError
from core.contracts.models import (
    UnifiedManifest, ModuleSection, CapabilitiesSection,
    APISection, ContractTypeModel,
    load_manifest_from_toml, validate_manifest_dict
)


class TestModuleSection:
    def test_module_section_valid(self):
        """Test valid module section"""
        section = ModuleSection(
            name="test_module",
            version="1.0.0",
            type=ContractTypeModel.MODULE
        )

        assert section.name == "test_module"
        assert section.version == "1.0.0"
        assert section.enabled is True
        assert section.auto_start is False

    def test_module_name_lowercase(self):
        """Test name is converted to lowercase"""
        section = ModuleSection(
            name="TestModule",
            version="1.0.0"
        )

        assert section.name == "testmodule"

    def test_module_name_no_spaces(self):
        """Test name cannot contain spaces"""
        with pytest.raises(ValidationError):
            ModuleSection(
                name="test module",
                version="1.0.0"
            )

    def test_version_pattern(self):
        """Test version must be semantic versioning"""
        # Valid versions
        ModuleSection(name="test", version="1.0.0")
        ModuleSection(name="test", version="12.34.56")

        # Invalid versions
        with pytest.raises(ValidationError):
            ModuleSection(name="test", version="1.0")

        with pytest.raises(ValidationError):
            ModuleSection(name="test", version="v1.0.0")


class TestUnifiedManifest:
    def test_minimal_manifest(self):
        """Test minimal valid manifest"""
        manifest = UnifiedManifest(
            module=ModuleSection(
                name="test",
                version="1.0.0"
            )
        )

        assert manifest.module.name == "test"
        assert manifest.manifest_version.value == "1.0"
        assert manifest.capabilities.has_api is False

    def test_module_with_api_requires_api_section(self):
        """Test [api] required when has_api=true"""
        with pytest.raises(ValidationError, match="api.*section required"):
            UnifiedManifest(
                module=ModuleSection(
                    name="test",
                    version="1.0.0"
                ),
                capabilities=CapabilitiesSection(
                    has_api=True
                )
                # Missing [api] section!
            )

    def test_module_with_api_valid(self):
        """Test valid module with API"""
        manifest = UnifiedManifest(
            module=ModuleSection(
                name="test",
                version="1.0.0"
            ),
            capabilities=CapabilitiesSection(
                has_api=True
            ),
            api=APISection(
                prefix="/test"
            )
        )

        assert manifest.capabilities.has_api is True
        assert manifest.api is not None
        assert manifest.api.prefix == "/test"

    def test_api_prefix_must_start_with_slash(self):
        """Test api.prefix must start with /"""
        with pytest.raises(ValidationError, match="String should match pattern"):
            UnifiedManifest(
                module=ModuleSection(
                    name="test",
                    version="1.0.0"
                ),
                capabilities=CapabilitiesSection(
                    has_api=True
                ),
                api=APISection(
                    prefix="wrong"  # Missing leading /
                )
            )

    def test_api_prefix_can_be_short(self):
        """Test api.prefix can be short (doesn't need to match module name exactly)"""
        # This is valid - allows short prefixes like /ollama instead of /ollama_module
        manifest = UnifiedManifest(
            module=ModuleSection(
                name="ollama_module",
                version="1.0.0"
            ),
            capabilities=CapabilitiesSection(
                has_api=True
            ),
            api=APISection(
                prefix="/ollama"  # Short prefix is OK
            )
        )
        assert manifest.api.prefix == "/ollama"

    def test_to_contract_metadata(self):
        """Test conversion to ContractMetadata"""
        manifest = UnifiedManifest(
            module=ModuleSection(
                name="test",
                version="1.0.0",
                description="Test module"
            ),
            capabilities=CapabilitiesSection(
                has_api=True
            ),
            api=APISection(
                prefix="/test",
                tags=["test", "demo"]
            )
        )

        metadata = manifest.to_contract_metadata()

        assert metadata.contract_id == "test"
        assert metadata.version == "1.0.0"
        assert metadata.description == "Test module"
        assert "test" in metadata.tags
        assert metadata.capabilities["has_api"] is True


class TestValidateManifestDict:
    def test_validate_dict(self):
        """Test validate_manifest_dict"""
        data = {
            "manifest_version": "1.0",
            "module": {
                "name": "test",
                "version": "1.0.0",
                "type": "module"
            }
        }

        manifest = validate_manifest_dict(data)
        assert manifest.module.name == "test"

    def test_validate_invalid_dict(self):
        """Test validation of invalid dict"""
        data = {
            "module": {
                "name": "test with spaces",  # Invalid
                "version": "1.0.0"
            }
        }

        with pytest.raises(ValidationError):
            validate_manifest_dict(data)
