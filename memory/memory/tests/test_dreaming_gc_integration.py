"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/tests/test_dreaming_gc_integration.py
Description: Integration tests — DreamingCycle invokes GCDaemon per active user.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch

from memory.memory.config import get_config
from memory.memory.workers.dreaming_cycle import DreamingCycle
from memory.memory.workers.gc_daemon import GCDaemon


def _make_store_with_users(user_ids):
    """Build a fake sqlite_store whose SELECT DISTINCT user_id returns user_ids."""
    store = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [(uid,) for uid in user_ids]
    conn.execute.return_value = cursor
    store._connect.return_value = conn
    return store


class TestDreamingCycleInvokesGC:

    @pytest.mark.asyncio
    async def test_gc_heavy_invokes_gc_daemon_per_user(self):
        """_gc_heavy() calls GCDaemon.run_gc once per distinct active user."""
        store = _make_store_with_users(["alice", "bob", "carol"])
        gc = MagicMock(spec=GCDaemon)
        gc.run_gc.return_value = {
            "user_id": "",
            "episodic_deleted": 0,
            "episodic_scanned": 0,
            "tombstones_expired": 0,
            "budget_enforced": False,
        }

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            vector_index=None,
            gc_daemon=gc,
        )
        await cycle._gc_heavy()

        called_users = [c.args[0] for c in gc.run_gc.call_args_list]
        assert called_users == ["alice", "bob", "carol"]

    @pytest.mark.asyncio
    async def test_gc_heavy_no_users_no_invocations(self):
        """If no active episodic users, GCDaemon.run_gc is never called."""
        store = _make_store_with_users([])
        gc = MagicMock(spec=GCDaemon)

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            gc_daemon=gc,
        )
        await cycle._gc_heavy()

        gc.run_gc.assert_not_called()

    @pytest.mark.asyncio
    async def test_gc_heavy_skipped_when_interval_not_reached(self):
        """With _gc_heavy_every=3, first two invocations are skipped."""
        store = _make_store_with_users(["alice"])
        gc = MagicMock(spec=GCDaemon)
        gc.run_gc.return_value = {
            "episodic_deleted": 0,
            "tombstones_expired": 0,
            "budget_enforced": False,
        }

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            gc_daemon=gc,
        )
        cycle._gc_heavy_every = 3

        await cycle._gc_heavy()  # counter 1 → skip
        await cycle._gc_heavy()  # counter 2 → skip
        await cycle._gc_heavy()  # counter 3 → run

        assert gc.run_gc.call_count == 1

    @pytest.mark.asyncio
    async def test_gc_heavy_logs_pruned_count(self, caplog):
        """When GCDaemon reports deletions, _gc_heavy logs it."""
        import logging
        store = _make_store_with_users(["alice"])
        gc = MagicMock(spec=GCDaemon)
        gc.run_gc.return_value = {
            "episodic_deleted": 5,
            "tombstones_expired": 2,
            "budget_enforced": True,
        }

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            gc_daemon=gc,
        )
        with caplog.at_level(logging.INFO, logger="memory.memory.workers.gc_daemon"):
            await cycle._gc_heavy()

        assert any("5 episodic pruned" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_gc_heavy_survives_per_user_exception(self):
        """An exception on one user does not abort GC for the rest."""
        store = _make_store_with_users(["alice", "bob"])
        gc = MagicMock(spec=GCDaemon)
        gc.run_gc.side_effect = [
            RuntimeError("boom"),
            {
                "episodic_deleted": 1,
                "tombstones_expired": 0,
                "budget_enforced": False,
            },
        ]

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            gc_daemon=gc,
        )
        # Must not raise
        await cycle._gc_heavy()

        assert gc.run_gc.call_count == 2

    @pytest.mark.asyncio
    async def test_gc_heavy_respects_should_stop(self):
        """If _should_stop is set mid-iteration, remaining users are skipped."""
        store = _make_store_with_users(["alice", "bob", "carol"])
        gc = MagicMock(spec=GCDaemon)

        def stop_after_first(user_id):
            cycle._should_stop = True
            return {
                "episodic_deleted": 0,
                "tombstones_expired": 0,
                "budget_enforced": False,
            }
        gc.run_gc.side_effect = stop_after_first

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            gc_daemon=gc,
        )
        await cycle._gc_heavy()

        assert gc.run_gc.call_count == 1

    @pytest.mark.asyncio
    async def test_dreaming_cycle_builds_default_gc_daemon(self):
        """When gc_daemon is not supplied, DreamingCycle creates a default."""
        store = _make_store_with_users([])
        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
        )
        assert isinstance(cycle._gc_daemon, GCDaemon)


class TestRunCycleCallsGCHeavy:

    @pytest.mark.asyncio
    async def test_run_cycle_invokes_gc_heavy(self):
        """The full run_cycle path calls _gc_heavy after _gc_lightweight."""
        store = _make_store_with_users([])  # no users — fastpath
        gc = MagicMock(spec=GCDaemon)

        cycle = DreamingCycle(
            config=get_config("m1_8gb"),
            sqlite_store=store,
            gc_daemon=gc,
        )
        with patch.object(cycle, "_gc_heavy", wraps=cycle._gc_heavy) as spy_heavy, \
             patch.object(cycle, "_gc_lightweight", wraps=cycle._gc_lightweight) as spy_light, \
             patch.object(cycle, "_count_pending", return_value=0), \
             patch.object(cycle, "_process_staging", return_value=None), \
             patch.object(cycle, "_sync_vector_index", return_value=None), \
             patch.object(cycle, "_recover_stuck_leases", return_value=None):
            await cycle.run_cycle()

        assert spy_light.call_count == 1
        assert spy_heavy.call_count == 1
