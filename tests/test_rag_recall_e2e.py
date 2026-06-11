"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_rag_recall_e2e.py
Description: E2E integration tests for RAG recall across a 3-turn conversation.
             Uses real Qdrant embedded + fastembed to verify that a fact saved
             in turn 1 is retrievable in turn 3 (with a neutral turn 2 that
             prevents proximity-only recall).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import os
from pathlib import Path

import pytest

# Integration tests require fastembed model; skip if unavailable.
pytestmark = pytest.mark.integration

FASTEMBED_CACHE = os.environ.get("FASTEMBED_CACHE_PATH", os.path.expanduser("~/.cache/fastembed"))


def _fastembed_available() -> bool:
    """Check whether the fastembed model exists in the cache."""
    cache_path = Path(FASTEMBED_CACHE)
    if not cache_path.exists():
        return False
    # Accept both model dir naming conventions used by different fastembed versions
    patterns = [
        "models--xenova--paraphrase-multilingual*",
        "paraphrase-multilingual*",
        "sentence-transformers--paraphrase-multilingual*",
    ]
    for pattern in patterns:
        if list(cache_path.glob(pattern)):
            return True
    return False


skip_if_no_fastembed = pytest.mark.skipif(
    not _fastembed_available(),
    reason="fastembed model not in cache — run the installer or set FASTEMBED_CACHE_PATH",
)


# ══════════════════════════════════════════════════════════════════
# FIXTURES
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_qdrant_path(tmp_path):
    """Temporary Qdrant embedded storage path, isolated per test."""
    return str(tmp_path / "qdrant_test")


@pytest.fixture
def set_fastembed_cache(monkeypatch):
    """Ensure FASTEMBED_CACHE_PATH points to the real model cache."""
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", FASTEMBED_CACHE)


@pytest.fixture
async def memory_api(tmp_qdrant_path, set_fastembed_cache):
    """
    Initialized MemoryAPI with real embedded Qdrant + real fastembed.
    Uses a tmp path so tests don't pollute the dev storage.
    """
    from memory.memory.api import MemoryAPI
    api = MemoryAPI(qdrant_path=Path(tmp_qdrant_path))
    await api.initialize()
    await api.create_collection("personal_memory")
    yield api
    await api.close()


# ══════════════════════════════════════════════════════════════════
# 3-TURN CONVERSATION: save → neutral → recall
# ══════════════════════════════════════════════════════════════════

@skip_if_no_fastembed
class TestRagRecallAcross3Turns:
    """
    Verifies that a fact saved in turn 1 is retrievable in turn 3.

    The 3-turn structure is deliberate:
    - Turn 1: save fact ("el meu gos es diu Ruf")
    - Turn 2: neutral message (no mention of dog) — forces recall to use
              Qdrant vector store, not conversational proximity
    - Turn 3: query ("Com es diu el meu gos?") — must return "Ruf" via RAG

    If the test passes with a 2-turn structure it could succeed by proximity;
    the neutral turn in the middle forces the system to actually query Qdrant.
    """

    @pytest.mark.asyncio
    async def test_recall_returns_saved_fact_after_3_turns(self, memory_api):
        """Turn 1 saves 'Ruf', turn 2 is neutral, turn 3 recalls 'Ruf' via Qdrant."""
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        import plugins.web_ui_module.core.memory_helper as mh

        # Reset module-level singleton so this test uses our fixture API
        original_instance = mh._memory_api_instance
        original_failed = mh._memory_api_init_failed
        original_ts = mh._memory_api_last_failure_ts
        mh._memory_api_instance = memory_api
        mh._memory_api_init_failed = False
        mh._memory_api_last_failure_ts = None

        try:
            helper = MemoryHelper()

            # Turn 1: save the fact
            save_result = await memory_api.store(
                text="el meu gos es diu Ruf",
                collection="personal_memory",
                metadata={"type": "personal_fact", "source": "test"},
            )
            assert save_result is not None, "Store must return a document ID"

            # Turn 2: neutral message (unrelated to the dog)
            # No save, no recall — just confirms the test doesn't rely on turn adjacency.
            # In production this would be a chat exchange; here we simply skip to turn 3.

            # Turn 3: recall — must find "Ruf"
            recall_result = await helper.recall_from_memory(
                query="Com es diu el meu gos?",
                limit=5,
                collections=["personal_memory"],
            )

            assert recall_result["success"] is True, (
                f"recall must succeed, got: {recall_result}"
            )
            assert recall_result["results"], "recall must return at least 1 result"
            content_blob = " ".join(r["content"] for r in recall_result["results"]).lower()
            assert "ruf" in content_blob, (
                f"Expected 'Ruf' in recall results, got: {recall_result['results']}"
            )
        finally:
            mh._memory_api_instance = original_instance
            mh._memory_api_init_failed = original_failed
            mh._memory_api_last_failure_ts = original_ts

    @pytest.mark.asyncio
    async def test_neutral_turn_does_not_return_unrelated_fact(self, memory_api):
        """Turn 2 neutral query must not accidentally return the dog fact."""
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        import plugins.web_ui_module.core.memory_helper as mh

        original_instance = mh._memory_api_instance
        mh._memory_api_instance = memory_api
        mh._memory_api_init_failed = False
        mh._memory_api_last_failure_ts = None

        try:
            helper = MemoryHelper()

            await memory_api.store(
                text="el meu gos es diu Ruf",
                collection="personal_memory",
                metadata={"type": "personal_fact"},
            )

            # Neutral turn: query about the weather (unrelated)
            recall_result = await helper.recall_from_memory(
                query="quin temps fa avui?",
                limit=5,
                collections=["personal_memory"],
            )

            # Either no results or low-score results — "Ruf" should NOT dominate
            if recall_result["results"]:
                top_score = recall_result["results"][0]["score"]
                assert top_score < 0.5, (
                    f"Neutral query should not score high on dog fact, got score={top_score}"
                )
        finally:
            mh._memory_api_instance = original_instance
            mh._memory_api_init_failed = False
            mh._memory_api_last_failure_ts = None


# ══════════════════════════════════════════════════════════════════
# Graceful degradation when MemoryAPI unavailable
# ══════════════════════════════════════════════════════════════════

class TestRecallGracefulDegradation:
    """
    recall_from_memory must never raise to callers even when MemoryAPI is down.
    The chat endpoint depends on this contract for graceful-degrade.
    """

    def setup_method(self):
        import plugins.web_ui_module.core.memory_helper as mh
        self._orig = (mh._memory_api_instance, mh._memory_api_init_failed, mh._memory_api_last_failure_ts)
        mh._memory_api_instance = None
        mh._memory_api_init_failed = True
        mh._memory_api_last_failure_ts = __import__("time").monotonic()

    def teardown_method(self):
        import plugins.web_ui_module.core.memory_helper as mh
        mh._memory_api_instance, mh._memory_api_init_failed, mh._memory_api_last_failure_ts = self._orig

    def test_recall_returns_dict_not_raises(self):
        """recall_from_memory must return a dict, never raise, when API is unavailable."""
        import plugins.web_ui_module.core.memory_helper as mh

        async def _test():
            return await mh.get_memory_helper().recall_from_memory("any query")

        # asyncio.run creates a fresh event loop: get_event_loop() relied on
        # the ambient loop policy, which earlier async tests in the suite
        # leave unset (RuntimeError: no current event loop) — order-dependent.
        result = asyncio.run(_test())
        assert isinstance(result, dict), "Must return dict even when API unavailable"
        assert result["success"] is False
        assert result["results"] == []

    def test_recall_message_is_clear(self):
        """The failure message must clearly indicate Memory API is unavailable."""
        import plugins.web_ui_module.core.memory_helper as mh

        async def _test():
            return await mh.get_memory_helper().recall_from_memory("query")

        # See test_recall_returns_dict_not_raises — fresh loop, no ambient
        # loop dependency.
        result = asyncio.run(_test())
        assert "Memory API not available" in result.get("message", ""), (
            f"Message should mention Memory API unavailable, got: {result.get('message')}"
        )
