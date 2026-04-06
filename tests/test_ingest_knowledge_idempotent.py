"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_ingest_knowledge_idempotent.py
Description: Tests F7 — ingest_knowledge defaults a nexe_documentation,
             és idempotent (no destructiu) i admet target_collection
             override per casos excepcionals.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_memory_mock(collections_existing=None):
    """Helper: build a MemoryAPI mock with configurable existing collections."""
    existing = set(collections_existing or [])
    mock = MagicMock()
    mock.initialize = AsyncMock()
    mock.collection_exists = AsyncMock(side_effect=lambda name: name in existing)
    mock.create_collection = AsyncMock()
    mock.delete_collection = AsyncMock()
    mock.store = AsyncMock(return_value="doc-id")
    mock.close = AsyncMock()
    return mock


class TestF7DefaultsToDocumentation:
    """The default target collection must be nexe_documentation, never user_knowledge."""

    def test_default_target_collection_constant(self):
        from core.ingest.ingest_knowledge import (
            DOCUMENTATION_COLLECTION,
            USER_KNOWLEDGE_COLLECTION,
        )
        assert DOCUMENTATION_COLLECTION == "nexe_documentation"
        assert USER_KNOWLEDGE_COLLECTION == "user_knowledge"
        assert DOCUMENTATION_COLLECTION != USER_KNOWLEDGE_COLLECTION

    def test_default_writes_to_nexe_documentation(self, tmp_path):
        """When called without target_collection, store() must use nexe_documentation."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "guide.txt").write_text("Some corporate know-how content.")

        mock = _make_memory_mock(collections_existing=set())

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        # All store() calls must target nexe_documentation
        assert mock.store.call_count >= 1
        for call in mock.store.call_args_list:
            assert call.kwargs["collection"] == "nexe_documentation"

    def test_default_creates_only_nexe_documentation(self, tmp_path):
        """create_collection should be called for nexe_documentation, NOT user_knowledge."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.md").write_text("# Doc\n\ncontent")

        mock = _make_memory_mock(collections_existing=set())

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            asyncio.run(ingest_knowledge())

        created = [c.args[0] for c in mock.create_collection.call_args_list]
        assert "nexe_documentation" in created
        assert "user_knowledge" not in created


class TestF7IdempotentNotDestructive:
    """Re-running ingest must NOT wipe existing data in the target collection."""

    def test_existing_collection_not_deleted(self, tmp_path):
        """If nexe_documentation already exists, no delete_collection call."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("content")

        mock = _make_memory_mock(collections_existing={"nexe_documentation"})

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        mock.delete_collection.assert_not_called()
        mock.create_collection.assert_not_called()

    def test_missing_collection_is_created(self, tmp_path):
        """If nexe_documentation is missing, it gets created (and not deleted)."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("content")

        mock = _make_memory_mock(collections_existing=set())

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(ingest_knowledge())

        assert result is True
        mock.delete_collection.assert_not_called()
        mock.create_collection.assert_called_once()
        assert mock.create_collection.call_args.args[0] == "nexe_documentation"

    def test_user_knowledge_pre_existing_docs_not_wiped(self, tmp_path):
        """Even when targeting user_knowledge, existing data is preserved."""
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("content")

        # user_knowledge already exists with 5 hypothetical docs (in production)
        mock = _make_memory_mock(collections_existing={"user_knowledge"})

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(
                ingest_knowledge(target_collection="user_knowledge")
            )

        assert result is True
        mock.delete_collection.assert_not_called()


class TestF7TargetCollectionOverride:
    """target_collection kwarg lets callers override the default destination."""

    def test_override_to_user_knowledge(self, tmp_path):
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("ad-hoc user content")

        mock = _make_memory_mock(collections_existing=set())

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(
                ingest_knowledge(target_collection="user_knowledge")
            )

        assert result is True
        for call in mock.store.call_args_list:
            assert call.kwargs["collection"] == "user_knowledge"

    def test_override_to_custom_collection(self, tmp_path):
        from core.ingest.ingest_knowledge import ingest_knowledge

        knowledge_path = tmp_path / "knowledge"
        knowledge_path.mkdir()
        (knowledge_path / "doc.txt").write_text("plugin content")

        mock = _make_memory_mock(collections_existing=set())

        with patch("memory.memory.api.MemoryAPI", return_value=mock), \
             patch("core.ingest.ingest_knowledge.PROJECT_ROOT", tmp_path):
            result = asyncio.run(
                ingest_knowledge(target_collection="plugin_xyz_kb")
            )

        assert result is True
        created = [c.args[0] for c in mock.create_collection.call_args_list]
        assert created == ["plugin_xyz_kb"]
