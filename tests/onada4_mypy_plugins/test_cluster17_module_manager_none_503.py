"""
────────────────────────────────────
Server Nexe
Location: tests/onada4_mypy_plugins/test_cluster17_module_manager_none_503.py
Description: Tests cecs Onada 4.4 — Cluster 17 (module_manager.registry None cross-file).

Cluster 17: routes_chat.py L575/592 i rag_handler.py L57 accedeixen a
`module_manager.registry` sense guard. Si get_server_state().module_manager
és None (startup race o inicialització fallida), AttributeError → absorbida
per except Exception → response_text "Error: ..." → HTTP 200 (NO 503).

Contracte post-fix (Dev#2): si module_manager=None → HTTPException(503).
Ruta calenta del chat (L575 és la primera crida del bloc "intent chat").

Contract pin (anti-regressió, PASSA pre i post): ServerState.module_manager
és Optional (None per defecte), no s'ha endurit com a obligatori post-fix.

Contract TDD (xfail): POST /chat amb module_manager=None → 503 (no 200).

Veure: nat/dev/server-nexe/diari/2026-05/20260504/onada4-mypy-plugins/02-tests.md
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — anti-regressió (PASSA pre i post-fix)
# ──────────────────────────────────────────────────────────────────────────────

def test_server_state_module_manager_is_optional_none_by_default():
    """Anti-regressió Cluster 17: ServerState.module_manager és Optional, None per defecte.

    Pina que post-fix Dev#2 no endurixi module_manager com a Required (no-None).
    L'atribut ha de continuar essent inicialitzat a None al __init__ (set a
    initialize()/lifespan). Si Dev#2 canvia el default a un valor no-None,
    trencaria el contracte de startup (lifespan.py depèn del default None).

    PASSA pre-fix i post-fix.
    """
    from core.lifespan import ServerState

    state = ServerState()
    assert hasattr(state, "module_manager"), (
        "ServerState ha de tenir atribut 'module_manager' — "
        "refactor col·lateral Cluster 17 no hauria d'eliminar-lo."
    )
    assert state.module_manager is None, (
        f"ServerState().module_manager ha de ser None per defecte (Optional), "
        f"obtingut: {state.module_manager!r}. "
        "Si post-fix Dev#2 el canvia a no-None, trenca el contracte de startup."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures per al test HTTP (Cluster 17 xfail)
# ──────────────────────────────────────────────────────────────────────────────

def _build_minimal_chat_app():
    """App FastAPI mínima amb l'endpoint POST /chat registrat."""
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
    """TDD Cluster 17: POST /chat amb module_manager=None ha de retornar HTTP 503.

    Pre-fix: retorna 200 amb {'response': "Error: 'NoneType' object has no attribute
    'registry'", ...} (AttributeError absorbida per except Exception a routes_chat.py).
    Post-fix (Dev#2): guard explícit → HTTPException(503, 'Service unavailable').
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
        f"Esperat HTTP 503 (module_manager=None, guard dev#2), "
        f"obtingut {r.status_code}. Body: {r.text[:200]!r}"
    )
