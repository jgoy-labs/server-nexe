"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_chat_v1_validation.py
Description: Bug 21 — Verifica que /v1/chat/completions aplica validate_string_input
             als camps string del payload (messages.content, model, engine).
             SQL injection / XSS / etc. han de retornar HTTP 400.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_KEY = "test-v1-validation-key"


def _build_app():
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}

    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from core.endpoints.v1 import router_v1
    app.include_router(router_v1)
    return app


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)


@pytest.fixture
def client():
    app = _build_app()
    with TestClient(app) as c:
        yield c


_HEADERS = {"X-API-Key": API_KEY}


class TestChatV1Validation:
    """Bug 21 — string input validation a /v1/chat/completions."""

    def test_sql_injection_in_message_content_rejected(self, client):
        """Payload SQL injection a messages.content -> 400."""
        payload = {
            "messages": [
                {"role": "user", "content": "' OR '1'='1' UNION SELECT * FROM users--"}
            ],
            "stream": False,
            "use_rag": False,
        }
        r = client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        assert r.status_code == 400, f"Esperat 400 SQLi, rebut {r.status_code}: {r.text}"

    def test_xss_in_message_content_rejected(self, client):
        """Payload XSS a messages.content -> 400."""
        payload = {
            "messages": [
                {"role": "user", "content": "<script>alert('xss')</script>"}
            ],
            "stream": False,
            "use_rag": False,
        }
        r = client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        assert r.status_code == 400

    def test_sql_injection_in_model_field_rejected(self, client):
        payload = {
            "model": "qwen3'; DROP TABLE users;--",
            "messages": [{"role": "user", "content": "hola"}],
            "stream": False,
            "use_rag": False,
        }
        r = client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        assert r.status_code == 400

    def test_oversized_message_rejected(self, client):
        """Missatge > 8000 chars -> 400 (DoS prevention)."""
        payload = {
            "messages": [{"role": "user", "content": "A" * 9000}],
            "stream": False,
            "use_rag": False,
        }
        r = client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        assert r.status_code == 400

    def test_legitimate_message_passes_validation(self, client, monkeypatch):
        """Missatge normal NO ha de ser rebutjat per la validació (pot fallar després per falta d'engine, no per 400 de validació)."""
        payload = {
            "messages": [{"role": "user", "content": "Quina és la capital de Catalunya?"}],
            "stream": False,
            "use_rag": False,
        }
        r = client.post("/v1/chat/completions", json=payload, headers=_HEADERS)
        # No ha de ser 400 per validació. Pot ser 200, 503, 500 etc. segons disponibilitat engine.
        assert r.status_code != 400, f"Validació ha rebutjat input legítim: {r.text}"
