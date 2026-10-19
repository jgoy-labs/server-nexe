"""pla-comportament-segons-mida-model, A: the size is read from the model itself."""
import json

import pytest

from core.turn import model_size as ms


def _mlx_dir(tmp_path, name, *, total_size, bits=None, group=64, total_parameters=None):
    folder = tmp_path / name
    folder.mkdir()
    meta = {"total_size": total_size}
    if total_parameters:
        meta["total_parameters"] = total_parameters
    (folder / "model.safetensors.index.json").write_text(json.dumps({"metadata": meta}))
    cfg = {"quantization": {"group_size": group, "bits": bits}} if bits else {}
    (folder / "config.json").write_text(json.dumps(cfg))
    return folder


class TestName:
    @pytest.mark.parametrize("name,total,active", [
        ("Qwen3.5-9B-MLX-4bit", 9.0, None),
        ("qwen3.5:4b", 4.0, None),
        ("gemma-4-31b-8bit", 31.0, None),
        ("qwen3.5:35b-a3b", 35.0, 3.0),
    ])
    def test_reads_the_billions(self, name, total, active):
        got = ms.from_name(name)
        assert (got.params_b, got.active_b, got.source) == (total, active, "name")

    @pytest.mark.parametrize("name", ["", "test-model", "qwen3.5-4bit", "gemma-4-e4b-4bit", "mixtral:8x7b"])
    def test_no_size_in_the_name_is_unknown(self, name):
        assert ms.from_name(name) is ms.UNKNOWN


class TestOllama:
    @pytest.mark.parametrize("raw,expected", [("9.0B", 9.0), ("20.9B", 20.9), ("751.63M", 0.75)])
    def test_parameter_size(self, raw, expected):
        got = ms.from_ollama_details({"parameter_size": raw}, "x")
        assert (got.params_b, got.source) == (expected, "ollama")

    def test_missing_details_fall_back_to_the_name(self):
        got = ms.from_ollama_details({}, "qwen3.5:4b")
        assert (got.params_b, got.source) == (4.0, "name")


class TestMlx:
    def test_the_index_count_wins(self, tmp_path):
        folder = _mlx_dir(tmp_path, "gpt-oss-20b-MLX-8bit", total_size=22228464768, bits=8,
                          total_parameters=20914755648)
        got = ms.from_mlx_dir(folder)
        assert (got.params_b, got.source) == (20.91, "index")

    # The four real models measured on 17/10 (weights bytes, bits): the estimate
    # tells a 4B from a 9B from a 27B from a 31B within 20 %.
    @pytest.mark.parametrize("name,size,bits,real", [
        ("Qwen3.5-4B-4bit", 3034147328, 4, 4.7),
        ("Qwen3.5-9B-MLX-4bit", 5950062560, 4, 9.65),
        ("Qwen3.5-27B-4bit", 16054266848, 4, 27.8),
        ("gemma-4-31b-8bit", 33762858712, 8, 31.0),
    ])
    def test_estimate_from_the_weights(self, tmp_path, name, size, bits, real):
        got = ms.from_mlx_dir(_mlx_dir(tmp_path, name, total_size=size, bits=bits))
        assert got.source == "estimated"
        assert abs(got.params_b - real) / real < 0.20

    def test_not_quantised_counts_16_bits(self, tmp_path):
        got = ms.from_mlx_dir(_mlx_dir(tmp_path, "x-bf16", total_size=16_000_000_000))
        assert (got.params_b, got.source) == (8.0, "estimated")

    def test_without_index_the_name_speaks(self, tmp_path):
        folder = tmp_path / "Qwen3.5-9B-MLX-4bit"
        folder.mkdir()
        assert ms.from_mlx_dir(folder).source == "name"


class TestModelSize:
    @pytest.fixture(autouse=True)
    def _fresh(self):
        ms.forget_cache()
        yield
        ms.forget_cache()

    async def test_an_api_is_api(self):
        assert (await ms.model_size("api", "deepseek-chat")) is ms.API

    async def test_mlx_by_name_under_the_models_dir(self, tmp_path, monkeypatch):
        _mlx_dir(tmp_path, "Qwen3.5-9B-MLX-4bit", total_size=5950062560, bits=4)
        monkeypatch.setenv("NEXE_STORAGE_PATH", str(tmp_path))
        got = await ms.model_size("mlx", "Qwen3.5-9B-MLX-4bit")
        assert got.source == "estimated"

    async def test_ollama_reads_show(self, monkeypatch):
        async def fake(model):
            return ms.from_ollama_details({"parameter_size": "4.7B"}, model)
        monkeypatch.setattr(ms, "_ollama_show", fake)
        got = await ms.model_size("ollama", "qwen3.5:4b")
        assert (got.params_b, got.source) == (4.7, "ollama")

    async def test_a_failing_ollama_falls_back_to_the_name_and_never_raises(self, monkeypatch):
        async def boom(model):
            raise OSError("down")
        monkeypatch.setattr(ms, "_ollama_show", boom)
        got = await ms.model_size("ollama", "qwen3.5:4b")
        assert (got.params_b, got.source) == (4.0, "name")

    async def test_unreadable_is_unknown(self, monkeypatch):
        got = await ms.model_size("llama_cpp", "mystery")
        assert got is ms.UNKNOWN

    async def test_it_is_cached(self, monkeypatch):
        calls = []

        async def fake(model):
            calls.append(model)
            return ms.from_ollama_details({"parameter_size": "9B"}, model)
        monkeypatch.setattr(ms, "_ollama_show", fake)
        await ms.model_size("ollama", "m")
        await ms.model_size("ollama", "m")
        assert calls == ["m"]


class TestEffective:
    def test_the_active_parameters_weigh_when_known(self):
        assert ms.ModelSize(35.0, 3.0, "name").effective_b() == 3.0

    def test_otherwise_the_total(self):
        assert ms.ModelSize(9.0, None, "ollama").effective_b() == 9.0

    def test_nothing_is_none(self):
        assert ms.UNKNOWN.effective_b() is None


class TestRetry:
    @pytest.fixture(autouse=True)
    def _fresh(self):
        ms.forget_cache()
        yield
        ms.forget_cache()

    async def test_an_unknown_is_tried_again_after_a_minute(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(ms.time, "monotonic", lambda: now[0])
        assert (await ms.model_size("llama_cpp", "mystery")) is ms.UNKNOWN
        calls = []
        real = ms.from_name
        monkeypatch.setattr(ms, "from_name", lambda n: (calls.append(n), real(n))[1])
        await ms.model_size("llama_cpp", "mystery")
        assert calls == []                      # still cached
        now[0] += ms._RETRY_AFTER_S + 1
        await ms.model_size("llama_cpp", "mystery")
        assert calls == ["mystery"]             # asked again

    async def test_a_known_size_is_kept(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(ms.time, "monotonic", lambda: now[0])
        calls = []

        async def fake(model):
            calls.append(model)
            return ms.from_ollama_details({"parameter_size": "9B"}, model)
        monkeypatch.setattr(ms, "_ollama_show", fake)
        await ms.model_size("ollama", "m")
        now[0] += 10 * ms._RETRY_AFTER_S
        await ms.model_size("ollama", "m")
        assert calls == ["m"]
