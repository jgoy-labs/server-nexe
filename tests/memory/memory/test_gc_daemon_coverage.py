"""Tests for memory/memory/workers/gc_daemon.py — coverage gaps."""
from unittest.mock import MagicMock


class TestGCDaemon:
    def _make_config(self):
        config = MagicMock()
        config.gc.episodic_half_life_days = 60
        config.gc.access_boost_max = 3.0
        config.gc.score_threshold = 0.15
        config.gc.max_entries_per_user = 1000
        return config

    def test_init(self):
        from memory.memory.workers.gc_daemon import GCDaemon
        daemon = GCDaemon(config=self._make_config())
        assert daemon is not None

    def test_calculate_entry_score_fresh(self):
        from memory.memory.workers.gc_daemon import GCDaemon
        daemon = GCDaemon(config=self._make_config())
        score = daemon.calculate_entry_score(
            importance=0.8,
            created_at="2026-05-10T00:00:00+00:00",
            access_count=5,
        )
        assert isinstance(score, float)
        assert score > 0

    def test_calculate_entry_score_old(self):
        from memory.memory.workers.gc_daemon import GCDaemon
        daemon = GCDaemon(config=self._make_config())
        score = daemon.calculate_entry_score(
            importance=0.1,
            created_at="2025-01-01T00:00:00+00:00",
            access_count=0,
        )
        assert isinstance(score, float)
        assert score < 1.0

    def test_calculate_entry_score_invalid_date(self):
        from memory.memory.workers.gc_daemon import GCDaemon
        daemon = GCDaemon(config=self._make_config())
        score = daemon.calculate_entry_score(
            importance=0.5,
            created_at="invalid-date",
        )
        assert isinstance(score, float)
