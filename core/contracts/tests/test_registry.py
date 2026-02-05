"""Tests addicionals per ContractRegistry"""
import pytest
from core.contracts.registry import (
    ContractRegistry,
    get_contract_registry,
    RegisteredContract,
    ContractStatus
)
from core.contracts.base import (
    ContractMetadata,
    ContractType,
    HealthResult,
    HealthStatus
)


class TestContractRegistry:
    """Tests per ContractRegistry"""

    @pytest.fixture
    def registry(self):
        """Fixture per crear registry nou (clear)"""
        registry = get_contract_registry()
        registry.clear()
        return registry

    @pytest.fixture
    def mock_module(self):
        """Mock d'un mòdul"""
        class MockModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="mock_module",
                    contract_type=ContractType.MODULE,
                    name="Mock Module",
                    version="1.0.0",
                    description="Test module"
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

        return MockModule()

    @pytest.fixture
    def mock_failing_module(self):
        """Mock d'un mòdul que falla"""
        class FailingModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="failing_module",
                    contract_type=ContractType.MODULE,
                    name="Failing Module",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return False  # Falla

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Not healthy"
                )

        return FailingModule()

    def test_get_registry_singleton(self):
        """Test que get_contract_registry retorna singleton"""
        registry1 = get_contract_registry()
        registry2 = get_contract_registry()
        assert registry1 is registry2

    @pytest.mark.asyncio
    async def test_register_module(self, registry, mock_module):
        """Test registrar mòdul"""
        success = await registry.register(mock_module, auto_initialize=False)

        assert success is True
        assert registry.exists("mock_module")
        assert registry.count() == 1

    @pytest.mark.asyncio
    async def test_register_duplicate(self, registry, mock_module):
        """Test que no es pot registrar duplicat"""
        await registry.register(mock_module, auto_initialize=False)
        success = await registry.register(mock_module, auto_initialize=False)

        assert success is False
        assert registry.count() == 1

    @pytest.mark.asyncio
    async def test_register_with_initialize(self, registry, mock_module):
        """Test registrar amb auto-initialize"""
        success = await registry.register(mock_module, auto_initialize=True)

        assert success is True
        registered = registry.get("mock_module")
        assert registered is not None
        # Després d'initialize, l'estat és INITIALIZED
        assert registered.status == ContractStatus.INITIALIZED

    @pytest.mark.asyncio
    async def test_register_initialize_fails(self, registry, mock_failing_module):
        """Test que initialize pot fallar"""
        success = await registry.register(
            mock_failing_module,
            auto_initialize=True
        )

        # Es registra però initialize falla
        assert registry.exists("failing_module")
        registered = registry.get("failing_module")
        # Status ha de ser REGISTERED, no ACTIVE
        assert registered.status == ContractStatus.REGISTERED

    @pytest.mark.asyncio
    async def test_unregister(self, registry, mock_module):
        """Test desregistrar mòdul"""
        await registry.register(mock_module, auto_initialize=False)
        success = await registry.unregister("mock_module")

        assert success is True
        assert not registry.exists("mock_module")
        assert registry.count() == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, registry):
        """Test desregistrar mòdul inexistent"""
        success = await registry.unregister("nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_unregister_calls_shutdown(self, registry):
        """Test que unregister crida shutdown"""
        shutdown_called = False

        class TrackingModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="tracking",
                    contract_type=ContractType.MODULE,
                    name="Tracking",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                nonlocal shutdown_called
                shutdown_called = True

            async def health_check(self):
                return HealthResult(
                    status=HealthStatus.HEALTHY,
                    message="OK"
                )

        module = TrackingModule()
        await registry.register(module, auto_initialize=False)
        await registry.unregister("tracking")

        assert shutdown_called is True

    def test_get_existing(self, registry, mock_module):
        """Test obtenir contracte existent"""
        import asyncio
        asyncio.run(registry.register(mock_module, auto_initialize=False))

        registered = registry.get("mock_module")
        assert registered is not None
        assert registered.metadata.contract_id == "mock_module"

    def test_get_nonexistent(self, registry):
        """Test obtenir contracte inexistent"""
        registered = registry.get("nonexistent")
        assert registered is None

    def test_exists(self, registry, mock_module):
        """Test verificar existència"""
        import asyncio
        assert not registry.exists("mock_module")

        asyncio.run(registry.register(mock_module, auto_initialize=False))
        assert registry.exists("mock_module")

    def test_list_all(self, registry):
        """Test llistar tots els contractes"""
        import asyncio

        class MockModule1:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="module1",
                    contract_type=ContractType.MODULE,
                    name="Module 1",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        class MockModule2:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="module2",
                    contract_type=ContractType.MODULE,
                    name="Module 2",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        asyncio.run(registry.register(MockModule1(), auto_initialize=False))
        asyncio.run(registry.register(MockModule2(), auto_initialize=False))

        contracts = registry.list_all()
        assert len(contracts) == 2
        assert all(isinstance(c, RegisteredContract) for c in contracts)

    def test_list_active(self, registry):
        """Test llistar només actius"""
        import asyncio

        class ActiveModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="active",
                    contract_type=ContractType.MODULE,
                    name="Active",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        # Registrar i forçar estat ACTIVE
        module = ActiveModule()
        asyncio.run(registry.register(module, auto_initialize=False))
        # Canviar estat manualment a ACTIVE
        registered = registry.get("active")
        registered.status = ContractStatus.ACTIVE

        active = registry.list_active()
        assert len(active) == 1
        assert active[0].status == ContractStatus.ACTIVE

    def test_count(self, registry, mock_module):
        """Test comptar contractes"""
        import asyncio
        assert registry.count() == 0

        asyncio.run(registry.register(mock_module, auto_initialize=False))
        assert registry.count() == 1

    def test_clear(self, registry, mock_module):
        """Test netejar registry"""
        import asyncio
        asyncio.run(registry.register(mock_module, auto_initialize=False))
        assert registry.count() == 1

        registry.clear()
        assert registry.count() == 0

    @pytest.mark.asyncio
    async def test_initialize_contract(self, registry, mock_module):
        """Test inicialitzar contracte"""
        await registry.register(mock_module, auto_initialize=False)

        success = await registry.initialize_contract(
            "mock_module",
            context={"test": True}
        )

        assert success is True
        registered = registry.get("mock_module")
        assert registered.status == ContractStatus.INITIALIZED

    @pytest.mark.asyncio
    async def test_initialize_nonexistent(self, registry):
        """Test inicialitzar contracte inexistent"""
        success = await registry.initialize_contract("nonexistent", {})
        assert success is False

    @pytest.mark.asyncio
    async def test_health_check(self, registry, mock_module):
        """Test health check d'un contracte"""
        await registry.register(mock_module, auto_initialize=False)

        result = await registry.health_check("mock_module")
        assert result is not None
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_nonexistent(self, registry):
        """Test health check de contracte inexistent"""
        result = await registry.health_check("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_health_check_all(self, registry, mock_module):
        """Test health check de tots els contractes"""
        await registry.register(mock_module, auto_initialize=False)

        results = await registry.health_check_all()
        assert "mock_module" in results
        assert results["mock_module"].status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_all_empty(self, registry):
        """Test health check amb registry buit"""
        results = await registry.health_check_all()
        assert len(results) == 0

    def test_get_summary(self, registry, mock_module):
        """Test obtenir resum"""
        import asyncio
        asyncio.run(registry.register(mock_module, auto_initialize=True))

        summary = registry.get_summary()

        assert "total" in summary
        assert "status" in summary
        assert "contracts" in summary
        assert summary["total"] == 1
        assert summary["status"]["initialized"] == 1

    def test_get_summary_empty(self, registry):
        """Test resum amb registry buit"""
        summary = registry.get_summary()

        assert summary["total"] == 0
        assert all(count == 0 for count in summary["status"].values())

    def test_registered_contract_attributes(self, mock_module):
        """Test atributs de RegisteredContract"""
        registered = RegisteredContract(
            metadata=mock_module.metadata,
            instance=mock_module,
            status=ContractStatus.REGISTERED
        )

        assert registered.metadata.contract_id == "mock_module"
        assert registered.status == ContractStatus.REGISTERED
        assert registered.instance is mock_module
