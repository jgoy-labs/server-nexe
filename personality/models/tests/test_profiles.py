"""
Tests per personality/models/profiles.py i registry.py
"""
import pytest
from personality.models.profiles import (
    EngineType,
    HardwareTier,
    ModelProfile,
    PROFILES,
)
from personality.models.registry import (
    ModelEntry,
    MODEL_REGISTRY,
    get_model_entry,
    list_models_table,
)


class TestEngineType:
    def test_auto_value(self):
        assert EngineType.AUTO == "auto"

    def test_mlx_value(self):
        assert EngineType.MLX == "mlx"

    def test_ollama_value(self):
        assert EngineType.OLLAMA == "ollama"

    def test_llama_cpp_value(self):
        assert EngineType.LLAMA_CPP == "llama_cpp"

    def test_from_string(self):
        engine = EngineType("mlx")
        assert engine == EngineType.MLX


class TestHardwareTier:
    def test_micro_value(self):
        assert HardwareTier.MICRO == "micro"

    def test_consumer_value(self):
        assert HardwareTier.CONSUMER == "consumer"

    def test_pro_value(self):
        assert HardwareTier.PRO == "pro"

    def test_ultra_value(self):
        assert HardwareTier.ULTRA == "ultra"


class TestModelProfile:
    def test_creation(self):
        profile = ModelProfile(
            tier=HardwareTier.CONSUMER,
            primary_model="llama3.2",
            secondary_model="tinyllama",
            embedding_model="paraphrase-multilingual-mpnet-base-v2",
            preferred_engine=EngineType.MLX,
            max_tokens=2048,
            context_window=8192,
            description="Test profile"
        )
        assert profile.tier == HardwareTier.CONSUMER
        assert profile.primary_model == "llama3.2"
        assert profile.mlx_model_id is None

    def test_with_mlx_model_id(self):
        profile = ModelProfile(
            tier=HardwareTier.PRO,
            primary_model="llama3.1:8b",
            secondary_model="mistral:7b",
            embedding_model="paraphrase-multilingual-mpnet-base-v2",
            preferred_engine=EngineType.MLX,
            max_tokens=4096,
            context_window=32768,
            description="Pro profile",
            mlx_model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
        )
        assert profile.mlx_model_id is not None


class TestProfiles:
    def test_all_tiers_defined(self):
        assert HardwareTier.MICRO in PROFILES
        assert HardwareTier.CONSUMER in PROFILES
        assert HardwareTier.PRO in PROFILES
        assert HardwareTier.ULTRA in PROFILES

    def test_micro_profile(self):
        profile = PROFILES[HardwareTier.MICRO]
        assert profile.tier == HardwareTier.MICRO
        assert profile.max_tokens == 1024
        assert profile.context_window == 2048

    def test_consumer_profile(self):
        profile = PROFILES[HardwareTier.CONSUMER]
        assert profile.preferred_engine == EngineType.MLX
        assert profile.max_tokens >= 2048

    def test_pro_profile(self):
        profile = PROFILES[HardwareTier.PRO]
        assert profile.max_tokens >= 4096

    def test_ultra_profile(self):
        profile = PROFILES[HardwareTier.ULTRA]
        assert profile.max_tokens >= 8192


class TestModelRegistry:
    def test_registry_not_empty(self):
        assert len(MODEL_REGISTRY) > 0

    def test_get_model_entry_exists(self):
        entry = get_model_entry("phi3.5")
        assert entry is not None
        assert entry.short_name == "phi3.5"

    def test_get_model_entry_case_insensitive(self):
        entry = get_model_entry("PHI3.5")
        assert entry is not None

    def test_get_model_entry_not_found(self):
        entry = get_model_entry("model_inexistent")
        assert entry is None

    def test_model_entry_fields(self):
        entry = get_model_entry("llama3.1-8b")
        assert entry is not None
        assert entry.ollama_tag is not None
        assert entry.mlx_hf_id is not None
        assert entry.size_gb > 0

    def test_list_models_table_returns_string(self):
        table = list_models_table()
        assert isinstance(table, str)
        assert len(table) > 0

    def test_list_models_table_contains_models(self):
        table = list_models_table()
        assert "phi3.5" in table

    def test_iberian_models_present(self):
        assert "salamandra2b" in MODEL_REGISTRY
        assert "salamandra7b" in MODEL_REGISTRY

    def test_micro_models_present(self):
        assert "qwen0.5" in MODEL_REGISTRY
        assert "tinyllama" in MODEL_REGISTRY


class TestModelSelector:
    def test_hardware_profile_creation(self):
        from personality.models.selector import HardwareProfile
        hw = HardwareProfile()
        assert hw.total_ram_gb > 0
        assert hw.system in ("Darwin", "Linux", "Windows")

    def test_hardware_profile_str(self):
        from personality.models.selector import HardwareProfile
        hw = HardwareProfile()
        s = str(hw)
        assert "Hardware:" in s
        assert "RAM:" in s

    def test_model_selector_analyze(self):
        from personality.models.selector import ModelSelector, HardwareProfile
        selector = ModelSelector()
        hw = selector.analyze()
        assert isinstance(hw, HardwareProfile)

    def test_model_selector_recommend(self):
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        profile = selector.recommend()
        assert isinstance(profile, ModelProfile)
        assert profile.preferred_engine in list(EngineType)

    def test_determine_tier_micro(self):
        from personality.models.selector import ModelSelector, HardwareProfile
        from unittest.mock import patch
        selector = ModelSelector()
        selector.hw.total_ram_gb = 4.0
        tier = selector._determine_tier()
        assert tier == HardwareTier.MICRO

    def test_determine_tier_consumer(self):
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        selector.hw.total_ram_gb = 8.0
        tier = selector._determine_tier()
        assert tier == HardwareTier.CONSUMER

    def test_determine_tier_pro(self):
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        selector.hw.total_ram_gb = 16.0
        tier = selector._determine_tier()
        assert tier == HardwareTier.PRO

    def test_determine_tier_ultra(self):
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        selector.hw.total_ram_gb = 64.0
        tier = selector._determine_tier()
        assert tier == HardwareTier.ULTRA

    def test_check_ollama_available(self):
        from personality.models.selector import ModelSelector
        from unittest.mock import patch
        selector = ModelSelector()
        with patch("shutil.which", return_value="/usr/local/bin/ollama"):
            assert selector._check_ollama_available() is True
        with patch("shutil.which", return_value=None):
            assert selector._check_ollama_available() is False

    def test_apply_to_config(self):
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        profile = PROFILES[HardwareTier.CONSUMER]
        config = {}
        result = selector.apply_to_config(config, profile)
        assert "plugins" in result
        assert "models" in result["plugins"]
        assert "preferred_engine" in result["plugins"]["models"]

    def test_apply_to_config_existing_config(self):
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        profile = PROFILES[HardwareTier.PRO]
        config = {"plugins": {"models": {"existing_key": "val"}}}
        result = selector.apply_to_config(config, profile)
        assert result["plugins"]["models"]["existing_key"] == "val"
        assert "primary" in result["plugins"]["models"]

    def test_recommend_apple_silicon(self):
        from personality.models.selector import ModelSelector
        from unittest.mock import patch
        selector = ModelSelector()
        selector.hw.is_apple_silicon = True
        profile = selector.recommend()
        assert profile.preferred_engine == EngineType.MLX

    def test_recommend_ollama_available(self):
        from personality.models.selector import ModelSelector
        from unittest.mock import patch
        selector = ModelSelector()
        selector.hw.is_apple_silicon = False
        with patch.object(selector, "_check_ollama_available", return_value=True):
            profile = selector.recommend()
        assert profile.preferred_engine == EngineType.OLLAMA

    def test_recommend_fallback_llama_cpp(self):
        from personality.models.selector import ModelSelector
        from unittest.mock import patch
        selector = ModelSelector()
        selector.hw.is_apple_silicon = False
        with patch.object(selector, "_check_ollama_available", return_value=False):
            profile = selector.recommend()
        assert profile.preferred_engine == EngineType.LLAMA_CPP
