"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b7_ollama_url_resolve.py
Description: TDD cec — B7 Ollama URL hardcoded: routes_auth.py ignora NEXE_OLLAMA_HOST.
             4 literals "http://localhost:11434" (L298, L418, L471, L524) han d'usar
             resolve_base_url() de plugins/ollama_module/core/client.py.
             Onada 4.6d / xfail strict pre-fix.

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
    """B7: routes_auth.py ha d'importar i usar resolve_base_url() en lloc de localhost literal.

    Pre-fix: resolve_base_url no s'importa i els 4 punts (L298, L418, L471, L524)
    hardcodegen "http://localhost:11434" ignorant NEXE_OLLAMA_HOST.
    Post-fix: from plugins.ollama_module.core.client import resolve_base_url (o equivalent)
    + usat als 4 URL constructions.

    Revert mental: aplicar fix → resolve_base_url a la font → test PASSA.
    Revert del fix → localhost torna → test FALLA.
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
    """Anti-reg B7: 'localhost:11434' no ha d'aparèixer literalment a routes_auth.py.

    Pin estàtic permanent: detecta si post-fix algú torna a hardcodejar localhost.
    Cobreix els 4 punts: L298 (urllib/api/ps), L418 (httpx/api/tags a _backend_model_exists),
    L471 (httpx/api/tags a set_backend), L524 (httpx/api/chat a set_backend).
    Dev#2 no ha de tocar aquest test — queda com a guard permanent.
    """
    src = _ROUTES_AUTH_FILE.read_text()

    assert "localhost:11434" not in src, (
        "Anti-reg B7: 'localhost:11434' literal present a routes_auth.py — "
        "fix B7 absent o regredit. Tots 4 URL literals han d'usar resolve_base_url()."
    )
