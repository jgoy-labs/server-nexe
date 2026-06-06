"""Tests for personality/models/registry.py — coverage gaps."""


class TestModelEntry:
    def test_dataclass_fields(self):
        from personality.models.registry import ModelEntry
        e = ModelEntry(
            short_name="test", description="Test model",
            size_gb=1.0, ollama_tag="test:latest", mlx_hf_id="org/test",
        )
        assert e.short_name == "test"
        assert e.size_gb == 1.0


class TestModelRegistry:
    def test_registry_not_empty(self):
        from personality.models.registry import MODEL_REGISTRY
        assert len(MODEL_REGISTRY) > 10

    def test_all_entries_have_required_fields(self):
        from personality.models.registry import MODEL_REGISTRY
        for name, entry in MODEL_REGISTRY.items():
            assert entry.short_name == name
            assert entry.description
            assert entry.size_gb > 0
            assert entry.ollama_tag


class TestGetModelEntry:
    def test_existing_model(self):
        from personality.models.registry import get_model_entry
        entry = get_model_entry("qwen3.5:4b")
        assert entry is not None
        assert entry.short_name == "qwen3.5:4b"

    def test_case_insensitive(self):
        from personality.models.registry import get_model_entry
        # PERS-005: catalog key is lowercase; lookup must be case-insensitive.
        assert get_model_entry("ALIA-40B") is not None

    def test_nonexistent_returns_none(self):
        from personality.models.registry import get_model_entry
        assert get_model_entry("nonexistent_model") is None


class TestV105Catalog:
    """PERS-005: registry must match the v1.0.5 catalog (Qwen3.5, Gemma 4,
    GPT-OSS, DeepSeek R1, ALIA, Salamandra), not the stale Qwen2/Llama3.x set."""

    def test_v105_models_present(self):
        from personality.models.registry import MODEL_REGISTRY
        for key in (
            "qwen3.5:4b", "qwen3.5:9b", "qwen3.5:27b", "qwen3.5:35b-a3b",
            "gemma4:e4b", "gemma4:31b",
            "mistral-small3.2", "gpt-oss:20b", "deepseek-r1:32b",
            "alia-40b", "salamandra7b",
        ):
            assert key in MODEL_REGISTRY, f"missing v1.0.5 model: {key}"

    def test_stale_models_removed(self):
        from personality.models.registry import MODEL_REGISTRY
        for stale in ("qwen0.5", "tinyllama", "phi3.5", "llama3.1-8b",
                      "llama3.2-3b", "salamandra2b", "mistral7b"):
            assert stale not in MODEL_REGISTRY, f"stale model still present: {stale}"

    def test_ollama_tags_match_catalog(self):
        from personality.models.registry import get_model_entry
        assert get_model_entry("qwen3.5:4b").ollama_tag == "qwen3.5:4b"
        assert get_model_entry("gpt-oss:20b").ollama_tag == "gpt-oss:20b"
        assert get_model_entry("alia-40b").ollama_tag == "csala/ALIA-40B:Q8_0"

    def test_gguf_only_models_have_no_mlx(self):
        from personality.models.registry import get_model_entry
        # Salamandra / DeepSeek / ALIA are GGUF/Ollama-only in the catalog.
        assert get_model_entry("salamandra7b").mlx_hf_id == ""
        assert get_model_entry("deepseek-r1:32b").mlx_hf_id == ""
        assert get_model_entry("alia-40b").mlx_hf_id == ""


class TestListModelsTable:
    def test_returns_formatted_string(self):
        from personality.models.registry import list_models_table
        table = list_models_table()
        assert isinstance(table, str)
        assert "qwen3.5:4b" in table
        assert "GB" in table
        assert len(table.split("\n")) > 10
