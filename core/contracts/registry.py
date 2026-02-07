"""
Unified registry for NEXE contracts.
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import threading
import asyncio

from .base import BaseContract, ContractMetadata, HealthResult, HealthStatus


# ============================================
# ENUMS
# ============================================

class ContractStatus(str, Enum):
    """Contract status in the registry."""
    REGISTERED = "registered"
    INITIALIZED = "initialized"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"


# ============================================
# DATACLASSES
# ============================================

@dataclass
class RegisteredContract:
    """Registered contract."""
    metadata: ContractMetadata
    instance: BaseContract
    status: ContractStatus = ContractStatus.REGISTERED
    registered_at: datetime = field(default_factory=datetime.now)
    initialized_at: Optional[datetime] = None
    last_health_check: Optional[HealthResult] = None
    last_health_check_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert to a dictionary."""
        return {
            "metadata": self.metadata.to_dict(),
            "status": self.status.value,
            "registered_at": self.registered_at.isoformat(),
            "initialized_at": self.initialized_at.isoformat() if self.initialized_at else None,
            "last_health_check": self.last_health_check.to_dict() if self.last_health_check else None,
            "last_health_check_at": self.last_health_check_at.isoformat() if self.last_health_check_at else None
        }


# ============================================
# CONTRACT REGISTRY (SINGLETON)
# ============================================

class ContractRegistry:
    """
    Central registry for all contracts.

    Thread-safe singleton pattern.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._contracts: Dict[str, RegisteredContract] = {}
        self._lock_instance = threading.Lock()
        self._initialized = True

    # ============================================
    # REGISTRATION
    # ============================================

    async def register(
        self,
        contract: BaseContract,
        auto_initialize: bool = False,
        context: Optional[Dict] = None
    ) -> bool:
        """
        Register a contract.

        Args:
            contract: Contract to register
            auto_initialize: If True, auto-initialize
            context: Initialization context

        Returns:
            True if registered successfully
        """
        meta = contract.metadata
        contract_id = meta.contract_id

        with self._lock_instance:
            if contract_id in self._contracts:
                # Ja existeix
                return False

            registered = RegisteredContract(
                metadata=meta,
                instance=contract,
                status=ContractStatus.REGISTERED
            )

            self._contracts[contract_id] = registered

        # Auto-initialize si cal
        if auto_initialize:
            ctx = context or {}
            await self.initialize_contract(contract_id, ctx)

        return True

    async def unregister(self, contract_id: str) -> bool:
        """
        Unregister a contract.

        Args:
            contract_id: Contract ID

        Returns:
            True if unregistered successfully
        """
        with self._lock_instance:
            if contract_id not in self._contracts:
                return False

            registered = self._contracts[contract_id]

            # Shutdown graceful
            try:
                await registered.instance.shutdown()
            except Exception:
                pass

            del self._contracts[contract_id]
            return True

    # ============================================
    # QUERIES
    # ============================================

    def get(self, contract_id: str) -> Optional[RegisteredContract]:
        """
        Get a registered contract.

        Args:
            contract_id: Contract ID

        Returns:
            RegisteredContract or None
        """
        return self._contracts.get(contract_id)

    def get_instance(self, contract_id: str) -> Optional[BaseContract]:
        """
        Get a contract instance.

        Args:
            contract_id: Contract ID

        Returns:
            BaseContract or None
        """
        registered = self.get(contract_id)
        return registered.instance if registered else None

    def list_all(self) -> List[RegisteredContract]:
        """
        List all registered contracts.

        Returns:
            List of RegisteredContract
        """
        return list(self._contracts.values())

    def list_by_status(self, status: ContractStatus) -> List[RegisteredContract]:
        """
        List contracts by status.

        Args:
            status: Status to filter by

        Returns:
            List of contracts with this status
        """
        return [
            rc for rc in self._contracts.values()
            if rc.status == status
        ]

    def list_active(self) -> List[RegisteredContract]:
        """
        List active contracts.

        Returns:
            List of active contracts
        """
        return self.list_by_status(ContractStatus.ACTIVE)

    def exists(self, contract_id: str) -> bool:
        """
        Check whether a contract exists.

        Args:
            contract_id: Contract ID

        Returns:
            True if it exists
        """
        return contract_id in self._contracts

    def count(self) -> int:
        """
        Return the number of registered contracts.

        Returns:
            Number of contracts
        """
        return len(self._contracts)

    # ============================================
    # LIFECYCLE
    # ============================================

    async def initialize_contract(
        self,
        contract_id: str,
        context: Dict
    ) -> bool:
        """
        Initialize a contract.

        Args:
            contract_id: Contract ID
            context: Initialization context

        Returns:
            True if initialized successfully
        """
        registered = self.get(contract_id)
        if not registered:
            return False

        try:
            success = await registered.instance.initialize(context)

            if success:
                with self._lock_instance:
                    registered.status = ContractStatus.INITIALIZED
                    registered.initialized_at = datetime.now()

            return success

        except Exception as e:
            with self._lock_instance:
                registered.status = ContractStatus.FAILED
            return False

    async def activate_contract(self, contract_id: str) -> bool:
        """
        Activate a contract.

        Args:
            contract_id: Contract ID

        Returns:
            True if activated successfully
        """
        registered = self.get(contract_id)
        if not registered:
            return False

        if registered.status != ContractStatus.INITIALIZED:
            return False

        with self._lock_instance:
            registered.status = ContractStatus.ACTIVE

        return True

    async def deactivate_contract(self, contract_id: str) -> bool:
        """
        Deactivate a contract.

        Args:
            contract_id: Contract ID

        Returns:
            True if deactivated successfully
        """
        registered = self.get(contract_id)
        if not registered:
            return False

        with self._lock_instance:
            registered.status = ContractStatus.INACTIVE

        return True

    # ============================================
    # HEALTH CHECKS
    # ============================================

    async def health_check(self, contract_id: str) -> Optional[HealthResult]:
        """
        Run a health check for a contract.

        Args:
            contract_id: Contract ID

        Returns:
            HealthResult or None
        """
        registered = self.get(contract_id)
        if not registered:
            return None

        try:
            result = await registered.instance.health_check()

            with self._lock_instance:
                registered.last_health_check = result
                registered.last_health_check_at = datetime.now()

            return result

        except Exception as e:
            result = HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )

            with self._lock_instance:
                registered.last_health_check = result
                registered.last_health_check_at = datetime.now()

            return result

    async def health_check_all(self) -> Dict[str, HealthResult]:
        """
        Run health checks for all contracts.

        Returns:
            Dictionary {contract_id: HealthResult}
        """
        results = {}

        for contract_id in self._contracts.keys():
            result = await self.health_check(contract_id)
            if result:
                results[contract_id] = result

        return results

    # ============================================
    # UTILS
    # ============================================

    def get_summary(self) -> Dict:
        """
        Get a summary of the registry.

        Returns:
            Summary dictionary
        """
        status_counts = {}
        for status in ContractStatus:
            status_counts[status.value] = len(self.list_by_status(status))

        return {
            "total": self.count(),
            "status": status_counts,
            "contracts": [
                {
                    "id": rc.metadata.contract_id,
                    "name": rc.metadata.name,
                    "type": rc.metadata.contract_type.value,
                    "version": rc.metadata.version,
                    "status": rc.status.value
                }
                for rc in self.list_all()
            ]
        }

    def clear(self) -> None:
        """
        Clear the registry (for testing).

        WARNING: This removes all registered contracts!
        """
        with self._lock_instance:
            self._contracts.clear()


# ============================================
# SINGLETON GETTER
# ============================================

_registry_instance: Optional[ContractRegistry] = None


def get_contract_registry() -> ContractRegistry:
    """
    Get the singleton registry instance.

    Returns:
        ContractRegistry singleton
    """
    global _registry_instance

    if _registry_instance is None:
        _registry_instance = ContractRegistry()

    return _registry_instance
