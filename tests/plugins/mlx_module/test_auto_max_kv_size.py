"""B004 — the KV window must be budgeted from the REAL model and RAM.

The old ``_auto_max_kv_size`` reserved a flat 20 GB (``max(0, total-20)`` = 0
on any machine under 20 GB → always the floor) and hardcoded the 32B model's
256 KB/token even when loading the 4B (real: 128 KB/token). Result on an
8 GB M1: a 4096-token window (0.5 GB of KV) on a machine where 16384 (2 GB)
works — and the floor is PROVEN too small for normal conversations.

The policy table below is the contract: each row is a pin. The formula
mutants (see the plan, FD-S2 m1–m8) must each kill at least one row.
"""

import json
import os

import pytest

from plugins.mlx_module.core.config import (
    DEFAULT_KV_BYTES_PER_TOKEN,
    MLXConfig,
    auto_max_kv_size,
    model_kv_bytes_per_token,
    model_weights_gb,
)

GB = 1024 ** 3


def make_model_dir(tmp_path, name, layers, kv_heads, head_dim, weights_gb,
                   nested=False, layer_types=None, no_config=False,
                   extra=None):
    """Synthetic MLX model dir: config.json + sparse safetensors (APFS)."""
    d = tmp_path / name
    d.mkdir()
    if not no_config:
        tc = {
            "num_hidden_layers": layers,
            "num_key_value_heads": kv_heads,
            "head_dim": head_dim,
            "num_attention_heads": kv_heads * 4,
            "hidden_size": head_dim * kv_heads * 4,
        }
        if layer_types is not None:
            tc["layer_types"] = layer_types
        if extra:
            tc.update(extra)
        cfg = {"text_config": tc, "model_type": "test_vlm"} if nested else \
            dict(tc, model_type="test")
        (d / "config.json").write_text(json.dumps(cfg))
    if weights_gb:
        f = d / "model.safetensors"
        f.touch()
        os.truncate(f, int(weights_gb * GB))  # sparse: st_size without disk
    return str(d)


QWEN4B = dict(layers=32, kv_heads=4, head_dim=256)     # 128 KB/token
QWEN27B = dict(layers=64, kv_heads=4, head_dim=256)    # 256 KB/token
GEMMA31B = dict(layers=60, kv_heads=16, head_dim=256)  # 960 KB/token naive
_GEMMA_LT = ["sliding_attention"] * 50 + ["full_attention"] * 10


class TestKvBytesPerToken:
    def test_top_level_fields(self, tmp_path):
        p = make_model_dir(tmp_path, "m", 36, 8, 128, 0)
        assert model_kv_bytes_per_token(p) == 2 * 36 * 8 * 128 * 2  # 147456

    def test_nested_text_config(self, tmp_path):
        p = make_model_dir(tmp_path, "m", 36, 8, 128, 0, nested=True)
        assert model_kv_bytes_per_token(p) == 147456

    def test_head_dim_derived_from_hidden_size(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        (d / "config.json").write_text(json.dumps({
            "num_hidden_layers": 32, "num_key_value_heads": 4,
            "hidden_size": 2560, "num_attention_heads": 16,  # → head_dim 160
        }))
        assert model_kv_bytes_per_token(str(d)) == 2 * 32 * 4 * 160 * 2

    def test_mha_fallback_without_kv_heads(self, tmp_path):
        d = tmp_path / "m"
        d.mkdir()
        (d / "config.json").write_text(json.dumps({
            "num_hidden_layers": 4, "num_attention_heads": 8, "head_dim": 64,
        }))
        assert model_kv_bytes_per_token(str(d)) == 2 * 4 * 8 * 64 * 2

    def test_unreadable_config_falls_back(self, tmp_path):
        assert model_kv_bytes_per_token(str(tmp_path / "no")) == \
            DEFAULT_KV_BYTES_PER_TOKEN
        d = tmp_path / "corrupt"
        d.mkdir()
        (d / "config.json").write_text("{not json")
        assert model_kv_bytes_per_token(str(d)) == DEFAULT_KV_BYTES_PER_TOKEN

    def test_absurd_values_hit_sanity_clamp(self, tmp_path):
        p = make_model_dir(tmp_path, "m", 10 ** 6, 4, 256, 0)
        assert model_kv_bytes_per_token(p) == DEFAULT_KV_BYTES_PER_TOKEN

    def test_effective_counts_only_full_attention(self, tmp_path):
        """The RAM guard's realistic figure: 10 full layers of 60."""
        p = make_model_dir(tmp_path, "m", weights_gb=0,
                           layer_types=_GEMMA_LT, **GEMMA31B)
        naive = model_kv_bytes_per_token(p)
        real = model_kv_bytes_per_token(p, effective=True)
        assert naive == 2 * 60 * 16 * 256 * 2      # 983040 — budget figure
        assert real == 2 * 10 * 16 * 256 * 2       # 163840 — guard figure
        assert real < naive

    def test_budget_default_ignores_layer_types(self, tmp_path):
        """The budget is DELIBERATELY the naive worst-case (what a rotating
        cache would store) — layer_types must not shrink it by default."""
        with_lt = make_model_dir(tmp_path, "a", weights_gb=0,
                                 layer_types=_GEMMA_LT, **GEMMA31B)
        without = make_model_dir(tmp_path, "b", weights_gb=0, **GEMMA31B)
        assert model_kv_bytes_per_token(with_lt) == \
            model_kv_bytes_per_token(without)


class TestPolicyTable:
    """The contract: pins per machine/model. Formula mutants die here."""

    @pytest.mark.parametrize(
        ("ram", "spec", "weights", "expected"),
        [
            (8, QWEN4B, 2.83, 16384),      # THE measured point (2026-07-23)
            (16, QWEN4B, 5.54, 32768),     # 9B tier
            (16, QWEN4B, 4.78, 32768),     # 4B-8bit
            (32, QWEN27B, 14.95, 57344),   # budget-limited, no cap/floor —
            #                                kills OS_RESERVE/factor mutants
            (32, GEMMA31B, 31.44, 8192),   # negative budget → floor
            (64, QWEN27B, 14.95, 65536),   # cap
            (64, GEMMA31B, 31.44, 28672),  # worst kv/token of the catalog
            (128, QWEN27B, 14.95, 65536),  # cap
        ],
    )
    def test_policy(self, tmp_path, ram, spec, weights, expected):
        p = make_model_dir(tmp_path, "m", weights_gb=weights, **spec)
        assert auto_max_kv_size(p, total_gb=ram) == expected

    def test_unreadable_model_on_8gb(self, tmp_path):
        """No config.json (weights measurable): 256KB fallback → floor."""
        p = make_model_dir(tmp_path, "m", 0, 0, 0, weights_gb=3.5,
                           no_config=True)
        assert auto_max_kv_size(p, total_gb=8) == 8192

    def test_32768_never_on_8gb(self, tmp_path):
        """Explicitly excluded: 32768 (4 GB of KV) is unmeasured on 8 GB."""
        p = make_model_dir(tmp_path, "tiny", 4, 2, 64, weights_gb=0.1)
        assert auto_max_kv_size(p, total_gb=8) <= 16384


class TestFromEnvWiring:
    def test_env_short_circuits_auto(self, tmp_path, monkeypatch):
        """NEXE_MLX_MAX_KV_SIZE always wins AND auto is never evaluated
        (the old default-arg pattern computed it even with the env set)."""
        import plugins.mlx_module.core.config as cfgmod
        p = make_model_dir(tmp_path, "m", weights_gb=0.1, **QWEN4B)
        monkeypatch.setenv("NEXE_MLX_MODEL", p)
        monkeypatch.setenv("NEXE_MLX_MAX_KV_SIZE", "12345")

        def _boom(*a, **k):  # noqa: ANN001
            raise AssertionError("auto_max_kv_size evaluated with env set")

        monkeypatch.setattr(cfgmod, "auto_max_kv_size", _boom)
        assert MLXConfig.from_env().max_kv_size == 12345

    def test_auto_receives_the_resolved_model_path(self, tmp_path, monkeypatch):
        """Hot-swap contract: from_env derives the window from the model it
        just resolved — switching models recalculates for free."""
        import plugins.mlx_module.core.config as cfgmod
        p = make_model_dir(tmp_path, "m", weights_gb=0.1, **QWEN4B)
        monkeypatch.setenv("NEXE_MLX_MODEL", p)
        monkeypatch.delenv("NEXE_MLX_MAX_KV_SIZE", raising=False)
        seen = {}

        def _spy(path, total_gb=None):  # noqa: ANN001
            seen["path"] = path
            return 4242

        monkeypatch.setattr(cfgmod, "auto_max_kv_size", _spy)
        cfg = MLXConfig.from_env()
        assert cfg.max_kv_size == 4242
        assert seen["path"] == cfg.model_path  # post-__post_init__ path
