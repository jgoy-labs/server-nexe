"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_sessions.py
Description: Live session lifecycle tests.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import pytest
import httpx


pytestmark = pytest.mark.test_live


class TestSessions:
    """Session create / list / get / delete lifecycle."""

    def test_session_create(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.post("/ui/session/new", headers=auth_headers, timeout=10.0)
        assert r.status_code == 200, (
            f"Session create returned {r.status_code}: {r.text[:400]}"
        )
        data = r.json()
        session_id = data.get("session_id") or data.get("id")
        assert session_id, f"No session_id in response: {data}"

    def test_session_list(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.get("/ui/sessions", headers=auth_headers, timeout=10.0)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))

    def test_session_lifecycle(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """Create → get → delete."""
        # Create
        create_r = client.post(
            "/ui/session/new", headers=auth_headers, timeout=10.0
        )
        assert create_r.status_code == 200
        data = create_r.json()
        session_id = data.get("session_id") or data.get("id")
        assert session_id

        # Get
        get_r = client.get(
            f"/ui/session/{session_id}", headers=auth_headers, timeout=10.0
        )
        assert get_r.status_code == 200

        # Delete
        del_r = client.delete(
            f"/ui/session/{session_id}", headers=auth_headers, timeout=10.0
        )
        assert del_r.status_code in (200, 204), (
            f"Delete returned {del_r.status_code}: {del_r.text[:200]}"
        )

    def test_session_no_key_returns_401(self, client: httpx.Client) -> None:
        r = client.post("/ui/session/new", timeout=10.0)
        assert r.status_code == 401
