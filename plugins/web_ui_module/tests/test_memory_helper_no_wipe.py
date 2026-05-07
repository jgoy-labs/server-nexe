"""
Tests for plugins/web_ui_module/core/memory_helper.py — Fix bug #19a.

Objective: guarantee that the MemoryAPI singleton init NEVER calls
delete_collection() on `personal_memory` or `user_knowledge`,
eliminating the silent wipe that lost user memories.

Architectural decision (approved by Jordi):
"`DEFAULT_VECTOR_SIZE` must always be 768. If there is ever a real mismatch
(corruption, qdrant_client bug), failing at upsert is acceptable;
silently deleting data is NOT."
"""

import inspect
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.web_ui_module.core import memory_helper


class TestNoSilentWipeInSingletonInit:

    def test_get_memory_api_source_has_no_delete_collection(self):
        """Static verification: inside get_memory_api() there must be
        NO reference to delete_collection. This test protects the
        architectural decision against future regressions."""
        src = inspect.getsource(memory_helper.MemoryHelper.get_memory_api)
        assert "delete_collection" not in src, (
            "REGRESSION: get_memory_api() contains delete_collection again. "
            "Architectural decision: personal_memory cannot be deleted during "
            "singleton init. If dims need to be checked, log ERROR and propagate, "
            "NEVER delete+recreate."
        )

    def test_get_memory_api_has_no_dim_mismatch_recreate_pattern(self):
        """Protection against a defensive code pattern that recreates collections
        if the dimension doesn't match. This pattern = time bomb."""
        src = inspect.getsource(memory_helper.MemoryHelper.get_memory_api)
        # Pattern: if dim ... != DEFAULT_VECTOR_SIZE ... delete_collection
        assert not re.search(
            r"dim\s*[!=].*DEFAULT_VECTOR_SIZE.*\n.*delete_collection",
            src,
            re.DOTALL,
        ), "dim-check-delete pattern detected inside get_memory_api"


class TestExistingCollectionsArePreserved:

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Singleton reset to isolate tests."""
        memory_helper._memory_api_instance = None
        memory_helper._memory_api_init_failed = False
        yield
        memory_helper._memory_api_instance = None
        memory_helper._memory_api_init_failed = False

    @pytest.mark.asyncio
    async def test_existing_collection_not_deleted_on_init(self):
        """If `personal_memory` exists with any dimension (even one that
        theoretically does not match DEFAULT_VECTOR_SIZE), the init
        must NOT delete it."""
        mock_api = AsyncMock()
        mock_api.collection_exists = AsyncMock(return_value=True)
        mock_api.delete_collection = AsyncMock()
        mock_api.create_collection = AsyncMock()

        # Qdrant returns anomalous dim — the fix must ignore it
        fake_qdrant = MagicMock()
        fake_qdrant.get_collection.return_value.config.params.vectors.size = 999
        mock_api._qdrant = fake_qdrant

        # Mock the v1 singleton reuse to force the creation path
        with patch(
            "memory.memory.api.v1.get_memory_api",
            side_effect=RuntimeError("skip v1"),
        ), patch("memory.memory.api.MemoryAPI", return_value=mock_api):
            helper = memory_helper.MemoryHelper()
            api = await helper.get_memory_api()

        assert api is mock_api
        assert not mock_api.delete_collection.called, (
            "delete_collection should NEVER have been called during init"
        )
        # create_collection also not called (collection already existed)
        assert not mock_api.create_collection.called

    @pytest.mark.asyncio
    async def test_missing_collection_is_created(self):
        """If `personal_memory` does NOT exist, it must be created (original
        behavior preserved)."""
        mock_api = AsyncMock()
        mock_api.collection_exists = AsyncMock(return_value=False)
        mock_api.delete_collection = AsyncMock()
        mock_api.create_collection = AsyncMock()

        with patch(
            "memory.memory.api.v1.get_memory_api",
            side_effect=RuntimeError("skip v1"),
        ), patch("memory.memory.api.MemoryAPI", return_value=mock_api):
            helper = memory_helper.MemoryHelper()
            await helper.get_memory_api()

        assert not mock_api.delete_collection.called
        # create_collection called for each of the 2 collections
        assert mock_api.create_collection.call_count >= 1
