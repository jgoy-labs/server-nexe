"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b7_ollama_url_resolve.py
Description: Blind TDD — B7 Ollama URL hardcoded: routes_auth.py ignores NEXE_OLLAMA_HOST.
             4 literals "http://localhost:11434" (L298, L418, L471, L524) must use
             resolve_base_url() from plugins/ollama_module/core/client.py.
             / xfail strict pre-fix.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path

_ROUTES_AUTH_FILE = (
    Path(__file__).parents[1]
    / "plugins"
    / "web_ui_module"
    / "api"
    / "routes_auth.py"
)


def test_routes_auth_uses_resolve_base_url():
    """B7: routes_auth.py must import and use resolve_base_url() instead of a localhost literal.

    Pre-fix: resolve_base_url is not imported and the 4 points (L298, L418, L471, L524)
    hardcode "http://localhost:11434" ignoring NEXE_OLLAMA_HOST.
    Post-fix: from plugins.ollama_module.core.client import resolve_base_url (or equivalent)
    + used in the 4 URL constructions.

    Mental revert: apply fix → resolve_base_url in the source → test PASSES.
    Revert of the fix → localhost returns → test FAILS.
    """
    src = _ROUTES_AUTH_FILE.read_text()

    assert "resolve_base_url" in src, (
        "B7: resolve_base_url no importat a routes_auth.py — "
        "NEXE_OLLAMA_HOST ignorat als 4 URL literals (L298, L418, L471, L524)"
    )

    assert "localhost:11434" not in src, (
        "B7: 'localhost:11434' literal present a routes_auth.py — "
        "resolve_base_url() no substitueix els 4 literals hardcoded"
    )


def test_routes_auth_no_localhost_hardcoded():
    """Anti-reg B7: 'localhost:11434' must not appear literally in routes_auth.py.

    Permanent static pin: detects if someone re-hardcodes localhost after the fix.
    Covers the 4 points: L298 (urllib/api/ps), L418 (httpx/api/tags in _backend_model_exists),
    L471 (httpx/api/tags in set_backend), L524 (httpx/api/chat in set_backend).
    dev must not touch this test — remains as a permanent guard.
    """
    src = _ROUTES_AUTH_FILE.read_text()

    assert "localhost:11434" not in src, (
        "Anti-reg B7: 'localhost:11434' literal present a routes_auth.py — "
        "fix B7 absent o regredit. Tots 4 URL literals han d'usar resolve_base_url()."
    )
