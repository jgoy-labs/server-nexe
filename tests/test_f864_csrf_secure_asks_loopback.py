"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_f864_csrf_secure_asks_loopback.py
Description: #864 — the Secure flag on the CSRF cookie stops consulting the
             localhost-alias list and asks whether the bind host is loopback.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

get_localhost_aliases() served three semantically different comparisons with a
single list: the Host header a client SENDS (middleware.py), the client's REAL
IP (bootstrap.py), and the server's OWN bind host (here). Only the third decides
cookie_secure, and an entry added for either of the other two landed in it too.

Concretely: an operator adds a LAN address to NEXE_LOCALHOST_ALIASES so the
bootstrap IP allowlist accepts that machine, then runs in production bound to
that same address with NEXE_ALLOW_PUBLIC_BIND=1. is_local came out True and the
CSRF cookie went over the network without Secure.

setup_csrf_protection now calls _host_is_loopback(host) — the question the line
was actually asking, already covered by its own tests in core/server/runner.py.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI


def _cookie_secure_of(app: FastAPI):
    """The cookie_secure actually handed to CSRFMiddleware."""
    for mw in app.user_middleware:
        opts = getattr(mw, "kwargs", None) or getattr(mw, "options", {})
        if "cookie_secure" in opts:
            return opts["cookie_secure"]
    raise AssertionError("CSRFMiddleware was never added")


@pytest.fixture()
def prod(monkeypatch):
    monkeypatch.setenv("NEXE_CSRF_SECRET", "test-secret")
    monkeypatch.setenv("NEXE_ENV", "production")


def test_a_lan_bind_keeps_secure_even_if_it_is_an_alias(prod, monkeypatch):
    """The finding, reproduced: alias + public bind used to drop Secure."""
    from core.middleware import setup_csrf_protection

    monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", "192.168.1.50")
    monkeypatch.setenv("NEXE_ALLOW_PUBLIC_BIND", "1")
    app = FastAPI()
    setup_csrf_protection(app, {"core": {"server": {"host": "192.168.1.50"}}})

    assert _cookie_secure_of(app) is True, (
        "the CSRF cookie lost Secure on a production server bound to a routable "
        "address — an entry in NEXE_LOCALHOST_ALIASES (which exists for the "
        "client-IP comparison in bootstrap.py) must not decide this"
    )


def test_binding_every_interface_keeps_secure(prod, monkeypatch):
    """0.0.0.0 reaches the public network; it was never loopback."""
    from core.middleware import setup_csrf_protection

    monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", "0.0.0.0")
    app = FastAPI()
    setup_csrf_protection(app, {"core": {"server": {"host": "0.0.0.0"}}})

    assert _cookie_secure_of(app) is True


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_real_loopback_bind_still_drops_secure(prod, monkeypatch, host):
    """Control: the legitimate reason the flag exists must keep working.

    Without this, the two tests above would pass on a version that simply
    hardcoded True and broke every local HTTP install.
    """
    from core.middleware import setup_csrf_protection

    monkeypatch.delenv("NEXE_LOCALHOST_ALIASES", raising=False)
    app = FastAPI()
    setup_csrf_protection(app, {"core": {"server": {"host": host}}})

    assert _cookie_secure_of(app) is False, (
        f"a server bound to {host} has no TLS and would set an unusable cookie"
    )
