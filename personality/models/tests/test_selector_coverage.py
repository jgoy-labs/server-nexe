"""Tests for personality/models/selector.py — coverage gaps."""
from unittest.mock import patch, MagicMock


class TestHardwareProfile:
    def test_creates_profile(self):
        from personality.models.selector import HardwareProfile
        hw = HardwareProfile()
        assert hw.total_ram_gb > 0
        assert hw.system in ("Darwin", "Linux", "Windows")

    def test_str_representation(self):
        from personality.models.selector import HardwareProfile
        hw = HardwareProfile()
        s = str(hw)
        assert "Hardware:" in s
        assert "RAM:" in s


class TestModelSelector:
    def test_analyze_returns_hw_profile(self):
        from personality.models.selector import ModelSelector, HardwareProfile
        sel = ModelSelector()
        hw = sel.analyze()
        assert isinstance(hw, HardwareProfile)

    def test_recommend_returns_profile(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import ModelProfile
        sel = ModelSelector()
        profile = sel.recommend()
        assert isinstance(profile, ModelProfile)

    def test_determine_tier_micro(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import HardwareTier
        sel = ModelSelector()
        sel.hw.total_ram_gb = 4
        assert sel._determine_tier() == HardwareTier.MICRO

    def test_determine_tier_consumer(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import HardwareTier
        sel = ModelSelector()
        sel.hw.total_ram_gb = 12
        assert sel._determine_tier() == HardwareTier.CONSUMER

    def test_determine_tier_pro(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import HardwareTier
        sel = ModelSelector()
        sel.hw.total_ram_gb = 24
        assert sel._determine_tier() == HardwareTier.PRO

    def test_determine_tier_ultra(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import HardwareTier
        sel = ModelSelector()
        sel.hw.total_ram_gb = 64
        assert sel._determine_tier() == HardwareTier.ULTRA

    def test_recommend_apple_silicon_uses_mlx(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import EngineType
        sel = ModelSelector()
        sel.hw.is_apple_silicon = True
        profile = sel.recommend()
        assert profile.preferred_engine == EngineType.MLX

    def test_recommend_no_apple_silicon_with_ollama(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import EngineType
        sel = ModelSelector()
        sel.hw.is_apple_silicon = False
        with patch.object(sel, '_check_ollama_available', return_value=True):
            profile = sel.recommend()
        assert profile.preferred_engine == EngineType.OLLAMA

    def test_recommend_no_apple_silicon_no_ollama(self):
        from personality.models.selector import ModelSelector
        from personality.models.profiles import EngineType
        sel = ModelSelector()
        sel.hw.is_apple_silicon = False
        with patch.object(sel, '_check_ollama_available', return_value=False):
            profile = sel.recommend()
        assert profile.preferred_engine == EngineType.LLAMA_CPP

    def test_apply_to_config(self):
        from personality.models.selector import ModelSelector
        sel = ModelSelector()
        profile = sel.recommend()
        config = {}
        result = sel.apply_to_config(config, profile)
        assert "plugins" in result
        assert "models" in result["plugins"]
        assert result["plugins"]["models"]["primary"] == profile.primary_model

    def test_apply_to_config_existing_plugins(self):
        from personality.models.selector import ModelSelector
        sel = ModelSelector()
        profile = sel.recommend()
        config = {"plugins": {"other": "data"}}
        result = sel.apply_to_config(config, profile)
        assert result["plugins"]["other"] == "data"
        assert "models" in result["plugins"]
