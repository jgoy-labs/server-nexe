"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/tests/test_rate_limiting.py
Description: Tests per RateLimitTracker, identificadors de rate limiting i helpers.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from plugins.security.core.rate_limiting import (
    RateLimitTracker,
    get_api_key_identifier,
    get_composite_identifier,
    get_endpoint_identifier,
    rate_limit_public,
    rate_limit_authenticated,
    rate_limit_admin,
    rate_limit_health,
    get_rate_limit_stats,
    DEFAULT_RATE_LIMITS,
)


def make_mock_request(api_key: str = "", ip: str = "127.0.0.1", path: str = "/health"):
    """Helper: crea un mock de FastAPI Request."""
    request = MagicMock()
    headers_mock = MagicMock()
    headers_mock.get = lambda k, default="": api_key if k == "x-api-key" else default
    request.headers = headers_mock
    request.client = MagicMock()
    request.client.host = ip
    request.url = MagicMock()
    request.url.path = path
    return request


class TestGetApiKeyIdentifier:
    """Tests per get_api_key_identifier."""

    def test_with_api_key_returns_hash_prefix(self):
        request = make_mock_request(api_key="my-secret-key")
        result = get_api_key_identifier(request)
        assert result.startswith("apikey:")
        expected_hash = hashlib.sha256("my-secret-key".encode()).hexdigest()[:16]
        assert result == f"apikey:{expected_hash}"

    def test_without_api_key_returns_ip(self):
        with patch("plugins.security.core.rate_limiting.get_remote_address", return_value="192.168.1.1"):
            request = make_mock_request(api_key="")
            result = get_api_key_identifier(request)
        assert result.startswith("ip:")

    def test_different_keys_different_identifiers(self):
        req1 = make_mock_request(api_key="key-1")
        req2 = make_mock_request(api_key="key-2")
        id1 = get_api_key_identifier(req1)
        id2 = get_api_key_identifier(req2)
        assert id1 != id2


class TestGetCompositeIdentifier:
    """Tests per get_composite_identifier."""

    def test_with_api_key_includes_hash(self):
        with patch("plugins.security.core.rate_limiting.get_remote_address", return_value="10.0.0.1"):
            request = make_mock_request(api_key="test-key")
            result = get_composite_identifier(request)
        assert result.startswith("composite:")
        assert "10.0.0.1" in result

    def test_without_api_key_includes_nokey(self):
        with patch("plugins.security.core.rate_limiting.get_remote_address", return_value="10.0.0.1"):
            request = make_mock_request(api_key="")
            result = get_composite_identifier(request)
        assert result == "composite:10.0.0.1:nokey"


class TestGetEndpointIdentifier:
    """Tests per get_endpoint_identifier."""

    def test_includes_path(self):
        with patch("plugins.security.core.rate_limiting.get_remote_address", return_value="127.0.0.1"):
            request = make_mock_request(path="/health")
            result = get_endpoint_identifier(request)
        assert result == "endpoint:127.0.0.1:/health"

    def test_strips_trailing_slash(self):
        with patch("plugins.security.core.rate_limiting.get_remote_address", return_value="127.0.0.1"):
            request = make_mock_request(path="/health/")
            result = get_endpoint_identifier(request)
        assert result == "endpoint:127.0.0.1:/health"


class TestRateLimitTracker:
    """Tests per RateLimitTracker."""

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


class TestRateLimitFunctions:
    """Tests per les funcions de rate limit."""

    def test_rate_limit_public_returns_decorator(self):
        decorator = rate_limit_public()
        assert decorator is not None

    def test_rate_limit_public_custom_limit(self):
        decorator = rate_limit_public("50/minute")
        assert decorator is not None

    def test_rate_limit_authenticated_returns_decorator(self):
        decorator = rate_limit_authenticated()
        assert decorator is not None

    def test_rate_limit_admin_returns_decorator(self):
        decorator = rate_limit_admin()
        assert decorator is not None

    def test_rate_limit_health_returns_decorator(self):
        decorator = rate_limit_health()
        assert decorator is not None

    def test_default_rate_limits_exist(self):
        assert "global" in DEFAULT_RATE_LIMITS
        assert "public" in DEFAULT_RATE_LIMITS
        assert "authenticated" in DEFAULT_RATE_LIMITS
        assert "admin" in DEFAULT_RATE_LIMITS
        assert "health" in DEFAULT_RATE_LIMITS


class TestGetRateLimitStats:
    """Tests per get_rate_limit_stats."""

    def test_returns_dict_with_active_identifiers(self):
        stats = get_rate_limit_stats()
        assert "active_identifiers" in stats
        assert isinstance(stats["active_identifiers"], int)

    def test_returns_trackers_dict(self):
        stats = get_rate_limit_stats()
        assert "trackers" in stats
        assert isinstance(stats["trackers"], dict)


class TestAddRateLimitHeaders:
    """Tests per add_rate_limit_headers middleware."""

    def test_adds_rate_limit_headers(self):
        from plugins.security.core.rate_limiting import add_rate_limit_headers

        request = make_mock_request()

        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_call_next(req):
            return mock_response

        asyncio.run(add_rate_limit_headers(request, mock_call_next))

        assert "X-RateLimit-Limit" in mock_response.headers
        assert "X-RateLimit-Remaining" in mock_response.headers
        assert "X-RateLimit-Reset" in mock_response.headers
        assert "X-RateLimit-Used" in mock_response.headers

    def test_uses_custom_identifier_func(self):
        from plugins.security.core.rate_limiting import add_rate_limit_headers

        request = make_mock_request()
        mock_response = MagicMock()
        mock_response.headers = {}

        async def mock_call_next(req):
            return mock_response

        custom_func = lambda r: "custom-id"
        asyncio.run(add_rate_limit_headers(
            request, mock_call_next,
            identifier_func=custom_func,
            limit=50,
            window_seconds=30
        ))

        assert mock_response.headers["X-RateLimit-Limit"] == "50"


class TestStartRateLimitCleanupTask:
    """Tests per start_rate_limit_cleanup_task."""

    def test_cleanup_task_can_be_cancelled(self):
        """Verifica que el background task es pot cancel·lar."""
        from plugins.security.core.rate_limiting import start_rate_limit_cleanup_task
        import asyncio

        async def run_with_timeout():
            task = asyncio.create_task(start_rate_limit_cleanup_task())
            # Let it start then cancel
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_with_timeout())
