"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_b127_error_persistence.py
Description: B127 — a non-streaming engine error ("Error: ...") must NOT be
            persisted to the session history. Otherwise get_context_messages()
            feeds the error back as an assistant turn and pollutes the context
            of the next request. The HTTP response must still surface the error.

            The error is produced naturally (server_state with no usable engine →
            routes_chat returns "Error: No AI engine available"), so the test
            exercises the real production path, not a mocked return value.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import APIRouter

from starlette.datastructures import State
from starlette.requests import Request as StarletteRequest

from plugins.web_ui_module.core.session_manager import ChatSession


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    from core.dependencies import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _mock_request():
    app_mock = MagicMock()
    app_mock.state = State()
    app_mock.state.i18n = None
    scope = {
        "type": "http", "method": "POST", "path": "/ui/chat",
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 12345),
        "app": app_mock, "state": State(),
    }
    return StarletteRequest(scope)


def _server_state_without_engine():
    """module_manager present but no engine resolves → 'Error: No AI engine available'."""
    registry = MagicMock()
    registry.list_modules.return_value = []
    registry.get_module.return_value = None
    mm = MagicMock()
    mm.registry = registry
    state = MagicMock()
    state.module_manager = mm
    state.project_root = "/tmp"
    return state


def _build_endpoint(session):
    session_mgr = MagicMock()
    session_mgr.get_or_create_session = MagicMock(return_value=session)
    session_mgr._save_session_to_disk = MagicMock()

    mh = MagicMock()
    mh.detect_intent = MagicMock(return_value=("chat", None))
    mh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})

    router = APIRouter()
    from plugins.web_ui_module.api.routes_chat import register_chat_routes
    register_chat_routes(router, session_mgr=session_mgr, require_ui_auth=AsyncMock(return_value=None))
    endpoint = next(r.endpoint for r in router.routes if getattr(r, "path", None) == "/chat")
    return endpoint, mh


async def _call(session):
    endpoint, mh = _build_endpoint(session)
    patches = [
        patch("plugins.web_ui_module.api.routes_chat._get_memory_helper", return_value=mh),
        patch("plugins.web_ui_module.api.routes_chat._compact_session", new=AsyncMock()),
        patch("core.lifespan.get_server_state", return_value=_server_state_without_engine()),
    ]
    for p in patches:
        p.start()
    try:
        return await endpoint(_mock_request(), {"message": "hola"}, None)
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.mark.asyncio
class TestErrorMessagePersistence:
    async def test_error_response_not_persisted_but_returned(self):
        """An 'Error: ...' engine response is surfaced via HTTP but NOT stored."""
        session = ChatSession(session_id="b127")
        result = await _call(session)

        # 1. The HTTP response still surfaces the error to the user.
        assert result["response"].startswith("Error:"), result

        # 2. It must NOT be persisted as an assistant message.
        assistant_errors = [
            m for m in session.messages
            if m["role"] == "assistant" and m["content"].startswith("Error:")
        ]
        assert not assistant_errors, f"Error leaked into session history: {assistant_errors}"

        # 3. It must not pollute the context of the next request.
        ctx = session.get_context_messages()
        assert not any(
            m["role"] == "assistant" and m["content"].startswith("Error:") for m in ctx
        )
