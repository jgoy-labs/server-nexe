"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_memory.py
Description: Live memory store/search E2E tests.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import uuid
import pytest
import httpx


pytestmark = pytest.mark.test_live


class TestMemory:
    """Memory store + search — end-to-end with real Qdrant."""

    def test_memory_health(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.get("/memory/health", headers=auth_headers, timeout=10.0)
        assert r.status_code == 200

    def test_memory_store(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            "/v1/memory/store",
            headers=auth_headers,
            json={
                "content": "El color preferit del Jordi és el blau",
                "metadata": {"source": "test_live", "type": "preference"},
            },
            timeout=15.0,
        )
        assert r.status_code in (200, 201), (
            f"Memory store returned {r.status_code}: {r.text[:400]}"
        )

    def test_memory_store_then_search(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """Store a unique fact and verify it can be retrieved."""
        unique_token = uuid.uuid4().hex[:8]
        content = f"Codi secret de test: {unique_token}"

        store_r = client.post(
            "/v1/memory/store",
            headers=auth_headers,
            json={"content": content, "metadata": {"source": "test_live_e2e"}},
            timeout=15.0,
        )
        assert store_r.status_code in (200, 201), (
            f"Store failed: {store_r.status_code} {store_r.text[:400]}"
        )

        search_r = client.post(
            "/v1/memory/search",
            headers=auth_headers,
            json={"query": f"codi secret {unique_token}", "limit": 5},
            timeout=15.0,
        )
        assert search_r.status_code == 200, (
            f"Search failed: {search_r.status_code} {search_r.text[:400]}"
        )
        results = search_r.json()
        result_list = (
            results if isinstance(results, list)
            else results.get("results", results.get("memories", []))
        )
        assert len(result_list) >= 1, (
            f"Expected ≥1 result for '{unique_token}', got 0. "
            f"Full response: {search_r.text[:400]}"
        )

    def test_memory_search_returns_list(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            "/v1/memory/search",
            headers=auth_headers,
            json={"query": "nexe server test", "limit": 3},
            timeout=15.0,
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict)), f"Unexpected response type: {type(data)}"
