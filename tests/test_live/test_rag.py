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

    def test_rag_retired_surface_is_gone(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """WS6-01/02: the standalone /rag surface (substring matcher +
        phantom upload) was retired — these routes must NOT come back."""
        for method, path in (
            ("GET", "/rag/files/stats"),
            ("POST", "/rag/search"),
            ("POST", "/rag/document"),
            ("POST", "/rag/upload"),
            ("GET", "/rag/ui"),
        ):
            r = client.request(
                method, path, headers=auth_headers,
                json={"query": "x"} if method == "POST" else None,
                timeout=10.0,
            )
            assert r.status_code in (404, 405), f"{method} {path} → {r.status_code}"
