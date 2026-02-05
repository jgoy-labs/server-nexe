"""
Bridge between ModuleManager and ContractRegistry.

Integra el nou sistema de contractes amb el ModuleManager existent
sense modificar l'arquitectura actual.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

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


class ModuleContractAdapter:
    """
    Adapta un mòdul NEXE carregat per implementar BaseContract.

    Permet que mòduls existents treballin amb el nou sistema de contractes.
    """

    def __init__(self, module_instance: Any, manifest: UnifiedManifest, module_path: Path):
        """
        Args:
            module_instance: Instància del mòdul carregat
            manifest: UnifiedManifest del mòdul
            module_path: Path al directori del mòdul
        """
        self._instance = module_instance
        self._manifest = manifest
        self._path = module_path
        self._metadata = manifest.to_contract_metadata()

    @property
    def metadata(self) -> ContractMetadata:
        """Retorna metadata del contracte"""
        return self._metadata

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Inicialitza el mòdul"""
        try:
            # Si el mòdul té initialize, cridar-lo
            if hasattr(self._instance, 'initialize'):
                if callable(getattr(self._instance, 'initialize')):
                    result = self._instance.initialize(context)
                    # Handle both sync and async
                    if hasattr(result, '__await__'):
                        return await result
                    return bool(result)
            return True
        except Exception as e:
            logger.error(f"Failed to initialize {self._metadata.contract_id}: {e}")
            return False

    async def shutdown(self) -> None:
        """Shutdown del mòdul"""
        try:
            if hasattr(self._instance, 'shutdown'):
                if callable(getattr(self._instance, 'shutdown')):
                    result = self._instance.shutdown()
                    if hasattr(result, '__await__'):
                        await result
        except Exception as e:
            logger.warning(f"Error during shutdown of {self._metadata.contract_id}: {e}")

    async def health_check(self) -> HealthResult:
        """Health check del mòdul"""
        try:
            # Si el mòdul té health_check, usar-lo
            if hasattr(self._instance, 'health_check'):
                if callable(getattr(self._instance, 'health_check')):
                    result = self._instance.health_check()
                    if hasattr(result, '__await__'):
                        return await result
                    return result

            # Default: assumir healthy si està carregat
            return HealthResult(
                status=HealthStatus.HEALTHY,
                message="Module loaded and operational"
            )
        except Exception as e:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )

    def get_router(self) -> Optional[Any]:
        """Retorna router del mòdul (si n'hi ha)"""
        if hasattr(self._instance, 'get_router'):
            return self._instance.get_router()
        if hasattr(self._instance, 'router'):
            return self._instance.router
        return None

    def get_router_prefix(self) -> str:
        """Retorna prefix del router"""
        if self._manifest.api:
            return self._manifest.api.prefix
        return f"/{self._metadata.contract_id}"


class ContractBridge:
    """
    Bridge entre ModuleManager i ContractRegistry.

    Registra automàticament mòduls carregats al ContractRegistry.
    """

    def __init__(self):
        """Inicialitza el bridge"""
        self._registry = get_contract_registry()
        self._adapters: Dict[str, ModuleContractAdapter] = {}

    async def register_module(
        self,
        module_name: str,
        module_instance: Any,
        module_path: Path
    ) -> bool:
        """
        Registra un mòdul al ContractRegistry.

        Args:
            module_name: Nom del mòdul
            module_instance: Instància del mòdul carregat
            module_path: Path al directori del mòdul

        Returns:
            True si registrat correctament
        """
        try:
            # Carregar manifest
            manifest_path = module_path / "manifest.toml"
            if not manifest_path.exists():
                logger.warning(f"No manifest found for {module_name} at {manifest_path}")
                return False

            manifest = load_manifest_from_toml(str(manifest_path))

            # Crear adapter
            adapter = ModuleContractAdapter(module_instance, manifest, module_path)

            # Registrar al ContractRegistry
            success = await self._registry.register(
                adapter,
                auto_initialize=False  # ModuleManager ja inicialitza
            )

            if success:
                self._adapters[module_name] = adapter
                logger.info(f"✓ Registered {module_name} to ContractRegistry")

            return success

        except Exception as e:
            logger.error(f"Failed to register {module_name}: {e}")
            return False

    async def unregister_module(self, module_name: str) -> bool:
        """
        Desregistra un mòdul del ContractRegistry.

        Args:
            module_name: Nom del mòdul

        Returns:
            True si desregistrat correctament
        """
        try:
            if module_name in self._adapters:
                success = await self._registry.unregister(module_name)
                if success:
                    del self._adapters[module_name]
                    logger.info(f"✓ Unregistered {module_name} from ContractRegistry")
                return success
            return False
        except Exception as e:
            logger.error(f"Failed to unregister {module_name}: {e}")
            return False

    def get_adapter(self, module_name: str) -> Optional[ModuleContractAdapter]:
        """
        Obté l'adapter d'un mòdul.

        Args:
            module_name: Nom del mòdul

        Returns:
            ModuleContractAdapter o None
        """
        return self._adapters.get(module_name)

    async def health_check_all(self) -> Dict[str, HealthResult]:
        """
        Executa health check de tots els mòduls registrats.

        Returns:
            Diccionari {module_name: HealthResult}
        """
        return await self._registry.health_check_all()

    def get_registry_summary(self) -> Dict[str, Any]:
        """
        Obté resum del registry.

        Returns:
            Diccionari amb resum
        """
        return self._registry.get_summary()


# Singleton instance
_bridge_instance: Optional[ContractBridge] = None


def get_contract_bridge() -> ContractBridge:
    """
    Obté la instància singleton del ContractBridge.

    Returns:
        ContractBridge singleton
    """
    global _bridge_instance

    if _bridge_instance is None:
        _bridge_instance = ContractBridge()

    return _bridge_instance
