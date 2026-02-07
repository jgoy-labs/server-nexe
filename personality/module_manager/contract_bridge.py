"""
Bridge between ModuleManager and ContractRegistry.

Integrates the new contracts system with the existing ModuleManager
without changing the current architecture.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

from personality.i18n.resolve import t_modular

from core.contracts import (
    ContractRegistry,
    get_contract_registry,
    load_manifest_from_toml,
    UnifiedManifest,
    BaseContract,
    ContractMetadata,
    HealthResult,
    HealthStatus
)

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"module_manager.contract_bridge.{key}", fallback, **kwargs)


class ModuleContractAdapter:
    """
    Adapt a loaded NEXE module to implement BaseContract.

    Allows existing modules to work with the new contracts system.
    """

    def __init__(self, module_instance: Any, manifest: UnifiedManifest, module_path: Path):
        """
        Args:
            module_instance: Loaded module instance
            manifest: Module UnifiedManifest
            module_path: Path to the module directory
        """
        self._instance = module_instance
        self._manifest = manifest
        self._path = module_path
        self._metadata = manifest.to_contract_metadata()

    @property
    def metadata(self) -> ContractMetadata:
        """Return contract metadata."""
        return self._metadata

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize the module."""
        try:
            # If the module has initialize, call it
            if hasattr(self._instance, 'initialize'):
                if callable(getattr(self._instance, 'initialize')):
                    result = self._instance.initialize(context)
                    # Handle both sync and async
                    if hasattr(result, '__await__'):
                        return await result
                    return bool(result)
            return True
        except Exception as e:
            logger.error(
                _t(
                    "initialize_failed",
                    "Failed to initialize {contract_id}: {error}",
                    contract_id=self._metadata.contract_id,
                    error=str(e),
                )
            )
            return False

    async def shutdown(self) -> None:
        """Shutdown the module."""
        try:
            if hasattr(self._instance, 'shutdown'):
                if callable(getattr(self._instance, 'shutdown')):
                    result = self._instance.shutdown()
                    if hasattr(result, '__await__'):
                        await result
        except Exception as e:
            logger.warning(
                _t(
                    "shutdown_failed",
                    "Error during shutdown of {contract_id}: {error}",
                    contract_id=self._metadata.contract_id,
                    error=str(e),
                )
            )

    async def health_check(self) -> HealthResult:
        """Module health check."""
        try:
            # If the module has health_check, use it
            if hasattr(self._instance, 'health_check'):
                if callable(getattr(self._instance, 'health_check')):
                    result = self._instance.health_check()
                    if hasattr(result, '__await__'):
                        return await result
                    return result

            # Default: assume healthy if it is loaded
            return HealthResult(
                status=HealthStatus.HEALTHY,
                message=_t(
                    "health_ok",
                    "Module loaded and operational"
                )
            )
        except Exception as e:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=_t(
                    "health_failed",
                    "Health check failed: {error}",
                    error=str(e),
                )
            )

    def get_router(self) -> Optional[Any]:
        """Return the module router (if any)."""
        if hasattr(self._instance, 'get_router'):
            return self._instance.get_router()
        if hasattr(self._instance, 'router'):
            return self._instance.router
        return None

    def get_router_prefix(self) -> str:
        """Return router prefix."""
        if self._manifest.api:
            return self._manifest.api.prefix
        return f"/{self._metadata.contract_id}"


class ContractBridge:
    """
    Bridge between ModuleManager and ContractRegistry.

    Automatically registers loaded modules in the ContractRegistry.
    """

    def __init__(self):
        """Initialize the bridge."""
        self._registry = get_contract_registry()
        self._adapters: Dict[str, ModuleContractAdapter] = {}

    async def register_module(
        self,
        module_name: str,
        module_instance: Any,
        module_path: Path
    ) -> bool:
        """
        Register a module in the ContractRegistry.

        Args:
            module_name: Module name
            module_instance: Loaded module instance
            module_path: Path to the module directory

        Returns:
            True if registered successfully
        """
        try:
            # Load manifest
            manifest_path = module_path / "manifest.toml"
            if not manifest_path.exists():
                logger.warning(
                    _t(
                        "manifest_missing",
                        "No manifest found for {module} at {path}",
                        module=module_name,
                        path=manifest_path,
                    )
                )
                return False

            manifest = load_manifest_from_toml(str(manifest_path))

            # Create adapter
            adapter = ModuleContractAdapter(module_instance, manifest, module_path)

            # Register in ContractRegistry
            success = await self._registry.register(
                adapter,
                auto_initialize=False  # ModuleManager already initializes
            )

            if success:
                self._adapters[module_name] = adapter
                logger.info(
                    _t(
                        "registered",
                        "✓ Registered {module} to ContractRegistry",
                        module=module_name,
                    )
                )

            return success

        except Exception as e:
            logger.error(
                _t(
                    "register_failed",
                    "Failed to register {module}: {error}",
                    module=module_name,
                    error=str(e),
                )
            )
            return False

    async def unregister_module(self, module_name: str) -> bool:
        """
        Unregister a module from the ContractRegistry.

        Args:
            module_name: Module name

        Returns:
            True if unregistered successfully
        """
        try:
            if module_name in self._adapters:
                success = await self._registry.unregister(module_name)
                if success:
                    del self._adapters[module_name]
                    logger.info(
                        _t(
                            "unregistered",
                            "✓ Unregistered {module} from ContractRegistry",
                            module=module_name,
                        )
                    )
                return success
            return False
        except Exception as e:
            logger.error(
                _t(
                    "unregister_failed",
                    "Failed to unregister {module}: {error}",
                    module=module_name,
                    error=str(e),
                )
            )
            return False

    def get_adapter(self, module_name: str) -> Optional[ModuleContractAdapter]:
        """
        Get the adapter for a module.

        Args:
            module_name: Module name

        Returns:
            ModuleContractAdapter or None
        """
        return self._adapters.get(module_name)

    async def health_check_all(self) -> Dict[str, HealthResult]:
        """
        Run health checks for all registered modules.

        Returns:
            Dictionary {module_name: HealthResult}
        """
        return await self._registry.health_check_all()

    def get_registry_summary(self) -> Dict[str, Any]:
        """
        Get registry summary.

        Returns:
            Summary dictionary
        """
        return self._registry.get_summary()


# Singleton instance
_bridge_instance: Optional[ContractBridge] = None


def get_contract_bridge() -> ContractBridge:
    """
    Get the singleton ContractBridge instance.

    Returns:
        ContractBridge singleton
    """
    global _bridge_instance

    if _bridge_instance is None:
        _bridge_instance = ContractBridge()

    return _bridge_instance
