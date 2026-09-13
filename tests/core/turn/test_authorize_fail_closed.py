"""C4.1 — the chat door is fail-closed at both entries, and only the chat door
(#1044).

The scenario is one misconfiguration: a server with `NEXE_DEV_MODE=true` and
**no API key configured at all**, asked from localhost. Until here the two doors
answered it in opposite ways — `/ui/chat` refused with 503, `/v1/chat/completions`
waved the caller through with the `dev-mode-bypass` label — and the 31/08
kickoff decided which one wins:

  «**Auth oposada** en el mateix escenari: A cau a `_check_dev_mode` i pot obrir
  (`auth_dependencies.py:288`); B fa **503 fail-closed** (`:213-222`).
  **Mana la de B.**»

The radius is the point of the second half of this file. `_check_dev_mode` is
NOT touched: a `grep` of `Depends(require_api_key)` outside tests finds ~28
call sites — metrics, bootstrap, system, root, modules and four plugin routers —
and tipping it globally is a different decision. So the administration doors
must still open in exactly the same scenario, and `GET /admin/system/status`
(the harmless one: its siblings are `POST /restart` and `POST /shutdown`) says
so out loud. **If that test goes red, the radius escaped.**

`client=("127.0.0.1", …)`: `_check_dev_mode` only grants the bypass from
loopback (`_is_loopback_ip`), and TestClient's default client host is the
string `"testclient"`, which is not an IP address at all — the tests would then
be measuring a 403 about the source address instead of the policy.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Imported HERE, at module scope, not inside the client helpers — and that is
# load-bearing, not style. `core.endpoints.system` pulls in
# `core.server.process_utils` → `core/server/__init__.py` → `.runner`, whose
# line 30 is a bare `load_dotenv()`: importing it REPOPULATES
# `NEXE_PRIMARY_API_KEY` from the developer's `.env`, undoing the fixture below
# and turning this file's scenario into "a key IS configured" (measured 08/09:
# the admin test answered 401 "Missing API key" instead of 200). At module
# scope the side effect happens once, at collection, and every fixture then
# runs after it.
from core.endpoints.system import router_admin
from core.endpoints.v1 import router_v1
from core.turn.authorize import DEV_MODE_BYPASS, authorize_turn
from core.turn.context import TurnContext

LOOPBACK = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def _no_key_and_dev_mode(monkeypatch):
    """The misconfiguration, exactly: dev mode on, not a single key configured.

    `NEXE_ENV` must not be "production" or `is_dev_mode()` refuses the bypass
    before `_check_dev_mode` is even reached (`auth_config.py:100`), and the
    test would pass for the wrong reason.
    """
    monkeypatch.setenv("NEXE_ENV", "testing")
    monkeypatch.setenv("NEXE_DEV_MODE", "true")
    for name in ("NEXE_PRIMARY_API_KEY", "NEXE_SECONDARY_API_KEY", "NEXE_ADMIN_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    from core.dependencies import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _v1_client() -> TestClient:
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}
    app.include_router(router_v1)
    return TestClient(app, raise_server_exceptions=False, client=LOOPBACK)


def _admin_client() -> TestClient:
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}
    app.include_router(router_admin)
    return TestClient(app, raise_server_exceptions=False, client=LOOPBACK)


# ── the chat door closes ─────────────────────────────────────────────────────

def test_dev_mode_no_longer_opens_the_chat_door() -> None:
    """`NEXE_DEV_MODE=true`, no key, from localhost → 503 on /v1.

    Not 401: nothing is wrong with the request. The SERVER has no key material,
    which is the operator's to fix — and it is the answer /ui/chat has always
    given for the same state.
    """
    with _v1_client() as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hola"}],
                  "stream": False, "use_rag": False},
        )
    assert response.status_code == 503, (
        f"dev mode still opens the chat door: {response.status_code} "
        f"{response.text[:200]}"
    )


def test_the_chat_door_closes_even_with_a_key_presented() -> None:
    """A caller who presents SOMETHING gets the same 503.

    Without this, the test above would also pass on a server that merely
    rejected empty credentials: what closes the door is the server having no
    key material, not the client having no header.
    """
    with _v1_client() as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hola"}],
                  "stream": False, "use_rag": False},
            headers={"X-API-Key": "anything-at-all"},
        )
    assert response.status_code == 503, response.text[:200]


# ── the administration doors stay open: the radius is minimal ────────────────

def test_dev_mode_still_opens_the_admin_doors() -> None:
    """The same scenario, on `GET /admin/system/status` → 200.

    🔴 If this goes red, `_check_dev_mode` was touched after all and #1044 hit
    ~28 endpoints instead of one. Stop and say so; do not merge.
    """
    with _admin_client() as client:
        response = client.get("/admin/system/status")
    assert response.status_code == 200, (
        "the dev-mode bypass stopped working for the administration endpoints "
        f"— the #1044 radius escaped the chat door: {response.status_code} "
        f"{response.text[:200]}"
    )


# ── the step itself ──────────────────────────────────────────────────────────

async def test_authorize_refuses_a_turn_with_no_principal() -> None:
    """Fail-closed means fail-closed: a door that fills nothing is refused too,
    not trusted by omission."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await authorize_turn(TurnContext(turn_id="t", entry="api"))
    assert raised.value.status_code == 503


@pytest.mark.parametrize("principal", ["", "   ", None])
async def test_authorize_refuses_every_empty_shape_of_principal(principal) -> None:
    """An empty string and a blank one are as absent as None."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await authorize_turn(TurnContext(turn_id="t", entry="api", principal=principal))
    assert raised.value.status_code == 503


async def test_authorize_refuses_the_dev_mode_label() -> None:
    """The label `_check_dev_mode` hands out is not a credential."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await authorize_turn(
            TurnContext(turn_id="t", entry="api", principal=DEV_MODE_BYPASS)
        )
    assert raised.value.status_code == 503


async def test_authorize_lets_a_real_principal_through() -> None:
    """Otherwise every test above would pass on a step that refuses everything."""
    await authorize_turn(TurnContext(turn_id="t", entry="api", principal="a-real-key"))


# ── the principal actually travels: auth → request.state → ctx ───────────────

async def test_the_api_dependency_records_the_principal_it_authenticated(monkeypatch) -> None:
    """`require_api_key` used to compute a principal and throw it away
    (`grep -rn 'state.principal'` = 0 before C4.1), which is why `authorize`
    had nothing to read and stayed folded into "the route has a Depends".

    Measured on the real dependency: with a key configured, the value it
    returns is also on `request.state`, where the door reads it.
    """
    from starlette.requests import Request

    from core.security.auth_dependencies import require_api_key

    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "a-configured-key")
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)
    request = Request({
        "type": "http", "method": "POST", "path": "/v1/chat/completions",
        "query_string": b"", "headers": [], "client": LOOPBACK, "state": {},
    })
    returned = await require_api_key(request, "a-configured-key", None)
    assert returned, "the dependency authenticated nobody"
    assert request.state.principal == returned


async def test_the_dev_mode_label_is_the_one_that_travels(monkeypatch) -> None:
    """And in the misconfigured scenario, what lands there is the label the
    `authorize` step refuses — which is what joins the two halves of #1044."""
    from starlette.requests import Request

    from core.security.auth_dependencies import require_api_key

    request = Request({
        "type": "http", "method": "POST", "path": "/v1/chat/completions",
        "query_string": b"", "headers": [], "client": LOOPBACK, "state": {},
    })
    assert await require_api_key(request, None, None) == DEV_MODE_BYPASS
    assert request.state.principal == DEV_MODE_BYPASS
