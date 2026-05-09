"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_auth_bearer_sidecar.py
Description: P1-SIDECAR-AUTH — require_api_key accepts Authorization: Bearer <key>
             as a sidecar fallback when X-API-Key header is absent.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi.testclient import TestClient


PROTECTED = "/metrics/health"


@pytest.fixture
def bearer_client(app, monkeypatch, admin_api_key):
    """TestClient with base_url=http://localhost (TrustedHostMiddleware compatible)."""
    monkeypatch.setenv("NEXE_DEV_MODE", "false")
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", admin_api_key)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


class TestBearerFallback:
    def test_bearer_token_accepted(self, bearer_client, admin_api_key):
        """Authorization: Bearer <valid_key> without X-API-Key must authenticate."""
        resp = bearer_client.get(
            PROTECTED,
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code not in (401, 403), f"Expected auth to succeed, got {resp.status_code}: {resp.text[:100]}"

    def test_x_api_key_takes_precedence(self, bearer_client, admin_api_key):
        """When both headers present, X-API-Key is used (Bearer is ignored)."""
        resp = bearer_client.get(
            PROTECTED,
            headers={
                "X-API-Key": admin_api_key,
                "Authorization": "Bearer wrong-token",
            },
        )
        assert resp.status_code not in (401, 403)

    def test_bearer_invalid_key_rejected(self, bearer_client):
        """Authorization: Bearer <wrong_key> must be blocked (401/403)."""
        resp = bearer_client.get(
            PROTECTED,
            headers={"Authorization": "Bearer totally-wrong-key"},
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_bearer_wrong_scheme_rejected(self, bearer_client):
        """Authorization: Basic abc (not bearer) must not bypass auth."""
        resp = bearer_client.get(
            PROTECTED,
            headers={"Authorization": "Basic abc123"},
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_no_headers_rejected(self, bearer_client):
        """No auth headers at all must be blocked (regression guard)."""
        resp = bearer_client.get(PROTECTED)
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"
