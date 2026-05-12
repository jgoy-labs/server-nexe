"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_rag.py
Description: Live RAG health and search tests.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import pytest
import httpx


pytestmark = pytest.mark.test_live


class TestRag:
    """RAG endpoints — health, info, search."""

    def test_rag_health(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.get("/rag/health", headers=auth_headers, timeout=10.0)
        assert r.status_code == 200

    def test_rag_info(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.get("/rag/info", headers=auth_headers, timeout=10.0)
        assert r.status_code == 200

    def test_rag_files_stats(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.get("/rag/files/stats", headers=auth_headers, timeout=10.0)
        assert r.status_code == 200

    def test_rag_search_returns_list(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """Search may return 0 results if KB is empty — that's valid."""
        r = client.post(
            "/rag/search",
            headers=auth_headers,
            json={"query": "nexe server documentation", "limit": 5},
            timeout=15.0,
        )
        assert r.status_code == 200
        data = r.json()
        results = (
            data if isinstance(data, list)
            else data.get("results", data.get("documents", []))
        )
        assert isinstance(results, list), (
            f"Expected list of results, got: {type(data)}"
        )
