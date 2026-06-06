"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_cleanup_ollama_url_resolve.py
Description: Regression C-001 — cleanup_ollama_startup / cleanup_ollama_shutdown
             must honour the SHARED resolver (_resolve_ollama_url): when only
             OLLAMA_HOST is set (NO NEXE_OLLAMA_HOST, NO sidecar) the cleanup
             requests must target the RESOLVED host, not the localhost default.

             Pre-fix (cleanup llegia NOMÉS NEXE_OLLAMA_HOST): cau a
             localhost:11434 i el test FALLA.
             Post-fix (cleanup usa _resolve_ollama_url): apunta a OLLAMA_HOST
             i el test PASSA.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lifespan_ollama import cleanup_ollama_shutdown, cleanup_ollama_startup

# Custom host that is NOT the localhost:11434 default. C-001 reproduces only
# when OLLAMA_HOST diverges from the hardcoded fallback.
_CUSTOM_HOST = "http://ollama.lan:9999"


@pytest.fixture
def _only_ollama_host(monkeypatch):
    """Set ONLY OLLAMA_HOST; ensure NEXE_OLLAMA_HOST and sidecar are unset.

    This is the standalone scenario described in C-001: a user with a custom
    OLLAMA_HOST but without NEXE_OLLAMA_HOST. The sidecar singleton is reset so
    _resolve_ollama_url() re-reads the env we just monkeypatched.
    """
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.delenv("NEXE_SIDECAR", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", _CUSTOM_HOST)

    from core.sidecar_config import reset_sidecar_config
    reset_sidecar_config()
    yield
    reset_sidecar_config()


def _make_mock_client():
    """Build an httpx.AsyncClient mock whose /api/ps reports one loaded model."""
    ps_resp = MagicMock(status_code=200)
    ps_resp.json.return_value = {"models": [{"name": "llama3.2"}]}

    client = AsyncMock()
    client.__aenter__.return_value.get = AsyncMock(return_value=ps_resp)
    client.__aenter__.return_value.post = AsyncMock(return_value=MagicMock(status_code=200))
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def test_cleanup_startup_targets_resolved_host(_only_ollama_host):
    """C-001: startup cleanup must hit OLLAMA_HOST (resolved), not localhost.

    Pre-fix the startup helper read only NEXE_OLLAMA_HOST → localhost:11434, so
    the /api/ps GET and the unload /api/generate POST would target localhost and
    this assertion FAILS. Post-fix it shares _resolve_ollama_url() → custom host.
    """
    mock_client = _make_mock_client()
    server_state = MagicMock(i18n={})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await cleanup_ollama_startup(
            server_state,
            _translate=lambda *a, **k: "msg",
            health_timeout=5.0,
            unload_timeout=10.0,
        )

    inner = mock_client.__aenter__.return_value
    get_url = inner.get.call_args.args[0]
    post_url = inner.post.call_args.args[0]

    assert get_url == f"{_CUSTOM_HOST}/api/ps", (
        f"C-001: startup health check apunta a {get_url}, no a OLLAMA_HOST resolt "
        f"({_CUSTOM_HOST}) — cleanup ignora OLLAMA_HOST"
    )
    assert post_url == f"{_CUSTOM_HOST}/api/generate", (
        f"C-001: startup unload apunta a {post_url}, no a OLLAMA_HOST resolt "
        f"({_CUSTOM_HOST}) — models quedarien en RAM al host real"
    )
    assert "localhost:11434" not in get_url
    assert "localhost:11434" not in post_url


async def test_cleanup_shutdown_targets_resolved_host(_only_ollama_host):
    """C-001: shutdown cleanup must hit OLLAMA_HOST (resolved), not localhost.

    Pre-fix the shutdown helper read only NEXE_OLLAMA_HOST → localhost:11434, so
    the unload would silently fail and leave models in RAM on the real host;
    this assertion FAILS. Post-fix it shares _resolve_ollama_url() → custom host.
    """
    mock_client = _make_mock_client()

    with patch("httpx.AsyncClient", return_value=mock_client):
        await cleanup_ollama_shutdown(health_timeout=5.0, unload_timeout=10.0)

    inner = mock_client.__aenter__.return_value
    get_url = inner.get.call_args.args[0]
    post_url = inner.post.call_args.args[0]

    assert get_url == f"{_CUSTOM_HOST}/api/ps", (
        f"C-001: shutdown health check apunta a {get_url}, no a OLLAMA_HOST resolt "
        f"({_CUSTOM_HOST}) — cleanup ignora OLLAMA_HOST"
    )
    assert post_url == f"{_CUSTOM_HOST}/api/generate", (
        f"C-001: shutdown unload apunta a {post_url}, no a OLLAMA_HOST resolt "
        f"({_CUSTOM_HOST}) — models quedarien en RAM al host real"
    )
    assert "localhost:11434" not in get_url
    assert "localhost:11434" not in post_url
