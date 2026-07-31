# -*- coding: utf-8 -*-
"""#845 — NEXE_MLX_MAX_KV_SIZE is a no-op for every model family we ship.

``mlx_lm.models.cache.make_prompt_cache`` delegates to ``model.make_cache()``
whenever the model defines it, and drops ``max_kv_size`` on the floor
(mlx-lm 0.31.3, cache.py:31-32). Measured on this machine 31/07 by running the
module's own path with the real weights loaded:

    Qwen3.5-4B-4bit   → MLX cache created: {'ArraysCache': 24, 'KVCache': 8}
                        · max_kv_size=4096 (model-owned cache — NOT enforced)
    gpt-oss-20b-8bit  → MLX cache created: {'RotatingKVCache': 12, 'KVCache': 12}
                        · max_kv_size=4096 (model-owned cache — NOT enforced)

Neither honours 4096: Qwen3.5 gets plain unbounded KVCache on its attention
layers, gpt-oss gets its own 128-token sliding window. So the 4096 window could
not have been the mechanical cause of the 23/07 degeneration — which is exactly
what the FD-S2 instrumentation was added to settle.

These tests pin the delegation and the instrumentation's verdict, so the day
mlx-lm changes its mind we hear about it instead of assuming.
"""
import importlib

import pytest

from plugins.mlx_module.core.generate_helpers import lookup_prefix_cache


class _FakeCacheManager:
    """Empty manager: every lookup misses, so a cache is always created."""

    def fetch_nearest_cache(self, model_key, tokens):
        return None, list(tokens)


class _ModelWithMakeCache:
    """Qwen3.5/gemma4/gpt-oss shape: the model owns its cache construction."""

    def __init__(self):
        self.layers = [object(), object()]

    def make_cache(self):
        from mlx_lm.models.cache import KVCache
        return [KVCache() for _ in self.layers]


class _ModelWithoutMakeCache:
    """qwen3-style: mlx-lm builds the cache and honours max_kv_size."""

    def __init__(self):
        self.layers = [object(), object()]


class TestMlxLmDelegation:
    """The upstream behaviour this finding is about, against the pinned wheel."""

    def test_max_kv_size_is_ignored_when_the_model_owns_the_cache(self):
        from mlx_lm.models.cache import RotatingKVCache, make_prompt_cache

        cache = make_prompt_cache(_ModelWithMakeCache(), max_kv_size=4096)
        assert not any(isinstance(c, RotatingKVCache) for c in cache), (
            "#845 would be fixed upstream: max_kv_size now reaches a model that "
            "defines make_cache — re-check the finding"
        )

    def test_max_kv_size_is_honoured_without_make_cache(self):
        from mlx_lm.models.cache import RotatingKVCache, make_prompt_cache

        cache = make_prompt_cache(_ModelWithoutMakeCache(), max_kv_size=4096)
        assert all(isinstance(c, RotatingKVCache) for c in cache)
        assert all(c.max_size == 4096 for c in cache)


class TestWhichFamiliesOwnTheirCache:
    """Measured against the installed mlx-lm, not against the finding's text.

    The finding named Qwen3.5/gemma4/gpt-oss and described the fallback as
    covering "qwen3/llama/mistral-style". Llama defines make_cache too
    (llama.py:266) — the no-op is wider than reported.
    """

    @pytest.mark.parametrize("arch", ["qwen3_5", "qwen3_5_moe", "gemma4", "gpt_oss", "llama", "gemma3"])
    def test_family_owns_its_cache_so_the_limit_is_a_no_op(self, arch):
        mod = importlib.import_module(f"mlx_lm.models.{arch}")
        assert hasattr(mod.Model, "make_cache"), (
            f"{arch} no longer defines make_cache — max_kv_size may now apply"
        )

    def test_qwen3_is_the_family_that_still_gets_the_safety_net(self):
        mod = importlib.import_module("mlx_lm.models.qwen3")
        assert not hasattr(mod.Model, "make_cache")


class TestInstrumentationVerdict:
    """FD-S2's log line is the field evidence — it must not lie."""

    def test_model_owned_cache_is_reported_as_not_enforced(self, caplog):
        """Mutation guard: flip `_enforced = not hasattr(...)` to `hasattr(...)`
        and this goes RED — the log would claim the limit is being applied.
        """
        with caplog.at_level("INFO"):
            lookup_prefix_cache(_FakeCacheManager(), "k", [1, 2, 3],
                                _ModelWithMakeCache(), 4096)
        lines = [r.getMessage() for r in caplog.records if "MLX cache created" in r.getMessage()]
        assert lines, caplog.text
        assert "NOT enforced by mlx-lm" in lines[0]
        assert "max_kv_size=4096" in lines[0]

    def test_plain_model_is_reported_as_enforced(self, caplog):
        with caplog.at_level("INFO"):
            lookup_prefix_cache(_FakeCacheManager(), "k", [1, 2, 3],
                                _ModelWithoutMakeCache(), 4096)
        lines = [r.getMessage() for r in caplog.records if "MLX cache created" in r.getMessage()]
        assert lines and "enforced via RotatingKVCache" in lines[0]

    def test_the_log_names_the_real_cache_classes(self, caplog):
        """The counts are what re-attribute a degeneration report: an unbounded
        KVCache and a 4096-token rotating window are different worlds."""
        with caplog.at_level("INFO"):
            lookup_prefix_cache(_FakeCacheManager(), "k", [1, 2, 3],
                                _ModelWithMakeCache(), 4096)
        line = [r.getMessage() for r in caplog.records if "MLX cache created" in r.getMessage()][0]
        assert "'KVCache': 2" in line, line


# ═══════════════════════════════════════════════════════════════════════
# The #843 truncation vice, on the TEXT path.
#
# generate_helpers logged `model_key[:30]` when saving the post-prefill
# cache. len("storage/models/") == 15, so 30 characters never leave the
# model path: two conversations with the same model logged identically.
# This is the exact shape that cost a night of investigating a symptom
# that did not exist on the VLM side (#843, fixed there 31/07).
# ═══════════════════════════════════════════════════════════════════════

class TestPostPrefillLogNamesTheSession:

    def _run(self, model_key, caplog):
        import threading
        from unittest.mock import MagicMock, patch
        from plugins.mlx_module.core.generate_helpers import run_streaming_generation

        tokenizer = MagicMock()
        tokenizer.decode = lambda tids, **kw: "x"
        responses = []
        for _ in range(2):
            r = MagicMock(finish_reason=None, prompt_tokens=1, generation_tokens=1)
            r.text, r.token = "x", 42
            responses.append(r)

        with patch("mlx_lm.stream_generate", return_value=iter(responses)):
            with caplog.at_level("INFO"):
                run_streaming_generation(
                    model=MagicMock(), tokenizer=tokenizer,
                    tokens_to_process=MagicMock(), max_tokens=10,
                    sampler=MagicMock(), cached_kv=MagicMock(),
                    stream_callback=lambda t: None,
                    cache_manager=MagicMock(),
                    model_key=model_key, cache_lookup_tokens=[1, 2, 3],
                    cancel_event=threading.Event(),
                )
        return [r.getMessage() for r in caplog.records
                if "cache saved post-prefill" in r.getMessage()]

    def test_two_sessions_of_the_same_model_are_distinguishable(self, caplog):
        """Mutation guard: log `model_key[:30]` again and this goes RED — both
        lines collapse to 'storage/models/Qwen3.5-9B-MLX-'.
        """
        pytest.importorskip("mlx_lm", reason="mlx-lm is Apple-Silicon only")
        base = "storage/models/Qwen3.5-9B-MLX-4bit"
        first = self._run(f"{base}:aaaaaaaaaaaaaaaa:sessAAAA", caplog)
        caplog.clear()
        second = self._run(f"{base}:bbbbbbbbbbbbbbbb:sessBBBB", caplog)

        assert first and second, (first, second)
        assert first[0] != second[0], f"log cannot tell two sessions apart: {first[0]!r}"
        assert "sessAAAA" in first[0] and "sessBBBB" in second[0], (first, second)

    def test_the_model_name_survives_in_the_log(self, caplog):
        """Readable, not just unique: the operator must still see WHICH model."""
        pytest.importorskip("mlx_lm", reason="mlx-lm is Apple-Silicon only")
        lines = self._run("storage/models/Qwen3.5-9B-MLX-4bit:hash1234:sess0001", caplog)
        assert lines and "Qwen3.5-9B-MLX-4bit" in lines[0], lines
