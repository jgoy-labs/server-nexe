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

    @pytest.mark.asyncio
    async def test_register_failed_initialization(self, registry):
        """Test registre amb inicialització que falla completament"""
        class FailedInitModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="failed_init",
                    contract_type=ContractType.MODULE,
                    name="Failed Init",
                    version="1.0.0"
                )

            async def initialize(self, context):
                raise Exception("Initialization error")

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.UNHEALTHY, message="Failed")

        module = FailedInitModule()
        # Registrar amb auto_initialize - fallarà però es registrarà
        await registry.register(module, auto_initialize=True)

        # Ha de estar registrat però no initialized
        assert registry.exists("failed_init")

    @pytest.mark.asyncio
    async def test_health_check_with_error(self, registry):
        """Test health check d'un mòdul que llança excepció"""
        class ErrorModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="error_module",
                    contract_type=ContractType.MODULE,
                    name="Error",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                raise Exception("Health check error")

        await registry.register(ErrorModule(), auto_initialize=False)

        # Health check ha de retornar resultat amb error
        result = await registry.health_check("error_module")
        assert result is not None

    @pytest.mark.asyncio
    async def test_unregister_with_shutdown_error(self, registry):
        """Test desregistrar quan shutdown falla"""
        class ErrorShutdownModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="error_shutdown",
                    contract_type=ContractType.MODULE,
                    name="Error Shutdown",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                raise Exception("Shutdown error")

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        await registry.register(ErrorShutdownModule(), auto_initialize=False)

        # Unregister ha de funcionar tot i l'error en shutdown
        success = await registry.unregister("error_shutdown")
        assert success is True
        assert not registry.exists("error_shutdown")

    def test_list_by_status_registered(self, registry):
        """Test llistar per status REGISTERED"""
        import asyncio

        class RegisteredModule:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="registered_only",
                    contract_type=ContractType.MODULE,
                    name="Registered",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        asyncio.run(registry.register(RegisteredModule(), auto_initialize=False))

        registered = registry.list_by_status(ContractStatus.REGISTERED)
        assert len(registered) == 1

    def test_list_by_status_failed(self, registry):
        """Test llistar per status FAILED"""
        import asyncio

        class Module:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="will_fail",
                    contract_type=ContractType.MODULE,
                    name="Will Fail",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        asyncio.run(registry.register(Module(), auto_initialize=False))

        # Canviar estat a FAILED
        registered = registry.get("will_fail")
        registered.status = ContractStatus.FAILED

        failed = registry.list_by_status(ContractStatus.FAILED)
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_multiple_health_checks(self, registry, mock_module):
        """Test múltiples health checks consecutius"""
        await registry.register(mock_module, auto_initialize=False)

        # Primer health check
        result1 = await registry.health_check("mock_module")
        assert result1 is not None

        # Segon health check
        result2 = await registry.health_check("mock_module")
        assert result2 is not None

        # Ha de guardar last_health_check
        registered = registry.get("mock_module")
        assert registered.last_health_check is not None

    def test_get_summary_with_multiple_statuses(self, registry):
        """Test get_summary amb múltiples statuses"""
        import asyncio

        class Module1:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="m1",
                    contract_type=ContractType.MODULE,
                    name="M1",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        class Module2:
            @property
            def metadata(self):
                return ContractMetadata(
                    contract_id="m2",
                    contract_type=ContractType.MODULE,
                    name="M2",
                    version="1.0.0"
                )

            async def initialize(self, context):
                return True

            async def shutdown(self):
                pass

            async def health_check(self):
                return HealthResult(status=HealthStatus.HEALTHY, message="OK")

        # Registrar dos mòduls
        asyncio.run(registry.register(Module1(), auto_initialize=False))
        asyncio.run(registry.register(Module2(), auto_initialize=True))

        summary = registry.get_summary()

        assert summary["total"] == 2
        assert summary["status"]["registered"] >= 1  # M1
        assert summary["status"]["initialized"] >= 1  # M2

    @pytest.mark.asyncio
    async def test_activate_contract(self, registry, mock_module):
        """Test activar un contracte"""
        await registry.register(mock_module, auto_initialize=True)

        # Ara està INITIALIZED, activem
        success = await registry.activate_contract("mock_module")

        assert success is True
        registered = registry.get("mock_module")
        assert registered.status == ContractStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_activate_nonexistent_contract(self, registry):
        """Test activar contracte inexistent"""
        success = await registry.activate_contract("nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_activate_not_initialized_contract(self, registry, mock_module):
        """Test activar contracte no initialized"""
        await registry.register(mock_module, auto_initialize=False)

        # Està REGISTERED, no INITIALIZED
        success = await registry.activate_contract("mock_module")

        # No es pot activar si no està initialized
        assert success is False

    @pytest.mark.asyncio
    async def test_deactivate_contract(self, registry, mock_module):
        """Test desactivar un contracte"""
        await registry.register(mock_module, auto_initialize=True)

        # Activar primer
        await registry.activate_contract("mock_module")

        # Ara desactivar
        success = await registry.deactivate_contract("mock_module")

        assert success is True
        registered = registry.get("mock_module")
        assert registered.status == ContractStatus.INACTIVE

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_contract(self, registry):
        """Test desactivar contracte inexistent"""
        success = await registry.deactivate_contract("nonexistent")
        assert success is False
