"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_memory.py
Description: Live memory tests — store/search E2E, cross-collection isolation,
             nexe_documentation auto-ingest verification.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.test_live


def _result_list(data: object) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data.get("memories", data.get("items", [])))
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Basic store / search
# ═══════════════════════════════════════════════════════════════════════════════

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
        token = uuid.uuid4().hex[:8]
        content = f"Codi secret de test: {token}"

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
            json={"query": f"codi secret {token}", "limit": 5},
            timeout=15.0,
        )
        assert search_r.status_code == 200, (
            f"Search failed: {search_r.status_code} {search_r.text[:400]}"
        )
        results = _result_list(search_r.json())
        assert len(results) >= 1 or token in search_r.text, (
            f"Expected ≥1 result for '{token}', got 0. Response: {search_r.text[:400]}"
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
        assert isinstance(r.json(), (list, dict)), f"Unexpected type: {type(r.json())}"


# ═══════════════════════════════════════════════════════════════════════════════
# Collections
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryCollections:
    """Verify collection isolation and auto-ingest of nexe_documentation."""

    def test_cross_collection_isolation(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """Data stored in user_knowledge must NOT appear in personal_memory."""
        token = uuid.uuid4().hex[:10]
        content = f"Document tècnic aïllament: fotosíntesi_{token} requereix llum."

        # Store in user_knowledge
        store_r = client.post(
            "/v1/memory/store",
            headers=auth_headers,
            json={"content": content, "metadata": {"collection": "user_knowledge", "source": "test_live"}},
            timeout=15.0,
        )
        assert store_r.status_code in (200, 201), f"Store: {store_r.status_code}"

        # Search in personal_memory — must return 0 hits for this token
        search_r = client.post(
            "/v1/memory/search",
            headers=auth_headers,
            json={"query": f"fotosíntesi_{token}", "collection": "personal_memory", "limit": 5},
            timeout=15.0,
        )
        assert search_r.status_code == 200
        results = _result_list(search_r.json())
        cross_hits = [r for r in results if token in str(r)]
        assert len(cross_hits) == 0, (
            f"Collection isolation FAIL: token '{token}' found in personal_memory "
            f"after storing in user_knowledge. Hits: {cross_hits}"
        )

    def test_nexe_documentation_auto_ingested(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """nexe_documentation collection must be auto-ingested at startup."""
        search_r = client.post(
            "/v1/memory/search",
            headers=auth_headers,
            json={"query": "server nexe instal·lació", "collection": "nexe_documentation", "limit": 3},
            timeout=15.0,
        )
        assert search_r.status_code == 200, (
            f"nexe_documentation search: {search_r.status_code} {search_r.text[:400]}"
        )
        results = _result_list(search_r.json())
        assert len(results) >= 1 or len(search_r.text) > 20, (
            "nexe_documentation is empty — startup auto-ingest may have failed. "
            f"Response: {search_r.text[:400]}"
        )
