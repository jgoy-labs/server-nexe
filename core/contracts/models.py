"""
Pydantic models per validació de manifests NEXE.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from pathlib import Path


# ============================================
# ENUMS
# ============================================

class ManifestVersion(str, Enum):
    """Versió del format de manifest"""
    V1 = "1.0"


class ContractTypeModel(str, Enum):
    """Tipus de contracte (per Pydantic)"""
    MODULE = "module"
    CORE = "core"


# ============================================
# SECTIONS
# ============================================

class ModuleSection(BaseModel):
    """[module] section - OBLIGATORI"""
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
        """Valida que name no tingui espais i sigui lowercase"""
        import re

        # Convert to lowercase first
        v = v.lower()

        # Check no spaces
        if ' ' in v:
            raise ValueError("name cannot contain spaces")

        # Check pattern
        if not re.match(r'^[a-z0-9_]+$', v):
            raise ValueError("name must contain only lowercase letters, numbers, and underscores")

        return v


class CapabilitiesSection(BaseModel):
    """[capabilities] section"""
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
    """[dependencies] section"""
    modules: List[str] = Field(default_factory=list)
    optional_modules: List[str] = Field(default_factory=list)
    external_services: List[str] = Field(default_factory=list)
    python_packages: List[str] = Field(default_factory=list)


class APISection(BaseModel):
    """[api] section - Obligatori si has_api=true"""
    enabled: bool = True
    prefix: str = Field(..., pattern=r'^/[a-z0-9/_-]*$')
    tags: List[str] = Field(default_factory=list)
    public_routes: List[str] = Field(default_factory=list)
    protected_routes: List[str] = Field(default_factory=list)
    admin_routes: List[str] = Field(default_factory=list)
    rate_limit: Optional[str] = None  # "10/minute"


class UISection(BaseModel):
    """[ui] section - Obligatori si has_ui=true"""
    enabled: bool = True
    path: str = "ui"
    main_file: str = "index.html"
    route: Optional[str] = None
    framework: Optional[str] = "vanilla-js"
    theme_support: bool = True
    responsive: bool = True


class CLISection(BaseModel):
    """[cli] section - Obligatori si has_cli=true"""
    enabled: bool = True
    command_name: str = Field(..., min_length=1)
    entry_point: str = Field(..., min_length=1)
    description: str = ""
    commands: List[str] = Field(default_factory=list)
    framework: str = Field(default="click")

    @field_validator('framework')
    @classmethod
    def valid_framework(cls, v: str) -> str:
        """Valida framework CLI"""
        allowed = ["click", "typer", "argparse"]
        if v not in allowed:
            raise ValueError(f"framework must be one of: {allowed}")
        return v


class I18nSection(BaseModel):
    """[i18n] section - Opcional"""
    enabled: bool = False
    default_locale: str = "ca-ES"
    supported_locales: List[str] = Field(default_factory=lambda: ["ca-ES", "en-US"])
    translations_path: str = "languages/"


class StoragePathDeclaration(BaseModel):
    """Declaració de path d'emmagatzematge"""
    path: str
    type: str
    format: str = "json"
    retention_days: int = Field(default=30, ge=1)
    action: str = Field(default="DELETE")
    archive_to: Optional[str] = None


class StorageSection(BaseModel):
    """[storage] section - Opcional"""
    paths: List[StoragePathDeclaration] = Field(default_factory=list)
    protected_patterns: List[str] = Field(default_factory=list)


# ============================================
# UNIFIED MANIFEST (ROOT MODEL)
# ============================================

class UnifiedManifest(BaseModel):
    """
    Root model per manifest.toml unificat.

    Suporta modules (plugins estàndard).
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
        """Valida seccions condicionals segons capabilities"""

        # Si has_api, [api] és obligatori
        if self.capabilities.has_api and self.api is None:
            raise ValueError("[api] section required when capabilities.has_api = true")

        # Si has_ui, [ui] és obligatori
        if self.capabilities.has_ui and self.ui is None:
            raise ValueError("[ui] section required when capabilities.has_ui = true")

        # Si has_cli, [cli] és obligatori
        if self.capabilities.has_cli and self.cli is None:
            raise ValueError("[cli] section required when capabilities.has_cli = true")

        return self

    @model_validator(mode='after')
    def validate_api_prefix(self) -> 'UnifiedManifest':
        """Valida que api.prefix és vàlid"""
        if self.api:
            # Just check it starts with /
            if not self.api.prefix.startswith("/"):
                raise ValueError(f"api.prefix must start with /, got: {self.api.prefix}")
        return self

    def to_contract_metadata(self) -> 'ContractMetadata':
        """Converteix UnifiedManifest a ContractMetadata"""
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
    Carrega i valida un manifest.toml.

    Args:
        toml_path: Path al fitxer manifest.toml

    Returns:
        UnifiedManifest validat

    Raises:
        ValidationError: Si el manifest no compleix l'schema
        FileNotFoundError: Si el fitxer no existeix
    """
    import toml

    path = Path(toml_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {toml_path}")

    with open(path, 'r', encoding='utf-8') as f:
        data = toml.load(f)

    return UnifiedManifest(**data)


def validate_manifest_dict(data: Dict[str, Any]) -> UnifiedManifest:
    """
    Valida un diccionari com a manifest.

    Args:
        data: Diccionari amb dades del manifest

    Returns:
        UnifiedManifest validat
    """
    return UnifiedManifest(**data)


def manifest_to_dict(manifest: UnifiedManifest) -> Dict[str, Any]:
    """
    Converteix UnifiedManifest a diccionari.

    Args:
        manifest: UnifiedManifest a convertir

    Returns:
        Diccionari amb dades del manifest
    """
    return manifest.model_dump(exclude_none=True)
