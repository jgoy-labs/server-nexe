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
        entry = get_model_entry("phi3.5")
        assert entry is not None
        assert entry.short_name == "phi3.5"

    def test_case_insensitive(self):
        from personality.models.registry import get_model_entry
        assert get_model_entry("PHI3.5") is not None

    def test_nonexistent_returns_none(self):
        from personality.models.registry import get_model_entry
        assert get_model_entry("nonexistent_model") is None


class TestListModelsTable:
    def test_returns_formatted_string(self):
        from personality.models.registry import list_models_table
        table = list_models_table()
        assert isinstance(table, str)
        assert "phi3.5" in table
        assert "GB" in table
        assert len(table.split("\n")) > 10
