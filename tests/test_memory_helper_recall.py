"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_memory_helper_recall.py
Description: Unit tests for get_memory_api() and recall_from_memory() in memory_helper.
             Covers Bug A (v1 broken singleton), F1 (warning visibility), F3 (retry).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _reset_memory_helper_globals():
    """Reset module-level singletons between tests."""
    import asyncio as _a
    import plugins.web_ui_module.core.memory_helper as mh
    mh._memory_api_instance = None
    mh._memory_api_init_failed = False
    mh._memory_api_last_failure_ts = None
    mh._memory_init_lock = _a.Lock()


def _reset_v1_global():
    """Reset v1 singleton between tests."""
    import memory.memory.api.v1 as v1
    v1._memory_api = None


# ══════════════════════════════════════════════════════════════════
# F1 — WARNING visibility when v1 singleton fallback fails
# ══════════════════════════════════════════════════════════════════

class TestF1WarningVisibility:
    """
    Bug: logger.debug at memory_helper:279 silences v1 singleton failures.
    Fix: promote to logger.warning so failures surface immediately.
    """

    def setup_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    def teardown_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    @pytest.mark.asyncio
    async def test_v1_singleton_fallback_emits_warning(self, caplog):
        """When v1.get_memory_api() raises, a WARNING must be emitted (not DEBUG)."""
        import logging
        import plugins.web_ui_module.core.memory_helper as mh

        with patch.dict("sys.modules", {"memory.memory.api.v1": None}):
            with caplog.at_level(logging.DEBUG, logger="plugins.web_ui_module.core.memory_helper"):
                try:
                    await mh.get_memory_helper().get_memory_api()
                except Exception:
                    pass

        v1_records = [r for r in caplog.records if "reuse" in r.message.lower() or "v1 singleton" in r.message.lower()]
        assert v1_records, (
            f"Expected a log about v1 singleton fallback. Got: {[r.message for r in caplog.records]}"
        )
        assert v1_records[0].levelno >= logging.WARNING, (
            f"Expected WARNING level, got {v1_records[0].levelname}: {v1_records[0].message}"
        )

    @pytest.mark.asyncio
    async def test_v1_fallback_warning_not_debug_level(self, caplog):
        """The log record level must be WARNING (≥30), not DEBUG (10)."""
        import logging
        import plugins.web_ui_module.core.memory_helper as mh

        with patch.dict("sys.modules", {"memory.memory.api.v1": None}):
            with caplog.at_level(logging.DEBUG, logger="plugins.web_ui_module.core.memory_helper"):
                try:
                    await mh.get_memory_helper().get_memory_api()
                except Exception:
                    pass

        v1_records = [r for r in caplog.records if "reuse" in r.message.lower() or "v1 singleton" in r.message.lower()]
        assert v1_records, f"No v1-singleton log found. Records: {[r.message for r in caplog.records]}"
        assert v1_records[0].levelno >= logging.WARNING, (
            f"Expected WARNING (≥{logging.WARNING}), got {v1_records[0].levelno} ({v1_records[0].levelname})"
        )


# ══════════════════════════════════════════════════════════════════
# BUG A — v1.py broken singleton not returned
# ══════════════════════════════════════════════════════════════════

class TestBugAV1BrokenSingleton:
    """
    Bug A: v1.get_memory_api() sets _memory_api = MemoryAPI() BEFORE initialize().
    If initialize() raises, _memory_api points to an uninitialized object.
    Second call returns this broken object without raising — memory_helper
    thinks it has a valid API and fails later at collection_exists().

    Fix: set _memory_api ONLY after initialize() succeeds.
    """

    def setup_method(self):
        _reset_v1_global()

    def teardown_method(self):
        _reset_v1_global()

    @pytest.mark.asyncio
    async def test_v1_global_stays_none_when_initialize_fails(self):
        """After initialize() raises, v1._memory_api must remain None."""
        import memory.memory.api.v1 as v1

        with patch(
            "memory.memory.api.MemoryAPI.initialize",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fastembed not available"),
        ):
            try:
                await v1.get_memory_api()
            except RuntimeError:
                pass

        assert v1._memory_api is None, (
            f"v1._memory_api should be None after failed init, got: {v1._memory_api!r}"
        )

    @pytest.mark.asyncio
    async def test_v1_second_call_retries_after_failed_init(self):
        """
        After initialize() fails on first call, a second call must retry,
        not return a broken object silently.
        """
        import memory.memory.api.v1 as v1
        call_count = [0]

        async def fake_initialize(self):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient failure")
            self._initialized = True

        with patch("memory.memory.api.MemoryAPI.initialize", new=fake_initialize):
            # First call: fails
            try:
                await v1.get_memory_api()
            except RuntimeError:
                pass
            assert v1._memory_api is None, "After failed init, global must be None"

            # Second call: should retry (not return broken object)
            result = await v1.get_memory_api()
            assert result is not None, "Second call should succeed"
            assert result._initialized is True, "Second call should return initialized API"

    @pytest.mark.asyncio
    async def test_v1_global_set_after_successful_init(self):
        """Normal path: global is set after successful init."""
        import memory.memory.api.v1 as v1

        mock_api = MagicMock()
        mock_api.initialize = AsyncMock(return_value=True)
        mock_api._initialized = True
        mock_api.collection_exists = AsyncMock(return_value=True)

        with patch("memory.memory.api.MemoryAPI", return_value=mock_api):
            result = await v1.get_memory_api()

        assert v1._memory_api is mock_api, "After successful init, global must be set"
        assert result is mock_api


# ══════════════════════════════════════════════════════════════════
# F3 — Retry backoff for _memory_api_init_failed
# ══════════════════════════════════════════════════════════════════

class TestF3RetryBackoff:
    """
    Bug B: _memory_api_init_failed = True is permanent for the process lifetime.
    Any transient failure (Qdrant not ready, fastembed cold start) permanently
    disables RAG for the entire session.

    Fix F3: retry after 60s using _memory_api_last_failure_ts.
    """

    def setup_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    def teardown_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    @pytest.mark.asyncio
    async def test_init_failed_flag_set_on_failure(self):
        """After a failed init, _memory_api_init_failed must be True."""
        import plugins.web_ui_module.core.memory_helper as mh

        with patch.dict("sys.modules", {"memory.memory.api.v1": None}):
            with patch("memory.memory.api.MemoryAPI") as MockAPI:
                mock_instance = MagicMock()
                mock_instance.initialize = AsyncMock(
                    side_effect=RuntimeError("embed model missing")
                )
                MockAPI.return_value = mock_instance
                result = await mh.get_memory_helper().get_memory_api()

        assert result is None
        assert mh._memory_api_init_failed is True

    @pytest.mark.asyncio
    async def test_init_failed_with_no_retry_returns_none_immediately(self):
        """With _memory_api_init_failed=True and recent failure, returns None without retry."""
        import plugins.web_ui_module.core.memory_helper as mh
        mh._memory_api_init_failed = True
        mh._memory_api_last_failure_ts = time.monotonic()  # recent failure

        result = await mh.get_memory_helper().get_memory_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_retry_after_60s_elapsed(self):
        """After 60s since last failure, _memory_api_init_failed is reset inside the lock."""
        import plugins.web_ui_module.core.memory_helper as mh
        mh._memory_api_init_failed = True
        mh._memory_api_last_failure_ts = time.monotonic() - 61.0  # 61s ago — should retry

        mock_api = MagicMock()
        mock_api.initialize = AsyncMock(return_value=True)
        mock_api._initialized = True
        mock_api.collection_exists = AsyncMock(return_value=True)

        with patch.dict("sys.modules", {"memory.memory.api.v1": None}):
            with patch("memory.memory.api.MemoryAPI", return_value=mock_api):
                result = await mh.get_memory_helper().get_memory_api()

        assert result is not None, "After 60s, retry must succeed if init works"
        # Flag reset happens inside the lock — verify post-success state
        assert mh._memory_api_init_failed is False, "Flag must be reset after successful retry"
        assert mh._memory_api_instance is mock_api, "Instance must be cached after retry"

    @pytest.mark.asyncio
    async def test_retry_failure_resets_timestamp(self):
        """If retry also fails, _memory_api_last_failure_ts is updated and flag stays True."""
        import plugins.web_ui_module.core.memory_helper as mh
        old_ts = time.monotonic() - 70.0
        mh._memory_api_init_failed = True
        mh._memory_api_last_failure_ts = old_ts

        with patch.dict("sys.modules", {"memory.memory.api.v1": None}):
            with patch("memory.memory.api.MemoryAPI") as MockAPI:
                mock_instance = MagicMock()
                mock_instance.initialize = AsyncMock(
                    side_effect=RuntimeError("still failing")
                )
                MockAPI.return_value = mock_instance
                result = await mh.get_memory_helper().get_memory_api()

        assert result is None
        assert mh._memory_api_init_failed is True
        assert mh._memory_api_last_failure_ts > old_ts, "Failure timestamp must be updated after retry"

    @pytest.mark.asyncio
    async def test_last_failure_ts_set_on_first_failure(self):
        """On first failure (no previous ts), _memory_api_last_failure_ts is set."""
        import plugins.web_ui_module.core.memory_helper as mh
        assert mh._memory_api_last_failure_ts is None

        with patch.dict("sys.modules", {"memory.memory.api.v1": None}):
            with patch("memory.memory.api.MemoryAPI") as MockAPI:
                mock_instance = MagicMock()
                mock_instance.initialize = AsyncMock(
                    side_effect=RuntimeError("init failure")
                )
                MockAPI.return_value = mock_instance
                await mh.get_memory_helper().get_memory_api()

        assert mh._memory_api_last_failure_ts is not None, "Failure timestamp must be set after first failure"


# ══════════════════════════════════════════════════════════════════
# recall_from_memory — behaviour when API unavailable
# ══════════════════════════════════════════════════════════════════

class TestRecallFromMemoryWhenAPIUnavailable:
    """
    Verifies that recall_from_memory returns the correct failure dict
    when MemoryAPI is not available, without raising.
    """

    def setup_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    def teardown_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    @pytest.mark.asyncio
    async def test_recall_returns_success_false_when_api_none(self):
        """get_memory_api() = None → recall returns {"success": False, "results": []}."""
        import plugins.web_ui_module.core.memory_helper as mh
        mh._memory_api_init_failed = True
        mh._memory_api_last_failure_ts = time.monotonic()  # recent, no retry

        result = await mh.get_memory_helper().recall_from_memory("test query")
        assert result["success"] is False
        assert result["results"] == []
        assert "Memory API not available" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_recall_does_not_raise_when_api_unavailable(self):
        """recall_from_memory must never propagate MemoryAPI exceptions to callers."""
        import plugins.web_ui_module.core.memory_helper as mh
        mh._memory_api_init_failed = True
        mh._memory_api_last_failure_ts = time.monotonic()

        result = await mh.get_memory_helper().recall_from_memory("query")
        assert isinstance(result, dict), "recall must return dict even when API unavailable"


# ══════════════════════════════════════════════════════════════════
# Happy-path coverage: already-cached and v1-reuse paths
# ══════════════════════════════════════════════════════════════════

class TestGetMemoryAPIHappyPaths:
    """Cover the fast-path (already cached) and successful v1 reuse paths."""

    def setup_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    def teardown_method(self):
        _reset_memory_helper_globals()
        _reset_v1_global()

    @pytest.mark.asyncio
    async def test_already_cached_returns_instance_without_reinit(self):
        """If _memory_api_instance is set, get_memory_api returns it immediately."""
        import plugins.web_ui_module.core.memory_helper as mh
        mock_api = MagicMock()
        mh._memory_api_instance = mock_api

        result = await mh.get_memory_helper().get_memory_api()
        assert result is mock_api, "Must return the cached instance without re-init"

    @pytest.mark.asyncio
    async def test_v1_reuse_success_sets_instance(self):
        """When v1.get_memory_api() returns a valid API, instance is cached."""
        import plugins.web_ui_module.core.memory_helper as mh

        mock_api = MagicMock()
        mock_api._initialized = True
        mock_api.collection_exists = AsyncMock(return_value=True)

        mock_v1_module = MagicMock()
        mock_v1_module.get_memory_api = AsyncMock(return_value=mock_api)

        with patch.dict("sys.modules", {"memory.memory.api.v1": mock_v1_module}):
            result = await mh.get_memory_helper().get_memory_api()

        assert result is mock_api, "Must return the API from v1"
        assert mh._memory_api_instance is mock_api, "Must cache the API in the module global"

    @pytest.mark.asyncio
    async def test_v1_reuse_creates_collections_if_missing(self):
        """If v1 API exists but collections are missing, they are created."""
        import plugins.web_ui_module.core.memory_helper as mh

        mock_api = MagicMock()
        mock_api._initialized = True
        mock_api.collection_exists = AsyncMock(return_value=False)
        mock_api.create_collection = AsyncMock(return_value=True)

        mock_v1_module = MagicMock()
        mock_v1_module.get_memory_api = AsyncMock(return_value=mock_api)

        with patch.dict("sys.modules", {"memory.memory.api.v1": mock_v1_module}):
            result = await mh.get_memory_helper().get_memory_api()

        assert result is mock_api
        assert mock_api.create_collection.call_count == 2, (
            "Both personal_memory and user_knowledge must be created"
        )
