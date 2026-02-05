"""
Validators per contractes NEXE.

Validació multi-capa:
1. Schema validation (Pydantic)
2. Runtime validation (Protocol)
3. Integration validation (file structure)
"""

from typing import List, Optional, Any
from dataclasses import dataclass
from pathlib import Path
from enum import Enum

from .base import BaseContract, ModuleContract, validate_contract, contract_is_module
from .models import load_manifest_from_toml, UnifiedManifest


# ============================================
# ENUMS
# ============================================

class ValidationLevel(str, Enum):
    """Nivell de validació"""
    SCHEMA = "schema"
    RUNTIME = "runtime"
    INTEGRATION = "integration"


class ValidationSeverity(str, Enum):
    """Severitat d'un error de validació"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============================================
# DATACLASSES
# ============================================

@dataclass
class ValidationIssue:
    """Issue de validació"""
    level: ValidationLevel
    severity: ValidationSeverity
    message: str
    details: Optional[str] = None


@dataclass
class ValidationResult:
    """Resultat de validació"""
    valid: bool
    issues: List[ValidationIssue]
    contract_id: Optional[str] = None

    def has_errors(self) -> bool:
        """Check si té errors"""
        return any(
            issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            for issue in self.issues
        )

    def has_warnings(self) -> bool:
        """Check si té warnings"""
        return any(
            issue.severity == ValidationSeverity.WARNING
            for issue in self.issues
        )

    def get_errors(self) -> List[ValidationIssue]:
        """Obté només errors"""
        return [
            issue for issue in self.issues
            if issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
        ]

    def get_warnings(self) -> List[ValidationIssue]:
        """Obté només warnings"""
        return [
            issue for issue in self.issues
            if issue.severity == ValidationSeverity.WARNING
        ]

    def to_dict(self) -> dict:
        """Converteix a diccionari"""
        return {
            "valid": self.valid,
            "contract_id": self.contract_id,
            "issues": [
                {
                    "level": issue.level.value,
                    "severity": issue.severity.value,
                    "message": issue.message,
                    "details": issue.details
                }
                for issue in self.issues
            ]
        }


# ============================================
# CONTRACT VALIDATOR
# ============================================

class ContractValidator:
    """
    Validator unificat per contractes.

    Implementa validació en múltiples capes.
    """

    def validate_manifest_schema(self, manifest_path: Path) -> ValidationResult:
        """
        Valida l'schema del manifest amb Pydantic.

        Args:
            manifest_path: Path al manifest.toml

        Returns:
            ValidationResult
        """
        issues = []

        # Check existència
        if not manifest_path.exists():
            issues.append(ValidationIssue(
                level=ValidationLevel.SCHEMA,
                severity=ValidationSeverity.CRITICAL,
                message=f"Manifest file not found: {manifest_path}"
            ))
            return ValidationResult(valid=False, issues=issues)

        # Try load + validate
        try:
            manifest = load_manifest_from_toml(str(manifest_path))
            contract_id = manifest.module.name

            # Validació OK
            return ValidationResult(
                valid=True,
                issues=issues,
                contract_id=contract_id
            )

        except Exception as e:
            issues.append(ValidationIssue(
                level=ValidationLevel.SCHEMA,
                severity=ValidationSeverity.ERROR,
                message="Manifest schema validation failed",
                details=str(e)
            ))
            return ValidationResult(valid=False, issues=issues)

    def validate_contract_runtime(self, contract: Any) -> ValidationResult:
        """
        Valida que un objecte implementa BaseContract (runtime).

        Args:
            contract: Objecte a validar

        Returns:
            ValidationResult
        """
        issues = []

        # Check BaseContract
        if not validate_contract(contract):
            issues.append(ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.CRITICAL,
                message="Object does not implement BaseContract protocol"
            ))
            return ValidationResult(valid=False, issues=issues)

        # Check metadata
        try:
            meta = contract.metadata
            contract_id = meta.contract_id
        except Exception as e:
            issues.append(ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.ERROR,
                message="Failed to access contract metadata",
                details=str(e)
            ))
            return ValidationResult(valid=False, issues=issues)

        # Check ModuleContract si és module
        if meta.is_module() and not contract_is_module(contract):
            issues.append(ValidationIssue(
                level=ValidationLevel.RUNTIME,
                severity=ValidationSeverity.WARNING,
                message="Module does not fully implement ModuleContract"
            ))

        return ValidationResult(
            valid=True,
            issues=issues,
            contract_id=contract_id
        )

    def validate_file_structure(
        self,
        contract_path: Path,
        manifest: UnifiedManifest
    ) -> ValidationResult:
        """
        Valida estructura de fitxers del contracte.

        Args:
            contract_path: Path al directori del contracte
            manifest: Manifest carregat

        Returns:
            ValidationResult
        """
        issues = []
        contract_id = manifest.module.name

        # Check __init__.py
        init_file = contract_path / "__init__.py"
        if not init_file.exists():
            issues.append(ValidationIssue(
                level=ValidationLevel.INTEGRATION,
                severity=ValidationSeverity.WARNING,
                message="Missing __init__.py"
            ))

        # Check module.py si has_api
        if manifest.capabilities.has_api:
            module_file = contract_path / "module.py"
            if not module_file.exists():
                issues.append(ValidationIssue(
                    level=ValidationLevel.INTEGRATION,
                    severity=ValidationSeverity.ERROR,
                    message="Missing module.py (required for API modules)"
                ))

        # Check UI path si has_ui
        if manifest.capabilities.has_ui and manifest.ui:
            ui_path = contract_path / manifest.ui.path
            if not ui_path.exists():
                issues.append(ValidationIssue(
                    level=ValidationLevel.INTEGRATION,
                    severity=ValidationSeverity.ERROR,
                    message=f"Missing UI directory: {manifest.ui.path}"
                ))

        # Check tests si has_tests
        if manifest.capabilities.has_tests:
            tests_path = contract_path / "tests"
            if not tests_path.exists():
                issues.append(ValidationIssue(
                    level=ValidationLevel.INTEGRATION,
                    severity=ValidationSeverity.WARNING,
                    message="Missing tests directory"
                ))

        valid = not any(
            issue.severity == ValidationSeverity.CRITICAL
            for issue in issues
        )

        return ValidationResult(
            valid=valid,
            issues=issues,
            contract_id=contract_id
        )

    def validate_all(
        self,
        contract_path: Path,
        contract_instance: Optional[Any] = None
    ) -> ValidationResult:
        """
        Valida un contracte en totes les capes.

        Args:
            contract_path: Path al contracte
            contract_instance: Instància del contracte (opcional)

        Returns:
            ValidationResult agregat
        """
        all_issues = []
        contract_id = None

        # Layer 1: Schema
        manifest_path = contract_path / "manifest.toml"
        schema_result = self.validate_manifest_schema(manifest_path)
        all_issues.extend(schema_result.issues)
        contract_id = schema_result.contract_id

        if not schema_result.valid:
            # Si schema falla, no podem continuar
            return ValidationResult(
                valid=False,
                issues=all_issues,
                contract_id=contract_id
            )

        # Carregar manifest
        try:
            manifest = load_manifest_from_toml(str(manifest_path))
        except:
            return ValidationResult(
                valid=False,
                issues=all_issues,
                contract_id=contract_id
            )

        # Layer 2: Runtime (si tenim instància)
        if contract_instance:
            runtime_result = self.validate_contract_runtime(contract_instance)
            all_issues.extend(runtime_result.issues)

        # Layer 3: Integration
        integration_result = self.validate_file_structure(contract_path, manifest)
        all_issues.extend(integration_result.issues)

        # Valid si no hi ha errors crítics
        valid = not any(
            issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            for issue in all_issues
        )

        return ValidationResult(
            valid=valid,
            issues=all_issues,
            contract_id=contract_id
        )


# ============================================
# SINGLETON GETTER
# ============================================

_validator_instance: Optional[ContractValidator] = None


def get_validator() -> ContractValidator:
    """
    Obté la instància singleton del validator.

    Returns:
        ContractValidator singleton
    """
    global _validator_instance

    if _validator_instance is None:
        _validator_instance = ContractValidator()

    return _validator_instance
