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


# ═══════════════════════════════════════════════════════════════════════
# #843 — the 8 GB M1 field log read "new cache state → evicted cache state for
# the SAME key immediately". Measured 31/07: the two lines show the same
# text because the log truncated the key at 30 chars, which is still
# inside the model path. The keys were DIFFERENT (identity_hash/session
# live past char 30) — the eviction was key churn against max_sessions=1,
# not a manager that evicts what it just created.
# ═══════════════════════════════════════════════════════════════════════

_MODEL = "storage/models/Qwen3.5-9B-MLX-4bit"


def _key(identity="aaaaaaaaaaaaaaaa", session="sess1234"):
    return f"{_MODEL}:{identity}:{session}"


class TestF843KeyIsLegibleInTheLog:

    def test_two_different_keys_are_distinguishable_in_the_log(self, caplog):
        """The evidence a field capture depends on: two lines for two keys must
        not be byte-identical.

        Mutation guard: log ``model_key[:30]`` again and this goes RED — both
        lines collapse to the model path.
        """
        m = VLMPromptCacheManager(max_sessions=1)
        with caplog.at_level("INFO"):
            m.get_or_create(_key(identity="a" * 16))
            m.get_or_create(_key(identity="b" * 16))
        lines = [r.getMessage() for r in caplog.records]
        news = [ln for ln in lines if "new cache state" in ln]
        assert len(news) == 2, lines
        assert news[0] != news[1], f"log cannot tell two keys apart: {news}"

    def test_the_eviction_line_names_the_key_that_died(self, caplog):
        m = VLMPromptCacheManager(max_sessions=1)
        with caplog.at_level("INFO"):
            m.get_or_create(_key(identity="a" * 16))
            m.get_or_create(_key(identity="b" * 16))
        evicted = [r.getMessage() for r in caplog.records if "evicted" in r.getMessage()]
        assert len(evicted) == 1, evicted
        assert "aaaaaaaa" in evicted[0], evicted
        assert "bbbbbbbb" not in evicted[0], "evicted the wrong key in the log"

    def test_session_is_visible_so_two_sessions_are_told_apart(self, caplog):
        """Same system prompt, two conversations: the log must show which."""
        m = VLMPromptCacheManager(max_sessions=2)
        with caplog.at_level("INFO"):
            m.get_or_create(_key(session="sessAAAA"))
            m.get_or_create(_key(session="sessBBBB"))
        lines = " ".join(r.getMessage() for r in caplog.records)
        assert "sessAAAA" in lines and "sessBBBB" in lines, lines


class TestF843ReuseIsVisible:
    """A field log that only reports creations and evictions cannot prove
    reuse — which is exactly what #843 needed and did not have."""

    def test_reuse_of_the_same_key_is_logged(self, caplog):
        """Mutation guard: drop the reuse log line and this goes RED."""
        m = VLMPromptCacheManager(max_sessions=1)
        m.get_or_create(_key())
        with caplog.at_level("INFO"):
            m.get_or_create(_key())
        lines = [r.getMessage() for r in caplog.records]
        assert any("reuse" in ln.lower() for ln in lines), lines
        assert not any("new cache state" in ln for ln in lines), lines
        assert not any("evicted" in ln for ln in lines), lines

    def test_stable_key_across_turns_never_evicts(self, caplog):
        """The post-FD-S1 shape: identity_hash stable within the day and
        session_id in the key → three turns, one state, zero evictions."""
        m = VLMPromptCacheManager(max_sessions=1)
        with caplog.at_level("INFO"):
            states = [m.get_or_create(_key()) for _ in range(3)]
        assert states[0] is states[1] is states[2]
        assert not [r for r in caplog.records if "evicted" in r.getMessage()]

    def test_churning_key_evicts_every_turn(self, caplog):
        """The pre-FD-S1 shape, reproduced: a key that changes per turn (the
        clock in the system prompt) evicts the previous state every time —
        cached=0 forever, with max_sessions=1."""
        m = VLMPromptCacheManager(max_sessions=1)
        with caplog.at_level("INFO"):
            for turn in range(3):
                m.get_or_create(_key(identity=f"hash{turn:012d}"))
        evictions = [r.getMessage() for r in caplog.records if "evicted" in r.getMessage()]
        assert len(evictions) == 2, evictions
        assert m.get_stats()["total"] == 1


def test_stats_sessions_are_discriminating_too():
    """The MLX status endpoint showed k[:20] — even shorter than the log, so
    two live sessions of the same model were indistinguishable there as well.

    Mutation guard: back to ``k[:20]`` and this goes RED.
    """
    m = VLMPromptCacheManager(max_sessions=2)
    m.get_or_create(_key(session="sessAAAA"))
    m.get_or_create(_key(session="sessBBBB"))
    sessions = m.get_stats()["sessions"]
    assert len(set(sessions)) == 2, sessions


# ═══════════════════════════════════════════════════════════════════════
# max_sessions was configurable on paper only: the singleton applied the
# argument on its FIRST call and chat.py never passed one, so the VLM path
# was permanently pinned at 1 while the text path read
# config.max_session_caches (4, NEXE_MLX_MAX_SESSION_CACHES).
#
# The default STAYS 1: VLM KV caches are heavy and #843 is an 8 GB machine.
# What changes is that a configured value now actually lands.
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def _fresh_singleton():
    """The manager is a process-wide singleton — isolate it per test."""
    import plugins.mlx_module.core.vlm_cache_manager as vcm
    saved = vcm._vlm_cache_manager
    vcm._vlm_cache_manager = None
    yield vcm
    vcm._vlm_cache_manager = saved


class TestVLMMaxSessionsIsConfigurable:

    def test_default_stays_one(self, _fresh_singleton):
        """Prudence first: no env, no argument → the 8 GB behaviour is intact."""
        assert get_vlm_cache_manager().max_sessions == 1

    def test_configured_value_reaches_an_existing_singleton(self, _fresh_singleton):
        """The bug: the first caller froze the limit forever.

        Mutation guard: drop the set_max_sessions call from
        get_vlm_cache_manager and this goes RED — the manager stays at 1.
        """
        assert get_vlm_cache_manager().max_sessions == 1
        assert get_vlm_cache_manager(3).max_sessions == 3

    def test_lowering_the_limit_evicts_the_excess_now(self, _fresh_singleton, caplog):
        """Shrinking must free memory immediately, not on the next turn — the
        whole point on a machine that is short of RAM.

        Mutation guard: make set_max_sessions only assign the attribute and
        this goes RED.
        """
        m = get_vlm_cache_manager(3)
        for i in range(3):
            m.get_or_create(_key(session=f"sess{i:04d}"))
        assert m.get_stats()["total"] == 3
        with caplog.at_level("INFO"):
            get_vlm_cache_manager(1)
        assert m.get_stats()["total"] == 1
        assert m.max_sessions == 1
        assert [r for r in caplog.records if "evicted" in r.getMessage()]

    def test_floor_of_one_survives_a_bad_value(self, _fresh_singleton):
        """0 or negative must not disable caching outright."""
        assert get_vlm_cache_manager(0).max_sessions == 1

    def test_none_leaves_the_current_limit_alone(self, _fresh_singleton):
        """Call sites that do not care (clear()) must not reset the limit."""
        get_vlm_cache_manager(3)
        assert get_vlm_cache_manager().max_sessions == 3


class TestVLMMaxSessionsConfig:

    def test_config_default_is_one(self, monkeypatch):
        from plugins.mlx_module.core.config import MLXConfig
        monkeypatch.delenv("NEXE_MLX_VLM_MAX_SESSION_CACHES", raising=False)
        monkeypatch.setenv("NEXE_MLX_MODEL", "/tmp/fake-model")
        assert MLXConfig.from_env().max_vlm_session_caches == 1

    def test_config_reads_its_own_env(self, monkeypatch):
        """A separate knob from the text path: the VLM cache is far heavier,
        so NEXE_MLX_MAX_SESSION_CACHES=4 must not silently apply here.

        Mutation guard: read NEXE_MLX_MAX_SESSION_CACHES instead and this goes
        RED.
        """
        from plugins.mlx_module.core.config import MLXConfig
        monkeypatch.setenv("NEXE_MLX_MODEL", "/tmp/fake-model")
        monkeypatch.setenv("NEXE_MLX_MAX_SESSION_CACHES", "4")
        monkeypatch.setenv("NEXE_MLX_VLM_MAX_SESSION_CACHES", "2")
        cfg = MLXConfig.from_env()
        assert cfg.max_session_caches == 4
        assert cfg.max_vlm_session_caches == 2

    def test_invalid_env_falls_back_to_one(self, monkeypatch):
        from plugins.mlx_module.core.config import MLXConfig
        monkeypatch.setenv("NEXE_MLX_MODEL", "/tmp/fake-model")
        monkeypatch.setenv("NEXE_MLX_VLM_MAX_SESSION_CACHES", "moltes")
        assert MLXConfig.from_env().max_vlm_session_caches == 1


def test_vlm_path_passes_the_configured_limit():
    """Anti-theatre: the knob above is worthless if _generate_vlm keeps calling
    get_vlm_cache_manager() bare. Source guard — driving _generate_vlm needs a
    loaded VLM model.

    Mutation guard: drop the argument at the call site and this goes RED.
    """
    import inspect
    from plugins.mlx_module.core import chat as chat_mod

    # Whitespace-normalised: the call is wrapped across lines, and a formatter
    # rewrapping it must not fail the guard.
    src = " ".join(inspect.getsource(chat_mod).split())
    assert "get_vlm_cache_manager( self.config.max_vlm_session_caches )" in src \
        or "get_vlm_cache_manager(self.config.max_vlm_session_caches)" in src
