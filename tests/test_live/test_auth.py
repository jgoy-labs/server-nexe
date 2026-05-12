"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_auth.py
Description: Live auth fail-closed and rate-limit tests.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import pytest
import httpx


pytestmark = pytest.mark.test_live


class TestAuth:
    """Authentication and rate-limiting — fail-closed verification."""

    def test_chat_no_key_returns_401(self, client: httpx.Client) -> None:
        r = client.post("/ui/chat", json={"message": "hello"})
        assert r.status_code == 401, (
            f"Expected 401 without API key, got {r.status_code}: {r.text[:200]}"
        )

    def test_chat_invalid_key_returns_401(self, client: httpx.Client) -> None:
        r = client.post(
            "/ui/chat",
            headers={"X-API-Key": "invalid-key-00000000"},
            json={"message": "hello"},
        )
        assert r.status_code == 401, (
            f"Expected 401 with invalid key, got {r.status_code}: {r.text[:200]}"
        )

    def test_memory_store_no_key_returns_401(self, client: httpx.Client) -> None:
        r = client.post(
            "/v1/memory/store",
            json={"content": "test", "metadata": {}},
        )
        assert r.status_code == 401

    def test_v1_status_no_key_returns_401(self, client: httpx.Client) -> None:
        r = client.get("/status")
        assert r.status_code == 401
