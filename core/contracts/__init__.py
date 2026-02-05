"""
Core Contracts System for NEXE 0.9

Sistema unificat de contractes per plugins NEXE.

Suporta:
- Modules (plugins estàndard amb API, UI, CLI)

Validació multi-capa:
- Schema validation (Pydantic)
- Runtime validation (Protocol)
- Integration validation (file structure)
"""

from .base import (
    # Enums
    ContractType,
    HealthStatus,

    # Dataclasses
    ContractMetadata,
    HealthResult,

    # Protocols
    BaseContract,
    ModuleContract,

    # Validators/Helpers
    validate_contract,
    contract_is_module,
    get_contract_info,
)

from .models import (
    # Enums
    ManifestVersion,
    ContractTypeModel,

    # Sections
    ModuleSection,
    CapabilitiesSection,
    DependenciesSection,
    APISection,
    UISection,
    CLISection,
    I18nSection,
    StorageSection,
    StoragePathDeclaration,

    # Root model
    UnifiedManifest,

    # Helpers
    load_manifest_from_toml,
    validate_manifest_dict,
    manifest_to_dict,
)

from .registry import (
    # Enums
    ContractStatus,

    # Dataclasses
    RegisteredContract,

    # Registry
    ContractRegistry,
    get_contract_registry,
)

from .validators import (
    # Enums
    ValidationLevel,
    ValidationSeverity,

    # Dataclasses
    ValidationIssue,
    ValidationResult,

    # Validator
    ContractValidator,
    get_validator,
)

__version__ = "1.0.0"

__all__ = [
    # Base
    "ContractType",
    "HealthStatus",
    "ContractMetadata",
    "HealthResult",
    "BaseContract",
    "ModuleContract",
    "validate_contract",
    "contract_is_module",
    "get_contract_info",

    # Models
    "ManifestVersion",
    "ContractTypeModel",
    "ModuleSection",
    "CapabilitiesSection",
    "DependenciesSection",
    "APISection",
    "UISection",
    "CLISection",
    "I18nSection",
    "StorageSection",
    "StoragePathDeclaration",
    "UnifiedManifest",
    "load_manifest_from_toml",
    "validate_manifest_dict",
    "manifest_to_dict",

    # Registry
    "ContractStatus",
    "RegisteredContract",
    "ContractRegistry",
    "get_contract_registry",

    # Validators
    "ValidationLevel",
    "ValidationSeverity",
    "ValidationIssue",
    "ValidationResult",
    "ContractValidator",
    "get_validator",
]
