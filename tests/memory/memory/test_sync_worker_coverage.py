"""Tests for memory/memory/workers/sync_worker.py — coverage gaps."""
import pytest
from unittest.mock import MagicMock


class TestSyncWorker:
    def test_init(self):
        from memory.memory.workers.sync_worker import SyncWorker
        worker = SyncWorker(MagicMock(), MagicMock(), MagicMock())
        assert worker is not None

    @pytest.mark.asyncio
    async def test_sync_pending_no_deps(self):
        from memory.memory.workers.sync_worker import SyncWorker
        worker = SyncWorker(None, None, None)
        result = await worker.sync_pending()
        assert result == 0

    @pytest.mark.asyncio
    async def test_sync_pending_vector_unavailable(self):
        from memory.memory.workers.sync_worker import SyncWorker
        mock_vector = MagicMock()
        mock_vector.available = False
        worker = SyncWorker(MagicMock(), mock_vector, MagicMock())
        result = await worker.sync_pending()
        assert result == 0
