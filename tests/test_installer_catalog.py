"""
Tests for installer/installer_catalog_data.py — Bug 29 fix release v0.9.0.

Phi-3.5 has been removed from the catalog because the Microsoft GGUF URL
requires HF login and only downloaded 29 bytes (error HTML),
causing silent failures during installation.
"""

import json
from pathlib import Path

from installer.installer_catalog_data import MODEL_CATALOG


def _all_keys():
    keys = []
    for category in MODEL_CATALOG.values():
        for model in category:
            keys.append(model["key"])
    return keys


def test_phi35_not_in_python_catalog():
    assert "phi35" not in _all_keys()


def test_no_phi3_mini_ollama_tag():
    for category in MODEL_CATALOG.values():
        for model in category:
            assert model.get("ollama") != "phi3:mini"


def test_no_phi35_gguf_url():
    for category in MODEL_CATALOG.values():
        for model in category:
            gguf = model.get("gguf") or ""
            assert "Phi-3.5" not in gguf
            assert "phi-3.5" not in gguf.lower()


def test_phi35_not_in_swift_wizard_models_json():
    """The parallel Swift wizard JSON catalog must also be clean."""
    json_path = (
        Path(__file__).resolve().parent.parent
        / "installer" / "swift-wizard" / "Resources" / "models.json"
    )
    if not json_path.exists():
        # If not present in this checkout, do not fail the test.
        return
    data = json.loads(json_path.read_text())
    keys = []
    for category_models in data.values():
        for model in category_models:
            keys.append(model.get("key"))
    assert "phi35" not in keys


def test_catalog_still_has_small_models():
    """Sanity: small tier slimmed to qwen3.5:4b only (2026-05-23)."""
    small = MODEL_CATALOG.get("small", [])
    assert len(small) == 1
    assert small[0]["key"] == "qwen35_4b"
    assert small[0].get("recommended") is True


# ════════════════════════════════════════════════════════════════════════
# Tests helpers de select_model (refactor CCN 36→≤10, façana facade)
# ════════════════════════════════════════════════════════════════════════

from installer.installer_catalog import (  # noqa: E402
    _build_available_engines,
    _determine_recommended_category,
    _get_model_engines,
    _get_model_id,
    _get_model_status,
    _localize,
    _resolve_category,
    _select_category,
    _select_engine_interactive,
    _select_model_from_list,
    _warn_qwen35_mlx,
)


class TestDetermineRecommendedCategory:
    def test_small_when_ram_below_5(self):
        rec, _ = _determine_recommended_category(4)
        assert rec == "1"

    def test_medium_when_ram_5_to_19(self):
        rec, _ = _determine_recommended_category(10)
        assert rec == "2"

    def test_large_when_ram_20_plus(self):
        rec, _ = _determine_recommended_category(30)
        assert rec == "3"

    def test_boundary_5_is_medium(self):
        rec, _ = _determine_recommended_category(5)
        assert rec == "2"

    def test_boundary_20_is_large(self):
        rec, _ = _determine_recommended_category(20)
        assert rec == "3"


class TestResolveCategory:
    def test_choice_1_returns_small(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        cat, _ = _resolve_category("1", "1")
        assert cat == "small"

    def test_choice_2_returns_medium(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        cat, _ = _resolve_category("2", "1")
        assert cat == "medium"

    def test_choice_3_returns_large(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        cat, _ = _resolve_category("3", "1")
        assert cat == "large"

    def test_invalid_choice_uses_recommended(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        cat, _ = _resolve_category("99", "2")
        assert cat == "medium"


class TestGetModelEngines:
    def test_all_engines_in_order(self):
        assert _get_model_engines({"mlx": "m", "ollama": "o", "gguf": "g"}) == ["MLX", "Ollama", "GGUF"]

    def test_only_ollama(self):
        assert _get_model_engines({"ollama": "o"}) == ["Ollama"]

    def test_empty_model(self):
        assert _get_model_engines({}) == []

    def test_mlx_only(self):
        assert _get_model_engines({"mlx": "m"}) == ["MLX"]


class TestGetModelStatus:
    def test_fits_returns_compatible(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        assert "compatible" in _get_model_status(True, True, 100)

    def test_no_disk_with_free_space_returns_disk_suffix(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        assert "(disk)" in _get_model_status(False, False, 50)

    def test_no_ram_zero_disk_free_no_disk_suffix(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        assert "(disk)" not in _get_model_status(False, True, 0)


class TestLocalize:
    def test_dict_returns_requested_lang(self):
        assert _localize({"ca": "Català", "en": "English"}, "en") == "English"

    def test_dict_falls_back_to_ca(self):
        assert _localize({"ca": "Català"}, "fr") == "Català"

    def test_plain_string_passthrough(self):
        assert _localize("plain", "en") == "plain"


class TestBuildAvailableEngines:
    def test_metal_with_mlx_includes_mlx_first(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        engines = _build_available_engines({"mlx": "m", "ollama": "o"}, has_metal=True)
        assert engines[0][0] == "mlx"

    def test_no_metal_skips_mlx(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        engines = _build_available_engines({"mlx": "m", "ollama": "o"}, has_metal=False)
        assert all(e[0] != "mlx" for e in engines)

    def test_gguf_included_when_present(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        engines = _build_available_engines({"ollama": "o", "gguf": "g.gguf"}, has_metal=False)
        assert any(e[0] == "llama_cpp" for e in engines)

    def test_empty_model_returns_empty(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        assert _build_available_engines({}, has_metal=True) == []


class TestGetModelId:
    _M = {"mlx": "mlx-id", "ollama": "oll-id", "gguf": "gguf.bin"}

    def test_mlx(self):
        assert _get_model_id("mlx", self._M) == "mlx-id"

    def test_llama_cpp(self):
        assert _get_model_id("llama_cpp", self._M) == "gguf.bin"

    def test_ollama(self):
        assert _get_model_id("ollama", self._M) == "oll-id"


class TestSelectModelFromList:
    _MODELS = [{"name": "A"}, {"name": "B"}, {"name": "C"}]

    def test_valid_index_1(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "1")
        assert _select_model_from_list(self._MODELS)["name"] == "A"

    def test_valid_index_3(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "3")
        assert _select_model_from_list(self._MODELS)["name"] == "C"

    def test_empty_input_defaults_to_first(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert _select_model_from_list(self._MODELS)["name"] == "A"

    def test_invalid_string_defaults_to_first(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "xyz")
        assert _select_model_from_list(self._MODELS)["name"] == "A"

    def test_out_of_range_defaults_to_first(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "99")
        assert _select_model_from_list(self._MODELS)["name"] == "A"


class TestSelectCategory:
    def test_returns_user_input(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "2")
        assert _select_category("1", "label") == "2"

    def test_empty_input_returns_recommended(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert _select_category("3", "label") == "3"


class TestSelectEngineInteractive:
    def test_single_engine_returns_without_menu(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        result = _select_engine_interactive({"name": "M"}, [("ollama", "Ollama", "d", True)])
        assert result == "ollama"

    def test_no_engines_returns_ollama_fallback(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        assert _select_engine_interactive({"name": "M"}, []) == "ollama"

    def test_multiple_engines_picks_by_index(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "2")
        engines = [("mlx", "MLX", "d", True), ("ollama", "Ollama", "d", False)]
        assert _select_engine_interactive({"name": "M"}, engines) == "ollama"

    def test_invalid_choice_uses_recommended(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        monkeypatch.setattr("builtins.input", lambda _: "bad")
        engines = [("mlx", "MLX", "d", True), ("ollama", "Ollama", "d", False)]
        assert _select_engine_interactive({"name": "M"}, engines) == "mlx"


class TestWarnQwen35Mlx:
    def test_no_warn_for_ollama_engine(self, monkeypatch):
        calls = []
        monkeypatch.setattr("builtins.input", lambda _: calls.append(1) or "")
        _warn_qwen35_mlx("ollama", {"mlx": "mlx-community/Qwen3.5-2b"})
        assert calls == []

    def test_no_warn_for_non_qwen35_model(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        calls = []
        monkeypatch.setattr("builtins.input", lambda _: calls.append(1) or "")
        _warn_qwen35_mlx("mlx", {"mlx": "mlx-community/llama-3b"})
        assert calls == []

    def test_warns_for_qwen35_mlx_combination(self, monkeypatch):
        import installer.installer_catalog as ic
        monkeypatch.setattr(ic, "t", lambda k: k)
        calls = []
        monkeypatch.setattr("builtins.input", lambda _: calls.append(1) or "")
        _warn_qwen35_mlx("mlx", {"mlx": "mlx-community/Qwen3.5-2b-mlx"})
        assert len(calls) == 1
