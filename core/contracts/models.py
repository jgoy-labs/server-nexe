"""
Pydantic models for NEXE manifest validation.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from pathlib import Path

from personality.i18n.resolve import t_modular

def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"core.contracts.{key}", fallback, **kwargs)

# ============================================
# ENUMS
# ============================================

class ManifestVersion(str, Enum):
    """Manifest format version."""
    V1 = "1.0"


class ContractTypeModel(str, Enum):
    """Contract type (for Pydantic)."""
    MODULE = "module"
    CORE = "core"


# ============================================
# SECTIONS
# ============================================

class ModuleSection(BaseModel):
    """[module] section - REQUIRED"""
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern=r'^\d+\.\d+\.\d+$')
    type: ContractTypeModel = ContractTypeModel.MODULE
    description: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=200)
    license: str = Field(default="AGPL-3.0")

    enabled: bool = True
    auto_start: bool = False
    priority: int = Field(default=10, ge=0, le=100)

    @field_validator('name')
    @classmethod
    def name_lowercase_no_spaces(cls, v: str) -> str:
        """Validate that name has no spaces and is lowercase."""
        import re

        # Convert to lowercase first
        v = v.lower()

        # Check no spaces
        if ' ' in v:
            raise ValueError(
                _t("name_spaces", "name cannot contain spaces")
            )

        # Check pattern
        if not re.match(r'^[a-z0-9_]+$', v):
            raise ValueError(
                _t(
                    "name_invalid_chars",
                    "name must contain only lowercase letters, numbers, and underscores"
                )
            )

        return v


class CapabilitiesSection(BaseModel):
    """[capabilities] section."""
    # Module capabilities
    has_api: bool = False
    has_ui: bool = False
    has_cli: bool = False
    has_tests: bool = False
    streaming: bool = False
    real_time: bool = False

    # Custom capabilities (extensible)
    custom: Dict[str, bool] = Field(default_factory=dict)


class DependenciesSection(BaseModel):
    """[dependencies] section."""
    modules: List[str] = Field(default_factory=list)
    optional_modules: List[str] = Field(default_factory=list)
    external_services: List[str] = Field(default_factory=list)
    python_packages: List[str] = Field(default_factory=list)


class APISection(BaseModel):
    """[api] section - Required if has_api=true."""
    enabled: bool = True
    prefix: str = Field(..., pattern=r'^/[a-z0-9/_-]*$')
    tags: List[str] = Field(default_factory=list)
    public_routes: List[str] = Field(default_factory=list)
    protected_routes: List[str] = Field(default_factory=list)
    admin_routes: List[str] = Field(default_factory=list)
    rate_limit: Optional[str] = None  # "10/minute"


class UISection(BaseModel):
    """[ui] section - Required if has_ui=true."""
    enabled: bool = True
    path: str = "ui"
    main_file: str = "index.html"
    route: Optional[str] = None
    framework: Optional[str] = "vanilla-js"
    theme_support: bool = True
    responsive: bool = True


class CLISection(BaseModel):
    """[cli] section - Required if has_cli=true."""
    enabled: bool = True
    command_name: str = Field(..., min_length=1)
    entry_point: str = Field(..., min_length=1)
    description: str = ""
    commands: List[str] = Field(default_factory=list)
    framework: str = Field(default="click")

    @field_validator('framework')
    @classmethod
    def valid_framework(cls, v: str) -> str:
        """Validate CLI framework."""
        allowed = ["click", "typer", "argparse"]
        if v not in allowed:
            raise ValueError(
                _t(
                    "framework_invalid",
                    "framework must be one of: {allowed}",
                    allowed=", ".join(allowed),
                )
            )
        return v


class I18nSection(BaseModel):
    """[i18n] section - Optional."""
    enabled: bool = False
    default_locale: str = "ca-ES"
    supported_locales: List[str] = Field(default_factory=lambda: ["ca-ES", "en-US"])
    translations_path: str = "languages/"


class StoragePathDeclaration(BaseModel):
    """Storage path declaration."""
    path: str
    type: str
    format: str = "json"
    retention_days: int = Field(default=30, ge=1)
    action: str = Field(default="DELETE")
    archive_to: Optional[str] = None


class StorageSection(BaseModel):
    """[storage] section - Optional."""
    paths: List[StoragePathDeclaration] = Field(default_factory=list)
    protected_patterns: List[str] = Field(default_factory=list)


# ============================================
# UNIFIED MANIFEST (ROOT MODEL)
# ============================================

class UnifiedManifest(BaseModel):
    """
    Root model for the unified manifest.toml.

    Supports modules (standard plugins).
    """

    manifest_version: ManifestVersion = ManifestVersion.V1

    # Obligatori
    module: ModuleSection

    # Opcional
    capabilities: CapabilitiesSection = Field(default_factory=CapabilitiesSection)
    dependencies: DependenciesSection = Field(default_factory=DependenciesSection)

    # Condicionals
    api: Optional[APISection] = None
    ui: Optional[UISection] = None
    cli: Optional[CLISection] = None
    i18n: Optional[I18nSection] = None
    storage: Optional[StorageSection] = None

    # Metadata adicional (free-form)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_conditional_sections(self) -> 'UnifiedManifest':
        """Validate conditional sections based on capabilities."""

        # Si has_api, [api] és obligatori
        if self.capabilities.has_api and self.api is None:
            raise ValueError(
                _t(
                    "api_section_required",
                    "[api] section required when capabilities.has_api = true"
                )
            )

        # Si has_ui, [ui] és obligatori
        if self.capabilities.has_ui and self.ui is None:
            raise ValueError(
                _t(
                    "ui_section_required",
                    "[ui] section required when capabilities.has_ui = true"
                )
            )

        # Si has_cli, [cli] és obligatori
        if self.capabilities.has_cli and self.cli is None:
            raise ValueError(
                _t(
                    "cli_section_required",
                    "[cli] section required when capabilities.has_cli = true"
                )
            )

        return self

    @model_validator(mode='after')
    def validate_api_prefix(self) -> 'UnifiedManifest':
        """Validate that api.prefix is valid."""
        if self.api:
            # Just check it starts with /
            if not self.api.prefix.startswith("/"):
                raise ValueError(
                    _t(
                        "api_prefix_invalid",
                        "api.prefix must start with /, got: {prefix}",
                        prefix=self.api.prefix,
                    )
                )
        return self

    def to_contract_metadata(self) -> 'ContractMetadata':
        """Convert UnifiedManifest to ContractMetadata."""
        from .base import ContractMetadata, ContractType

        return ContractMetadata(
            contract_id=self.module.name,
            contract_type=ContractType(self.module.type.value),
            contract_version=self.manifest_version.value,
            name=self.module.name,
            version=self.module.version,
            description=self.module.description,
            author=self.module.author,
            license=self.module.license,
            capabilities=self.capabilities.model_dump(),
            dependencies=self.dependencies.modules,
            optional_dependencies=self.dependencies.optional_modules,
            tags=self.api.tags if self.api else []
        )


# ============================================
# HELPER FUNCTIONS
# ============================================

def load_manifest_from_toml(toml_path: str) -> UnifiedManifest:
    """
    Load and validate a manifest.toml.

    Args:
        toml_path: Path to the manifest.toml file

    Returns:
        Validated UnifiedManifest

    Raises:
        ValidationError: If the manifest does not match the schema
        FileNotFoundError: If the file does not exist
    """
    import toml

    path = Path(toml_path)
    if not path.exists():
        raise FileNotFoundError(
            _t(
                "manifest_not_found",
                "Manifest not found: {path}",
                path=toml_path,
            )
        )

    with open(path, 'r', encoding='utf-8') as f:
        data = toml.load(f)

    return UnifiedManifest(**data)


def validate_manifest_dict(data: Dict[str, Any]) -> UnifiedManifest:
    """
    Validate a dictionary as a manifest.

    Args:
        data: Dictionary with manifest data

    Returns:
        Validated UnifiedManifest
    """
    return UnifiedManifest(**data)


def manifest_to_dict(manifest: UnifiedManifest) -> Dict[str, Any]:
    """
    Convert UnifiedManifest to a dictionary.

    Args:
        manifest: UnifiedManifest to convert

    Returns:
        Dictionary with manifest data
    """
    return manifest.model_dump(exclude_none=True)
