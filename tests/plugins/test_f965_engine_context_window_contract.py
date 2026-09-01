"""#965 — every engine answers how many tokens it can hold, in its own module.

Before this, only Ollama (auto_num_ctx, by RAM) and MLX (auto_max_kv_size, by RAM
AND real model weights) could size their window; llama.cpp shipped a flat
`n_ctx = 8192` that ignored the machine entirely. On a 128 GB box that threw away
most of the window the model could actually hold.

The contract is deliberately per-plugin: each engine knows its own memory story,
and the caller only asks. `None` means "I cannot answer" — never a guessed number.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from plugins.llama_cpp_module.core.config import auto_n_ctx
from plugins.llama_cpp_module.module import LlamaCppModule
from plugins.mlx_module.module import MLXModule
from plugins.ollama_module.module import OllamaModule


def _fake_psutil(ram_gb: float) -> MagicMock:
    fake = MagicMock()
    fake.virtual_memory.return_value.total = int(ram_gb * (1024 ** 3))
    return fake


class TestLlamaCppAutoNCtx:
    """The detection llama.cpp was missing."""

    @pytest.mark.parametrize(
        "ram_gb,expected",
        [
            (128, 32768),
            (64, 32768),
            (48, 16384),
            (32, 16384),
            (24, 8192),
            (16, 4096),
            (8, 2048),
        ],
    )
    def test_window_follows_system_ram(self, ram_gb, expected, monkeypatch) -> None:
        monkeypatch.delenv("NEXE_LLAMA_CPP_N_CTX", raising=False)
        with patch.dict(sys.modules, {"psutil": _fake_psutil(ram_gb)}):
            assert auto_n_ctx() == expected

    def test_the_env_override_always_wins(self, monkeypatch) -> None:
        """An explicit NEXE_LLAMA_CPP_N_CTX short-circuits detection entirely —
        the user's number, not ours."""
        monkeypatch.setenv("NEXE_LLAMA_CPP_N_CTX", "4096")
        with patch.dict(sys.modules, {"psutil": _fake_psutil(128)}):
            assert auto_n_ctx() == 4096

    def test_without_psutil_it_stays_conservative(self, monkeypatch) -> None:
        """No psutil means no measurement: pick the safe rung, never the big one."""
        monkeypatch.delenv("NEXE_LLAMA_CPP_N_CTX", raising=False)
        with patch.dict(sys.modules, {"psutil": None}):
            assert auto_n_ctx() == 4096

    def test_it_is_no_longer_the_flat_8192(self, monkeypatch) -> None:
        """Regression guard for the actual bug: on a big machine the old code
        answered 8192 no matter what."""
        monkeypatch.delenv("NEXE_LLAMA_CPP_N_CTX", raising=False)
        with patch.dict(sys.modules, {"psutil": _fake_psutil(128)}):
            assert auto_n_ctx() != 8192


class TestFromEnvActuallyUsesTheDetection:
    """Testing `auto_n_ctx()` on its own is not enough: the bug was in what
    `from_env()` assigns. Unhook the two and every test above stays green while
    the product goes back to a flat 8192 — so this is the one that has to bite."""

    def test_the_built_config_carries_the_detected_window(self, monkeypatch) -> None:
        from plugins.llama_cpp_module.core.config import LlamaCppConfig

        monkeypatch.delenv("NEXE_LLAMA_CPP_N_CTX", raising=False)
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/tmp/does-not-exist.gguf")
        with patch.dict(sys.modules, {"psutil": _fake_psutil(128)}):
            cfg = LlamaCppConfig.from_env()
        assert cfg.n_ctx == 32768, (
            "from_env() must take n_ctx from auto_n_ctx(); a flat default here is the #965 bug"
        )

    def test_the_env_override_survives_from_env(self, monkeypatch) -> None:
        from plugins.llama_cpp_module.core.config import LlamaCppConfig

        monkeypatch.setenv("NEXE_LLAMA_CPP_N_CTX", "2048")
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/tmp/does-not-exist.gguf")
        with patch.dict(sys.modules, {"psutil": _fake_psutil(128)}):
            cfg = LlamaCppConfig.from_env()
        assert cfg.n_ctx == 2048


class TestTheRamLaddersDegradeTogether:
    """Failure tolerance of the two RAM ladders, in one place."""

    def test_a_broken_psutil_degrades_instead_of_raising(self, monkeypatch) -> None:
        """psutil importing and then failing is not ImportError. Both RAM ladders
        used to let that raise — and Ollama's runs at module import, so a broken
        probe was a boot failure, not a bad window."""
        from core.endpoints.chat_engines.ollama_helpers import auto_num_ctx

        monkeypatch.delenv("NEXE_LLAMA_CPP_N_CTX", raising=False)
        monkeypatch.delenv("NEXE_OLLAMA_NUM_CTX", raising=False)
        broken = MagicMock()
        broken.virtual_memory.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"psutil": broken}):
            assert auto_n_ctx() == 4096
            assert auto_num_ctx() == 4096

    def test_a_non_numeric_override_falls_back_to_detection(self, monkeypatch) -> None:
        """int('8k') used to raise — and auto_num_ctx runs at module import
        (ollama.py), so a typo in the env was a BOOT failure. Both ladders now
        warn and auto-detect instead."""
        from core.endpoints.chat_engines.ollama_helpers import auto_num_ctx

        for bogus in ("8k", "0", "-1"):
            monkeypatch.setenv("NEXE_LLAMA_CPP_N_CTX", bogus)
            monkeypatch.setenv("NEXE_OLLAMA_NUM_CTX", bogus)
            with patch.dict(sys.modules, {"psutil": _fake_psutil(128)}):
                assert auto_n_ctx() == 32768, f"{bogus!r} must fall back to detection"
                assert auto_num_ctx() == 32768, f"{bogus!r} must fall back to detection"

    def test_a_non_numeric_mlx_override_falls_back_to_auto(self, tmp_path, monkeypatch) -> None:
        from plugins.mlx_module.core.config import MLXConfig

        monkeypatch.setenv("NEXE_MLX_MAX_KV_SIZE", "64k")
        monkeypatch.setenv("NEXE_MLX_MODEL", str(tmp_path))
        cfg = MLXConfig.from_env()
        assert isinstance(cfg.max_kv_size, int) and cfg.max_kv_size >= 8192, (
            "a typo in NEXE_MLX_MAX_KV_SIZE must auto-size, not raise at engine init"
        )


class TestTheLaddersAgree:
    """Ollama IS llama.cpp underneath. Two different ladders would mean the engine
    you happened to pick silently changed how much context you got on the same box."""

    @pytest.mark.parametrize("ram_gb", [128, 64, 48, 32, 24, 16, 8])
    def test_llama_cpp_and_ollama_size_the_same_machine_the_same(self, ram_gb, monkeypatch) -> None:
        from core.endpoints.chat_engines.ollama_helpers import auto_num_ctx

        monkeypatch.delenv("NEXE_LLAMA_CPP_N_CTX", raising=False)
        monkeypatch.delenv("NEXE_OLLAMA_NUM_CTX", raising=False)
        with patch.dict(sys.modules, {"psutil": _fake_psutil(ram_gb)}):
            assert auto_n_ctx() == auto_num_ctx()


class TestTheContractAcrossEngines:
    """All three answer the same question, each from its own knowledge."""

    def test_ollama_answers_from_ram(self, monkeypatch) -> None:
        """Actually exercise the RAM ladder — setting NEXE_OLLAMA_NUM_CTX would
        short-circuit the very detection this test claims to check."""
        monkeypatch.delenv("NEXE_OLLAMA_NUM_CTX", raising=False)
        with patch.dict(sys.modules, {"psutil": _fake_psutil(32)}):
            assert OllamaModule().get_context_window() == 16384

    def test_ollama_honours_the_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXE_OLLAMA_NUM_CTX", "16384")
        assert OllamaModule().get_context_window() == 16384

    @pytest.mark.parametrize("module_cls", [MLXModule, LlamaCppModule])
    def test_no_node_means_no_answer_not_a_guess(self, module_cls) -> None:
        """A module that has not loaded anything must say None, so the caller
        falls back to the documented default instead of acting on a made-up number."""
        assert module_cls().get_context_window() is None

    def test_mlx_reports_its_kv_window(self) -> None:
        mod = MLXModule()
        mod._node = MagicMock()
        mod._node.config.max_kv_size = 65536
        assert mod.get_context_window() == 65536

    def test_llama_cpp_reports_its_n_ctx(self) -> None:
        mod = LlamaCppModule()
        mod._node = MagicMock()
        mod._node.config.n_ctx = 32768
        assert mod.get_context_window() == 32768

    @pytest.mark.parametrize("module_cls", [MLXModule, LlamaCppModule])
    def test_a_broken_config_does_not_take_the_chat_down(self, module_cls) -> None:
        """Window detection is a convenience, never a reason to 500 a chat turn."""
        mod = module_cls()
        mod._node = MagicMock()
        mod._node.config.max_kv_size = "not-a-number"
        mod._node.config.n_ctx = "not-a-number"
        assert mod.get_context_window() is None


class TestMLXIsCappedByTheModelItself:
    """#965 follow-up from the adversarial reviews: max_kv_size is a RAM budget,
    not the model's context limit. The cap lives in auto_max_kv_size() — NOT in
    whoever reports the window — so the prompt truncator, the prompt cache and
    the RAM guard all inherit it. A first version capped only the reported
    number, and the engine kept truncating against the uncapped budget: the very
    silent history loss the cap exists to prevent stayed alive on the path that
    causes it."""

    def _model_dir(self, tmp_path, max_positions, *, nested=False):
        import json

        d = tmp_path / "model"
        d.mkdir()
        params = {
            "max_position_embeddings": max_positions,
            "num_hidden_layers": 32, "num_key_value_heads": 8, "head_dim": 128,
        }
        body = {"text_config": params} if nested else params
        (d / "config.json").write_text(json.dumps(body))
        return d

    def test_a_small_model_caps_the_kv_budget_at_the_source(self, tmp_path) -> None:
        from plugins.mlx_module.core.config import auto_max_kv_size

        got = auto_max_kv_size(str(self._model_dir(tmp_path, 8192)), total_gb=128)
        assert got == 8192, "the governing value itself must carry the model's limit"

    def test_a_mid_size_model_caps_between_floor_and_tier(self, tmp_path) -> None:
        from plugins.mlx_module.core.config import auto_max_kv_size

        assert auto_max_kv_size(str(self._model_dir(tmp_path, 16384)), total_gb=128) == 16384

    def test_a_sub_floor_model_keeps_the_floor_not_the_limit(self, tmp_path) -> None:
        """A 2048-position model (TinyLlama, phi-2) capped literally would leave
        truncate_messages_to_budget with a NEGATIVE prompt budget (2048 minus the
        default 2048-token reply budget minus the 256 margin) — its degenerate
        branch then keeps only the last message: single-turn amnesia, every turn,
        with no log. The floor wins; such models keep the pre-#965 behaviour
        (the cache rotates on overflow), degraded but conversational."""
        from plugins.mlx_module.core.config import auto_max_kv_size

        got = auto_max_kv_size(str(self._model_dir(tmp_path, 2048)), total_gb=128)
        assert got == 8192, f"a sub-floor model limit must not shrink the KV budget (got {got})"

    def test_the_floor_also_keeps_validate_reachable_only_by_the_user(self, tmp_path) -> None:
        """validate() refuses max_kv_size < 512. Without the floor, a model
        publishing max_position_embeddings=256 would make the auto path build a
        config that fails validation — the plugin silently leaves the registry,
        or a hot-swap is refused with no signal. Only an explicit
        NEXE_MLX_MAX_KV_SIZE may reach that state."""
        from plugins.mlx_module.core.config import auto_max_kv_size

        assert auto_max_kv_size(str(self._model_dir(tmp_path, 256)), total_gb=128) >= 512

    def test_the_cap_survives_a_psutil_failure(self, tmp_path) -> None:
        """The RAM probe failing must not skip the model cap: an early return on
        the fallback path handed every consumer the UNCAPPED number. Both halves
        pinned — a small model gets capped AND a big one gets the untouched
        fallback — so this cannot go green by the fallback merely landing on the
        same number as the cap."""
        broken = MagicMock()
        broken.virtual_memory.side_effect = RuntimeError("boom")
        from plugins.mlx_module.core.config import auto_max_kv_size

        with patch.dict(sys.modules, {"psutil": broken}):
            capped = auto_max_kv_size(str(self._model_dir(tmp_path, 8192)), total_gb=None)
        assert capped == 8192, "the model cap must apply on the psutil-failure path too"

        big = tmp_path / "big"
        big.mkdir()
        import json
        (big / "config.json").write_text(json.dumps({"max_position_embeddings": 262144}))
        with patch.dict(sys.modules, {"psutil": broken}):
            fallback = auto_max_kv_size(str(big), total_gb=None)
        assert fallback == 16384, "a big model must get the documented fallback, uncapped"

    def test_an_empty_text_config_falls_back_to_the_top_level(self, tmp_path) -> None:
        """`text_config: {}` must read the top-level params — the behaviour the
        old `or cfg` gave and the isinstance guard has to preserve."""
        import json

        from plugins.mlx_module.core.config import model_max_positions

        d = tmp_path / "model"
        d.mkdir()
        (d / "config.json").write_text(
            json.dumps({"text_config": {}, "max_position_embeddings": 4096})
        )
        assert model_max_positions(str(d)) == 4096

    def test_a_non_object_config_json_is_treated_as_unreadable(self, tmp_path) -> None:
        """`[]`, `"x"` or `42` are valid JSON and used to reach `.get()` as an
        AttributeError from all three public readers — on a hot-swap that meant
        the model switch was silently skipped."""
        from plugins.mlx_module.core.config import (
            auto_max_kv_size,
            model_kv_bytes_per_token,
            model_max_positions,
        )

        for i, payload in enumerate(("[]", '"x"', "42", "true")):
            d = tmp_path / f"m{i}"
            d.mkdir()
            (d / "config.json").write_text(payload)
            assert model_max_positions(str(d)) is None
            assert model_kv_bytes_per_token(str(d)) == 256 * 1024
            assert auto_max_kv_size(str(d), total_gb=128) == 65536

    def test_the_floor_win_is_announced_as_a_warning(self, tmp_path, caplog) -> None:
        """The one path where we knowingly plan past the model must say so out
        loud — the whole #965 story is that silent context loss is the bug."""
        import logging

        from plugins.mlx_module.core.config import auto_max_kv_size

        model = str(self._model_dir(tmp_path, 2048))
        for ram in (128, 4):
            # ram=4: RAM alone already leaves the result at the floor, so
            # capped == result — gating the warning on `capped < result`
            # silenced it exactly on the 8 GB-class boxes where the rotation
            # bites hardest.
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="plugins.mlx_module.core.config"):
                auto_max_kv_size(model, total_gb=ram)
            assert any(
                "below the 8192 floor" in r.message and "rotate" in r.message
                for r in caplog.records
            ), f"ram={ram}: planning past a sub-floor model must warn — silence here is the #965 bug"

    def test_a_malformed_text_config_does_not_raise(self, tmp_path) -> None:
        """text_config can be truthy and not a dict; .get() on it raised an
        AttributeError that reached the chat request on a hot-swap. Both readers
        of config.json share the guard now."""
        import json

        from plugins.mlx_module.core.config import auto_max_kv_size, model_max_positions

        d = tmp_path / "model"
        d.mkdir()
        (d / "config.json").write_text(json.dumps({"text_config": "not-a-dict"}))
        assert model_max_positions(str(d)) is None
        assert auto_max_kv_size(str(d), total_gb=128) == 65536

    def test_a_big_model_leaves_the_kv_budget_alone(self, tmp_path) -> None:
        """Qwen3.5-9B publishes 262144 positions: there RAM is the real limit."""
        from plugins.mlx_module.core.config import auto_max_kv_size

        assert auto_max_kv_size(str(self._model_dir(tmp_path, 262144)), total_gb=128) == 65536

    def test_a_vlm_nested_config_is_read_too(self, tmp_path) -> None:
        """The production default (Qwen3.5-9B) nests the limit under text_config —
        the branch a flat synthetic config never exercises."""
        from plugins.mlx_module.core.config import auto_max_kv_size

        got = auto_max_kv_size(str(self._model_dir(tmp_path, 8192, nested=True)), total_gb=128)
        assert got == 8192

    def test_an_unreadable_config_falls_back_to_the_ram_budget(self, tmp_path) -> None:
        from plugins.mlx_module.core.config import auto_max_kv_size

        assert auto_max_kv_size(str(tmp_path / "does-not-exist"), total_gb=128) == 65536

    def test_a_boolean_limit_is_refused_not_propagated(self, tmp_path) -> None:
        """JSON true satisfies isinstance(x, int) in Python; min(65536, True) is 1.
        A malformed config must disable the cap, never poison the window."""
        from plugins.mlx_module.core.config import model_max_positions

        d = self._model_dir(tmp_path, True)
        assert model_max_positions(str(d)) is None

    def test_a_float_limit_still_caps(self, tmp_path) -> None:
        """Some configs publish 8192.0; the cap must not silently vanish on a float."""
        from plugins.mlx_module.core.config import auto_max_kv_size, model_max_positions

        d = self._model_dir(tmp_path, 8192.0)
        assert model_max_positions(str(d)) == 8192
        assert auto_max_kv_size(str(d), total_gb=128) == 8192

    def test_the_reporter_passes_the_config_value_through(self) -> None:
        """get_context_window() reports config.max_kv_size as-is: on the auto path
        it is already capped at the source, and an explicit NEXE_MLX_MAX_KV_SIZE
        is the user's word and must be reported as set."""
        mod = MLXModule()
        mod._node = MagicMock()
        mod._node.config.max_kv_size = 65536
        assert mod.get_context_window() == 65536
