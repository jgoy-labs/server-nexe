"""Tests for personality/models/__init__.py — facade coverage."""


class TestModelsInit:
    def test_exports_model_selector(self):
        from personality.models import ModelSelector
        assert ModelSelector is not None

    def test_exports_hardware_profile(self):
        from personality.models import HardwareProfile
        assert HardwareProfile is not None

    def test_all_exports(self):
        from personality.models import __all__
        assert "ModelSelector" in __all__
        assert "HardwareProfile" in __all__
