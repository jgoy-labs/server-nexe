"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_health.py
Description: Live health/status endpoint tests.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import pytest
import httpx


pytestmark = pytest.mark.test_live


class TestHealth:
    """Public health endpoints — no auth required."""

    def test_root(self, client: httpx.Client) -> None:
        r = client.get("/")
        assert r.status_code == 200

    def test_health(self, client: httpx.Client) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") in ("healthy", "degraded", "ok", "operational")

    def test_health_ready(self, client: httpx.Client) -> None:
        r = client.get("/health/ready")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") in ("healthy", "degraded", "unhealthy", "operational")

    def test_health_circuits(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.get("/health/circuits", headers=auth_headers)
        assert r.status_code == 200

    def test_api_info_has_version(self, client: httpx.Client) -> None:
        r = client.get("/api/info")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data or "nexe_version" in data or "name" in data

    def test_admin_system_health(self, client: httpx.Client) -> None:
        r = client.get("/admin/system/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
