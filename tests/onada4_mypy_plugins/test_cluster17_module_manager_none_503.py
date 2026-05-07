"""
────────────────────────────────────
Server Nexe
Location: tests/onada4_mypy_plugins/test_cluster17_module_manager_none_503.py
Description: Blind tests Onada 4.4 — Cluster 17 (module_manager.registry None cross-file).

Cluster 17: routes_chat.py L575/592 and rag_handler.py L57 access
`module_manager.registry` without a guard. If get_server_state().module_manager
is None (startup race or failed initialization), AttributeError → absorbed
by except Exception → response_text "Error: ..." → HTTP 200 (NOT 503).

Post-fix contract (Dev#2): if module_manager=None → HTTPException(503).
Hot path of chat (L575 is the first call of the "intent chat" block).

Contract pin (anti-regression, PASSES pre and post): ServerState.module_manager
is Optional (None by default), has not been hardened as required post-fix.

Contract TDD (xfail): POST /chat with module_manager=None → 503 (not 200).

See: nat/dev/server-nexe/diari/2026-05/20260504/onada4-mypy-plugins/02-tests.md
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — anti-regression (PASSES pre and post-fix)
# ──────────────────────────────────────────────────────────────────────────────

def test_server_state_module_manager_is_optional_none_by_default():
    """Anti-regression Cluster 17: ServerState.module_manager is Optional, None by default.

    Pins that post-fix Dev#2 does not harden module_manager as Required (non-None).
    The attribute must continue to be initialised to None in __init__ (set at
    initialize()/lifespan). If Dev#2 changes the default to a non-None value,
    it would break the startup contract (lifespan.py depends on the default None).

    PASSES pre-fix and post-fix.
    """
    from core.lifespan import ServerState

    state = ServerState()
    assert hasattr(state, "module_manager"), (
        "ServerState must have attribute 'module_manager' — "
        "collateral refactor Cluster 17 should not remove it."
    )
    assert state.module_manager is None, (
        f"ServerState().module_manager must be None by default (Optional), "
        f"obtained: {state.module_manager!r}. "
        "If post-fix Dev#2 changes it to non-None, it breaks the startup contract."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures for the HTTP test (Cluster 17 xfail)
# ──────────────────────────────────────────────────────────────────────────────

def _build_minimal_chat_app():
    """Minimal FastAPI app with the POST /chat endpoint registered."""
    from fastapi import FastAPI, APIRouter
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler
    from core.dependencies import limiter as _nexe_limiter

    app = FastAPI()
    app.state.limiter = _nexe_limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    async def _noop_auth():
        return None

    mock_session = MagicMock()
    mock_session.id = "test-c17-sess"
    mock_session.messages = []
    mock_session._pending_clear_all = False

    mock_session_mgr = MagicMock()
    mock_session_mgr.get_or_create_session.return_value = mock_session

    router = APIRouter()
    from plugins.web_ui_module.api.routes_chat import register_chat_routes
    register_chat_routes(router, session_mgr=mock_session_mgr, require_ui_auth=_noop_auth)
    app.include_router(router)
    return app


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — xfail TDD: POST /chat module_manager=None → 503
# ──────────────────────────────────────────────────────────────────────────────

def test_chat_endpoint_module_manager_none_returns_503():
    """TDD Cluster 17: POST /chat with module_manager=None must return HTTP 503.

    Pre-fix: returns 200 with {'response': "Error: 'NoneType' object has no attribute
    'registry'", ...} (AttributeError absorbed by except Exception in routes_chat.py).
    Post-fix (Dev#2): explicit guard → HTTPException(503, 'Service unavailable').
    """
    from fastapi.testclient import TestClient

    from core.dependencies import limiter as _nexe_limiter

    mock_state = MagicMock()
    mock_state.module_manager = None

    mock_memory_helper = MagicMock()
    mock_memory_helper.detect_intent.return_value = ("chat", None)
    mock_memory_helper.matches_clear_all_confirm.return_value = False

    app = _build_minimal_chat_app()

    with (
        patch("core.lifespan.get_server_state", return_value=mock_state),
        patch(
            "plugins.web_ui_module.api.routes_chat._get_memory_helper",
            return_value=mock_memory_helper,
        ),
        patch.object(_nexe_limiter, "_check_request_limit"),  # bypass @limiter.limit("20/min") cross-test accumulation
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/chat", json={"message": "hola"})

    assert r.status_code == 503, (
        f"Expected HTTP 503 (module_manager=None, dev#2 guard), "
        f"received {r.status_code}. Body: {r.text[:200]!r}"
    )
