"""
Tests d'integració entre ModuleManager i ContractRegistry.
"""

import pytest
from pathlib import Path

from core.contracts import (
    get_contract_registry,
    load_manifest_from_toml,
    ContractStatus
)
from personality.module_manager.contract_bridge import get_contract_bridge


class TestContractIntegration:
    """Tests d'integració del sistema de contractes"""

    def test_load_unified_manifests(self):
        """Test que els manifests migrats es carreguen correctament"""
        plugins = [
            'ollama_module',
            'mlx_module',
            'security',
            'llama_cpp_module',
            'web_ui_module'
        ]

        for plugin in plugins:
            manifest_path = Path(f"plugins/{plugin}/manifest.toml")
            assert manifest_path.exists(), f"Manifest not found: {manifest_path}"

            # Carregar i validar
            manifest = load_manifest_from_toml(str(manifest_path))

            assert manifest.module.name == plugin
            assert manifest.manifest_version.value == "1.0"
            assert manifest.capabilities is not None

            # Validar seccions condicionals
            if manifest.capabilities.has_api:
                assert manifest.api is not None
                assert manifest.api.prefix.startswith("/")

            if manifest.capabilities.has_ui:
                assert manifest.ui is not None

            if manifest.capabilities.has_cli:
                assert manifest.cli is not None

    def test_contract_registry_singleton(self):
        """Test que ContractRegistry és singleton"""
        registry1 = get_contract_registry()
        registry2 = get_contract_registry()

        assert registry1 is registry2

    def test_contract_bridge_singleton(self):
        """Test que ContractBridge és singleton"""
        bridge1 = get_contract_bridge()
        bridge2 = get_contract_bridge()

        assert bridge1 is bridge2

    @pytest.mark.asyncio
    async def test_mock_module_registration(self):
        """Test registre d'un mòdul mock al ContractRegistry"""
        from core.contracts.base import ContractMetadata, ContractType, HealthResult, HealthStatus

        # Mock module
        class MockModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test_module",
                    contract_type=ContractType.MODULE,
                    name="Test Module",
                    version="1.0.0",
                    description="Test module"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        registry = get_contract_registry()

        # Clear registry for test
        registry.clear()

        # Register mock module
        mock = MockModule()
        success = await registry.register(mock, auto_initialize=False)

        assert success is True
        assert registry.count() == 1
        assert registry.exists("test_module")

        # Get registered contract
        registered = registry.get("test_module")
        assert registered is not None
        assert registered.metadata.contract_id == "test_module"
        assert registered.status == ContractStatus.REGISTERED

        # Health check
        result = await registry.health_check("test_module")
        assert result is not None
        assert result.is_healthy()

        # Unregister
        success = await registry.unregister("test_module")
        assert success is True
        assert registry.count() == 0

    def test_manifest_backwards_compatibility(self):
        """Test que manifests amb .old encara existeixen com a backup"""
        plugins = [
            'ollama_module',
            'mlx_module',
            'security',
            'llama_cpp_module',
            'web_ui_module'
        ]

        for plugin in plugins:
            old_manifest = Path(f"plugins/{plugin}/manifest.toml.old")
            assert old_manifest.exists(), f"Backup not found: {old_manifest}"

    def test_manifest_metadata_preservation(self):
        """Test que metadata custom es preserva en migració"""
        # Security té moltes seccions custom
        manifest = load_manifest_from_toml("plugins/security/manifest.toml")

        # Verificar que custom sections estan a metadata
        assert manifest.metadata is not None
        assert "_migration" in manifest.metadata
        assert manifest.metadata["_migration"]["migrated_by"] == "ManifestMigrator v1.0"

        # Custom capabilities preservades
        if "custom" in manifest.capabilities.model_dump():
            custom_caps = manifest.capabilities.model_dump()["custom"]
            assert isinstance(custom_caps, dict)
