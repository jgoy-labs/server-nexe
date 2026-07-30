# -*- coding: utf-8 -*-
"""Tests for the VLM prompt-cache manager and its wiring into the VLM path.

Covers the fix for the historical "the VLM generation path never reused the KV
cache" bug (``cached=0`` on every turn): ``MLXPromptCacheManager`` was only
wired into the text path, so any model detected as VLM (e.g. the Qwen3.5
family) re-prefilled the whole context each turn. The fix keeps one
``mlx_vlm`` ``PromptCacheState`` per session and forwards it to
``mlx_vlm.stream_generate`` via ``_run_vlm_streaming``.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from plugins.mlx_module.core.vlm_cache_manager import (
    VLMPromptCacheManager,
    get_vlm_cache_manager,
)


class TestVLMPromptCacheManager:
    """The per-session state store that enables prefix reuse on the VLM path."""

    def test_get_or_create_reuses_same_state_for_same_key(self):
        mgr = VLMPromptCacheManager(max_sessions=2)
        if not mgr.available:
            pytest.skip("mlx_vlm without PromptCacheState")
        s1 = mgr.get_or_create("model:hashA:sess1")
        s2 = mgr.get_or_create("model:hashA:sess1")
        # Same key → same state object: this is exactly what lets turn N+1
        # reuse turn N's KV cache.
        assert s1 is s2

    def test_different_keys_get_different_states(self):
        mgr = VLMPromptCacheManager(max_sessions=2)
        if not mgr.available:
            pytest.skip("mlx_vlm without PromptCacheState")
        s1 = mgr.get_or_create("model:hashA:sess1")
        # A changed system prompt → different identity_hash → different key.
        s2 = mgr.get_or_create("model:hashB:sess1")
        assert s1 is not s2

    def test_lru_eviction_at_max_sessions(self):
        mgr = VLMPromptCacheManager(max_sessions=1)
        if not mgr.available:
            pytest.skip("mlx_vlm without PromptCacheState")
        first = mgr.get_or_create("k1")
        mgr.get_or_create("k2")  # evicts k1 (max_sessions=1, frees its KV)
        stats = mgr.get_stats()
        assert stats["total"] == 1
        # k1 was evicted → a brand new state is created, not the old one.
        assert mgr.get_or_create("k1") is not first

    def test_invalidate_drops_single_key(self):
        mgr = VLMPromptCacheManager(max_sessions=4)
        if not mgr.available:
            pytest.skip("mlx_vlm without PromptCacheState")
        mgr.get_or_create("k1")
        mgr.get_or_create("k2")
        mgr.invalidate("k1")
        assert mgr.get_stats()["total"] == 1

    def test_clear_drops_all(self):
        mgr = VLMPromptCacheManager(max_sessions=4)
        if not mgr.available:
            pytest.skip("mlx_vlm without PromptCacheState")
        mgr.get_or_create("k1")
        mgr.get_or_create("k2")
        mgr.clear()
        assert mgr.get_stats()["total"] == 0

    def test_max_sessions_floor_is_one(self):
        # Never allow zero — we always keep at least one live cache.
        assert VLMPromptCacheManager(max_sessions=0).max_sessions == 1

    def test_singleton(self):
        assert get_vlm_cache_manager() is get_vlm_cache_manager()


def test_run_vlm_streaming_forwards_prompt_cache_state():
    """Core of the fix: the runner must hand prompt_cache_state to mlx_vlm.

    Before the fix, ``_run_vlm_streaming`` called ``mlx_vlm.stream_generate``
    without any cache state, so mlx_vlm created a fresh cache every turn.
    """
    # mlx-vlm only exists on Apple Silicon (requirements-macos.txt); patch() forces the import.
    pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")
    from plugins.mlx_module.core.chat import MLXChatNode

    node = MLXChatNode.__new__(MLXChatNode)
    node.config = SimpleNamespace(max_tokens=64, model_path="dummy", max_kv_size=4096)

    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield SimpleNamespace(text="hello")

    sentinel = object()
    # _run_vlm_streaming does `from mlx_vlm import stream_generate` at call time,
    # so patching the attribute on the mlx_vlm module is enough.
    with patch("mlx_vlm.stream_generate", fake_stream):
        text, _last = node._run_vlm_streaming(
            model=object(),
            processor=object(),
            formatted_prompt="hi",
            tmp_path=None,
            max_tokens=10,
            stream_callback=lambda _s: None,
            cancel_event=None,
            prompt_cache_state=sentinel,
        )

    assert captured.get("prompt_cache_state") is sentinel
    assert "hello" in text
    # #826: el cap de KV ha de viatjar TAMBÉ pel camí VLM (el camí text ja el
    # passava via make_prompt_cache). Sense aquesta clau, mlx_vlm crea el
    # prompt_cache amb max_kv_size=None → KVCache il·limitat.
    assert captured.get("max_kv_size") == 4096


def test_run_vlm_oneshot_forwards_max_kv_size():
    """#826, camí oneshot: mateix contracte que l'streaming."""
    pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")
    from plugins.mlx_module.core.chat import MLXChatNode

    node = MLXChatNode.__new__(MLXChatNode)
    node.config = SimpleNamespace(max_tokens=64, model_path="dummy", max_kv_size=8192)

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="oneshot")

    with patch("mlx_vlm.generate", fake_generate):
        text, _last = node._run_vlm_oneshot(
            model=object(),
            processor=object(),
            formatted_prompt="hi",
            tmp_path=None,
            max_tokens=10,
        )

    assert captured.get("max_kv_size") == 8192
    assert "oneshot" in text


def test_rotated_rotating_cache_state_is_reset_before_reuse():
    """Review #826 (major): reutilitzar un RotatingKVCache ROTAT corromp el
    prefix (el trim de mlx_vlm assumeix KVCache pla). El guard ha de resetejar
    l'estat només quan hi ha rotació real."""
    pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")
    from plugins.mlx_module.core.chat import MLXChatNode

    RotatingKVCache = type("RotatingKVCache", (), {})
    KVCache = type("KVCache", (), {})

    rotated = RotatingKVCache()
    rotated.offset, rotated.max_size = 30, 16
    state = SimpleNamespace(cache=[rotated], token_ids=[1, 2, 3])
    assert MLXChatNode._reset_rotated_vlm_state(state) is True
    assert state.cache is None and state.token_ids is None

    fresh = RotatingKVCache()
    fresh.offset, fresh.max_size = 8, 16
    state2 = SimpleNamespace(cache=[fresh], token_ids=[1])
    assert MLXChatNode._reset_rotated_vlm_state(state2) is False
    assert state2.cache is not None, "sense rotació el reuse es conserva"

    plain = KVCache()
    plain.offset = 100
    state3 = SimpleNamespace(cache=[plain], token_ids=[1])
    assert MLXChatNode._reset_rotated_vlm_state(state3) is False, (
        "KVCache pla mai es reseteja (el trim hi és correcte)"
    )

    assert MLXChatNode._reset_rotated_vlm_state(SimpleNamespace(cache=None)) is False
    assert MLXChatNode._reset_rotated_vlm_state(object()) is False


def test_vlm_kv_instrumentation_logs_enforcement_verdict(caplog):
    """#826/#845: el log ha de dir si el límit és enforced o si el model l'ignora.

    Qwen3.5 defineix make_cache() propi (a language_model) → mlx_vlm delega i
    IGNORA max_kv_size (#845, FD-S7). La instrumentació deixa el veredicte al
    log perquè la re-atribució de FD-S7 tingui dades.
    """
    import logging

    pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")
    from plugins.mlx_module.core.chat import MLXChatNode

    def _fresh_node():
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = SimpleNamespace(max_tokens=64, model_path="dummy", max_kv_size=4096)
        return node

    def fake_stream(**kwargs):
        yield SimpleNamespace(text="x")

    class _ModelWithOwnCache:
        class language_model:  # noqa: N801 — mimic mlx_vlm attr
            @staticmethod
            def make_cache():
                return []

    with caplog.at_level(logging.INFO, logger="plugins.mlx_module.core.chat"):
        with patch("mlx_vlm.stream_generate", fake_stream):
            _fresh_node()._run_vlm_streaming(
                model=_ModelWithOwnCache(),
                processor=object(),
                formatted_prompt="hi",
                tmp_path=None,
                max_tokens=10,
                stream_callback=lambda _s: None,
                cancel_event=None,
                prompt_cache_state=None,
            )
    owned = [r for r in caplog.records if "MLX VLM cache request" in r.getMessage()]
    assert owned, "cap línia d'instrumentació del camí VLM"
    assert "NOT enforced" in owned[0].getMessage()

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="plugins.mlx_module.core.chat"):
        with patch("mlx_vlm.stream_generate", fake_stream):
            _fresh_node()._run_vlm_streaming(
                model=object(),  # sense language_model.make_cache → enforced
                processor=object(),
                formatted_prompt="hi",
                tmp_path=None,
                max_tokens=10,
                stream_callback=lambda _s: None,
                cancel_event=None,
                prompt_cache_state=None,
            )
    enforced = [r for r in caplog.records if "MLX VLM cache request" in r.getMessage()]
    assert enforced and "enforced via mlx_vlm" in enforced[0].getMessage()
