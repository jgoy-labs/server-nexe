"""Tests for base protocols"""
import pytest
from core.contracts.base import (
    BaseContract, ModuleContract,
    ContractMetadata, ContractType, HealthResult, HealthStatus,
    validate_contract, contract_is_module, get_contract_info
)


class TestContractMetadata:
    def test_contract_metadata_creation(self):
        """Test ContractMetadata dataclass"""
        meta = ContractMetadata(
            contract_id="test",
            contract_type=ContractType.MODULE,
            name="Test",
            version="1.0.0",
            description="Test contract"
        )

        assert meta.contract_id == "test"
        assert meta.contract_type == ContractType.MODULE
        assert meta.is_module()
        assert not meta.is_core()

    def test_has_capability(self):
        """Test has_capability method"""
        meta = ContractMetadata(
            contract_id="test",
            contract_type=ContractType.MODULE,
            name="Test",
            version="1.0.0",
            capabilities={"has_api": True, "has_ui": False}
        )

        assert meta.has_capability("has_api")
        assert not meta.has_capability("has_ui")
        assert not meta.has_capability("nonexistent")

    def test_to_dict(self):
        """Test to_dict serialization"""
        meta = ContractMetadata(
            contract_id="test",
            contract_type=ContractType.MODULE,
            name="Test",
            version="1.0.0"
        )

        data = meta.to_dict()
        assert data["contract_id"] == "test"
        assert data["name"] == "Test"


class TestHealthResult:
    def test_health_result_creation(self):
        """Test HealthResult dataclass"""
        result = HealthResult(
            status=HealthStatus.HEALTHY,
            message="All OK",
            details={"checks": 5}
        )

        assert result.status == HealthStatus.HEALTHY
        assert result.is_healthy()
        assert not result.is_degraded()

    def test_to_dict(self):
        """Test HealthResult serialization"""
        result = HealthResult(
            status=HealthStatus.HEALTHY,
            message="All OK",
            details={"checks": 5}
        )

        data = result.to_dict()
        assert data["status"] == "healthy"
        assert data["message"] == "All OK"
        assert data["details"]["checks"] == 5


class TestBaseContract:
    def test_base_contract_implementation(self):
        """Test BaseContract protocol implementation"""

        class TestContract:
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
                return HealthResult(status=HealthStatus.HEALTHY)

        contract = TestContract()

        # Runtime check
        assert isinstance(contract, BaseContract)
        assert validate_contract(contract)

        # Check methods exist
        assert hasattr(contract, 'metadata')
        assert hasattr(contract, 'initialize')
        assert hasattr(contract, 'shutdown')
        assert hasattr(contract, 'health_check')


class TestModuleContract:
    def test_module_contract_implementation(self):
        """Test ModuleContract protocol implementation"""

        class TestModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test_module",
                    contract_type=ContractType.MODULE,
                    name="Test Module",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY)

            def get_router(self):
                return None

            def get_router_prefix(self):
                return "/test"

        module = TestModule()

        # Runtime checks
        assert isinstance(module, BaseContract)
        assert isinstance(module, ModuleContract)
        assert validate_contract(module)
        assert contract_is_module(module)

        # Check module-specific methods
        assert hasattr(module, 'get_router')
        assert hasattr(module, 'get_router_prefix')
        assert module.get_router_prefix() == "/test"


class TestHelpers:
    def test_get_contract_info(self):
        """Test get_contract_info helper"""

        class TestContract:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="test",
                    contract_type=ContractType.MODULE,
                    name="Test",
                    version="1.0.0",
                    description="Test contract",
                    capabilities={"has_api": True}
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY)

        contract = TestContract()
        info = get_contract_info(contract)

        assert info["id"] == "test"
        assert info["type"] == "module"
        assert info["name"] == "Test"
        assert info["version"] == "1.0.0"
        assert info["capabilities"]["has_api"] is True
