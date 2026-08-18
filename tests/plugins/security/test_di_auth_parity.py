"""D-I / #883 — both chat paths share one auth gate.

AAA: primary + secondary with expiry, X-API-Key or Bearer, 429 on both.
The product path (/ui/) must reject an expired primary (it used to accept it).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from plugins.security.core.auth_models import ApiKeyConfig, ApiKeyData
from plugins.web_ui_module.api.routes_auth import make_require_ui_auth

_LOAD = "plugins.security.core.auth_dependencies.load_api_keys"


def _req(host="10.0.0.9"):
    req = MagicMock()
    req.app.state = MagicMock(spec=[])
    req.client.host = host
    req.url.path = "/ui/chat"
    return req


def _cfg(*, primary=None, primary_expires=None, secondary=None, secondary_expires=None):
    return ApiKeyConfig(
        primary=ApiKeyData(key=primary, expires_at=primary_expires) if primary else None,
        secondary=ApiKeyData(key=secondary, expires_at=secondary_expires) if secondary else None,
    )


@pytest.mark.asyncio
async def test_ui_rejects_expired_primary():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    require = make_require_ui_auth()
    with patch(_LOAD, return_value=_cfg(primary="old-key", primary_expires=past)):
        with pytest.raises(HTTPException) as ei:
            await require(_req(), x_api_key="old-key")
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_ui_accepts_valid_secondary_during_rotation():
    future = datetime.now(timezone.utc) + timedelta(days=7)
    require = make_require_ui_auth()
    with patch(
        _LOAD,
        return_value=_cfg(
            primary="new-key",
            secondary="old-key",
            secondary_expires=future,
        ),
    ):
        result = await require(_req(), x_api_key="old-key")
    assert result is None


@pytest.mark.asyncio
async def test_ui_accepts_bearer():
    require = make_require_ui_auth()
    with patch(_LOAD, return_value=_cfg(primary="k")):
        result = await require(_req(), x_api_key=None, authorization="Bearer k")
    assert result is None


@pytest.mark.asyncio
async def test_ui_and_core_share_rate_limit_bucket():
    """A burn-down on /ui/ must 429 on /chat/completions for the same IP."""
    from plugins.security.core.auth_dependencies import require_api_key
    from plugins.security.core.auth_rate_limit import (
        AUTH_FAILURE_LIMIT,
        auth_failures,
    )

    auth_failures.clear()
    require_ui = make_require_ui_auth()
    keys = _cfg(primary="real")
    req = _req(host="8.8.8.8")
    with patch(_LOAD, return_value=keys):
        for _ in range(AUTH_FAILURE_LIMIT):
            with pytest.raises(HTTPException) as ei:
                await require_ui(req, x_api_key="wrong")
            assert ei.value.status_code == 401
        with pytest.raises(HTTPException) as ei:
            await require_api_key(req, x_api_key="wrong", authorization=None)
        assert ei.value.status_code == 429
    auth_failures.clear()


def test_presented_api_key_bearer_and_precedence():
    from plugins.security.core.auth_dependencies import presented_api_key

    assert presented_api_key("x", "Bearer b") == "x"
    assert presented_api_key(None, "Bearer b") == "b"
    assert presented_api_key(None, "Basic abc") is None
    assert presented_api_key(None, None) is None
