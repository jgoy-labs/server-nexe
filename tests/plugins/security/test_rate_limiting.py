"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/tests/test_rate_limiting.py
Description: Tests for RateLimitTracker.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from datetime import datetime, timedelta, timezone

from core.security.rate_limiting import RateLimitTracker


class TestRateLimitTracker:
    """Tests for RateLimitTracker."""

    @pytest.mark.asyncio
    async def test_record_request_returns_state(self):
        tracker = RateLimitTracker()
        state = await tracker.record_request("test-id", limit=10, window_seconds=60)
        assert "remaining" in state
        assert "limit" in state
        assert "reset" in state
        assert "used" in state

    @pytest.mark.asyncio
    async def test_first_request_uses_1(self):
        tracker = RateLimitTracker()
        state = await tracker.record_request("test-id", limit=10, window_seconds=60)
        assert state["used"] == 1
        assert state["remaining"] == 9

    @pytest.mark.asyncio
    async def test_multiple_requests_decrement_remaining(self):
        tracker = RateLimitTracker()
        for _ in range(5):
            state = await tracker.record_request("test-id", limit=10, window_seconds=60)
        assert state["used"] == 5
        assert state["remaining"] == 5

    @pytest.mark.asyncio
    async def test_remaining_doesnt_go_below_zero(self):
        tracker = RateLimitTracker()
        for _ in range(15):
            state = await tracker.record_request("over-limit", limit=10, window_seconds=60)
        assert state["remaining"] == 0

    @pytest.mark.asyncio
    async def test_window_reset_when_expired(self):
        tracker = RateLimitTracker()
        await tracker.record_request("reset-id", limit=10, window_seconds=1)
        tracker._counters["reset-id"]["reset"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        state = await tracker.record_request("reset-id", limit=10, window_seconds=60)
        assert state["used"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_old_entries(self):
        tracker = RateLimitTracker()
        await tracker.record_request("id1", limit=10, window_seconds=60)
        await tracker.record_request("id2", limit=10, window_seconds=60)
        tracker._counters["id1"]["reset"] = datetime.now(timezone.utc) - timedelta(hours=2)
        await tracker.cleanup_expired()
        assert "id1" not in tracker._counters
        assert "id2" in tracker._counters

    @pytest.mark.asyncio
    async def test_memory_limit_evicts_expired_at_capacity(self):
        tracker = RateLimitTracker()
        tracker.MAX_TRACKED_IDENTIFIERS = 5

        for i in range(5):
            await tracker.record_request(f"id-{i}", limit=10, window_seconds=60)

        for i in range(3):
            tracker._counters[f"id-{i}"]["reset"] = datetime.now(timezone.utc) - timedelta(seconds=1)

        await tracker.record_request("new-id", limit=10, window_seconds=60)
        assert "new-id" in tracker._counters

    @pytest.mark.asyncio
    async def test_memory_limit_evicts_oldest_when_no_expired(self):
        tracker = RateLimitTracker()
        tracker.MAX_TRACKED_IDENTIFIERS = 5

        for i in range(5):
            await tracker.record_request(f"id-{i}", limit=10, window_seconds=60)

        await tracker.record_request("overflow-id", limit=10, window_seconds=60)
        assert len(tracker._counters) <= tracker.MAX_TRACKED_IDENTIFIERS + 1


class TestDeadHelpersRemoved:
    """A-001: dead decorator factories and the never-registered
    add_rate_limit_headers middleware were removed because they had no
    production call-sites (only docstring examples + tests exercised them).
    Re-adding them without wiring them to real endpoints/middleware would
    resurrect the misleading 'X-RateLimit-* headers: OK' boot log.

    #877 (2026-08-28): DEFAULT_RATE_LIMITS, the 3 identifier helpers,
    rate_limit_tracker and start_rate_limit_cleanup_task joined this list —
    same story, zero production call-sites.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "rate_limit_public",
            "rate_limit_authenticated",
            "rate_limit_admin",
            "rate_limit_health",
            "add_rate_limit_headers",
            "get_rate_limit_stats",
            "DEFAULT_RATE_LIMITS",
            "get_api_key_identifier",
            "get_composite_identifier",
            "get_endpoint_identifier",
            "rate_limit_tracker",
            "start_rate_limit_cleanup_task",
        ],
    )
    def test_dead_helper_is_absent(self, name):
        import core.security.rate_limiting as rl

        assert not hasattr(rl, name), (
            f"{name} was removed as dead code (no production call-site); "
            "wire it to a real endpoint/middleware before re-adding it."
        )
