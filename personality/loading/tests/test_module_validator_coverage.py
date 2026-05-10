"""Tests for personality/loading/module_validator.py — coverage gaps."""


class TestModuleValidator:
    def test_init(self):
        from personality.loading.module_validator import ModuleValidator
        v = ModuleValidator()
        assert v is not None

    def test_validation_error_class(self):
        from personality.loading.module_validator import ModuleValidationError
        err = ModuleValidationError("invalid module")
        assert "invalid module" in str(err)

    def test_module_imports(self):
        from personality.loading import module_validator
        assert hasattr(module_validator, 'ModuleValidator')
        assert hasattr(module_validator, 'ModuleValidationError')
