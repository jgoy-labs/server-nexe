"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/providers/connection.py
Description: Connection test for an external provider, separate from chat.
    It sends ONE cheap request (GET <endpoint>/v1/models) with no user
    message, no context and no memory, and returns a structured result.

    The key goes into a single request header. It never reaches a result,
    a log line, an exception message or a raw response body: the failure
    reason is a short code (no_key, unauthorized, unreachable, timeout,
    bad_response, http_<status>), and response bodies are never echoed.

    Without a key NO request is made.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from .registry import Provider, get_provider, read_api_key

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0


def _result(provider_key: str, reason: str, status_code: Optional[int] = None) -> Dict[str, Any]:
    ok = reason == "ok"
    if not ok:
        # Provider key + reason code only: the API key never goes in here.
        logger.warning("Provider connection check failed: provider=%s reason=%s", provider_key, reason)
    return {"provider": provider_key, "ok": ok, "reason": reason, "status_code": status_code}


def _classify(response: httpx.Response) -> str:
    """Map a response to a reason code, without ever reading the body into the result."""
    status = response.status_code
    if status in (401, 403):
        return "unauthorized"
    if not 200 <= status < 300:
        return f"http_{status}"
    try:
        payload = response.json()
    except ValueError:
        return "bad_response"
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return "ok"
    return "bad_response"


def _is_header_safe(api_key: str) -> bool:
    """A key that can travel in a header: printable ASCII, no spaces.

    Anything else would either raise (non-ASCII: UnicodeEncodeError, which is
    not an httpx error and would carry the key in its text) or be sent
    unvalidated, so it is rejected before any client is built.
    """
    return api_key.isascii() and api_key.isprintable() and " " not in api_key


#: Public name for the engine, which sends the key in the same single header.
is_header_safe = _is_header_safe


def _request(provider: Provider, api_key: str, timeout: float,
             transport: Optional[httpx.BaseTransport]) -> httpx.Response:
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as client:
        return client.get(
            provider.endpoint.rstrip("/") + provider.models_path,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json",
                     **dict(provider.extra_headers)},
        )


def check_connection(
    provider_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Optional[httpx.BaseTransport] = None,
) -> Dict[str, Any]:
    """Test connectivity and credentials of `provider_key` with one GET.

    Returns {"provider", "ok", "reason", "status_code"}. Reasons: ok, no_key,
    invalid_key (not header-safe), unknown_provider, unauthorized (401/403:
    note a key restricted by scope may be refused on the models listing),
    unreachable, timeout, bad_response, http_<status>. `transport` exists so
    tests can inject a fake endpoint; production passes nothing.
    """
    provider = get_provider(provider_key)
    if provider is None:
        return {"provider": provider_key, "ok": False, "reason": "unknown_provider", "status_code": None}
    api_key = read_api_key(provider)
    if not api_key:
        return _result(provider.key, "no_key")
    if not _is_header_safe(api_key):
        return _result(provider.key, "invalid_key")
    try:
        response = _request(provider, api_key, timeout, transport)
    except httpx.TimeoutException:
        return _result(provider.key, "timeout")
    except httpx.HTTPError:
        # Deliberately not logging/propagating the exception: its text may
        # quote request details.
        return _result(provider.key, "unreachable")
    return _result(provider.key, _classify(response), response.status_code)
