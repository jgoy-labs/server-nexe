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
    # mlx-vlm només existeix a Apple Silicon (requirements-macos.txt); patch() força l'import.
    pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")
    from plugins.mlx_module.core.chat import MLXChatNode

    node = MLXChatNode.__new__(MLXChatNode)
    node.config = SimpleNamespace(max_tokens=64, model_path="dummy")

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
