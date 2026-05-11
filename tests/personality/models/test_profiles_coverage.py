"""Tests for personality/models/profiles.py — coverage gaps."""


class TestEngineType:
    def test_all_variants(self):
        from personality.models.profiles import EngineType
        assert EngineType.AUTO == "auto"
        assert EngineType.MLX == "mlx"
        assert EngineType.OLLAMA == "ollama"
        assert EngineType.LLAMA_CPP == "llama_cpp"


class TestHardwareTier:
    def test_all_tiers(self):
        from personality.models.profiles import HardwareTier
        assert HardwareTier.MICRO == "micro"
        assert HardwareTier.CONSUMER == "consumer"
        assert HardwareTier.PRO == "pro"
        assert HardwareTier.ULTRA == "ultra"


class TestModelProfile:
    def test_profile_fields(self):
        from personality.models.profiles import ModelProfile, HardwareTier, EngineType
        p = ModelProfile(
            tier=HardwareTier.MICRO,
            primary_model="test",
            secondary_model="test2",
            embedding_model="embed",
            preferred_engine=EngineType.AUTO,
            max_tokens=512,
            context_window=1024,
            description="Test profile",
        )
        assert p.tier == HardwareTier.MICRO
        assert p.max_tokens == 512
        assert p.mlx_model_id is None


class TestProfiles:
    def test_all_tiers_have_profiles(self):
        from personality.models.profiles import PROFILES, HardwareTier
        for tier in HardwareTier:
            assert tier in PROFILES
            assert PROFILES[tier].tier == tier

    def test_micro_uses_llama_cpp(self):
        from personality.models.profiles import PROFILES, HardwareTier, EngineType
        assert PROFILES[HardwareTier.MICRO].preferred_engine == EngineType.LLAMA_CPP

    def test_ultra_has_largest_context(self):
        from personality.models.profiles import PROFILES, HardwareTier
        assert PROFILES[HardwareTier.ULTRA].context_window > PROFILES[HardwareTier.MICRO].context_window
