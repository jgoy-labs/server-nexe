"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_cli_ui_shared_pipeline.py
Description: Contracte ARQUITECTÒNIC — el chat del CLI (`nexe chat`) i el del web UI
             comparteixen UN SOL pipeline al servidor (`POST /ui/chat`). Guard
             anti-bifurcació: si algú torna a afegir un camí de chat alternatiu al
             client del CLI, o reanomena la ruta del servidor, o el frontend deixa
             d'apuntar-hi, aquests tests fallen. (Context: 2026-06-20 es va eliminar
             el camí legacy chat_stream/chat_offline que duplicava el pipeline.)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from fastapi import APIRouter


# ── helpers ──────────────────────────────────────────────────────────

def _capture_cli_chat_request():
    """Executa chat_ui_stream amb un httpx fals i captura (mètode, url) reals."""
    from core.cli.utils import api_client

    captured = {}

    class _FakeResp:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_bytes(self):
            return
            yield b""  # pragma: no cover  (generador async buit)

        async def aread(self):
            return b""

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            captured["method"] = method
            captured["url"] = url
            return _FakeResp()

    async def _run():
        client = api_client.NexeAPIClient(base_url="http://test.local")
        async for _ in client.chat_ui_stream("hola", "sess-1"):
            pass

    with patch.object(api_client.httpx, "AsyncClient", _FakeClient):
        asyncio.run(_run())
    return captured


def _server_post_paths():
    """Registra la ruta REAL de chat sobre un router amb el prefix de producció
    (/ui) i retorna el conjunt de paths POST registrats."""
    from plugins.web_ui_module.api.routes_chat import register_chat_routes

    router = APIRouter(prefix="/ui")
    register_chat_routes(router, session_mgr=MagicMock(), require_ui_auth=lambda: None)
    paths = set()
    for r in router.routes:
        methods = getattr(r, "methods", set()) or set()
        if "POST" in methods:
            paths.add(r.path)
    return paths


# ── tests ────────────────────────────────────────────────────────────

class TestCliUiSharedPipeline:
    """El CLI i el web UI han d'usar el MATEIX endpoint de chat."""

    def test_cli_chat_posts_to_ui_chat(self):
        cap = _capture_cli_chat_request()
        assert cap["method"] == "POST"
        assert urlparse(cap["url"]).path == "/ui/chat", (
            f"el CLI ha de POSTejar a /ui/chat, no a {cap['url']}"
        )

    def test_server_registers_ui_chat_post(self):
        paths = _server_post_paths()
        assert "/ui/chat" in paths, f"el servidor ha de registrar POST /ui/chat; té {paths}"

    def test_cli_path_is_a_real_server_route(self):
        """EL contracte: el path que el CLI ataca ÉS una ruta registrada al servidor
        (el mateix pipeline que el web UI). + control que discrimina (un path fals
        NO casa cap ruta → el test té dents)."""
        cli_path = urlparse(_capture_cli_chat_request()["url"]).path
        server_paths = _server_post_paths()
        assert cli_path in server_paths, (
            f"BIFURCACIÓ: el CLI ataca {cli_path} però el servidor no el registra "
            f"({server_paths}). El CLI i el UI han de compartir el pipeline."
        )
        assert "/ui/chatXYZ" not in server_paths, "control: un path fals no ha de casar"

    def test_web_ui_frontend_uses_same_endpoint(self):
        """El frontend del web UI (app.js) també POSTeja a /ui/chat → mateix camí."""
        import plugins.web_ui_module as wu
        app_js = Path(wu.__file__).parent / "ui" / "app.js"
        text = app_js.read_text(encoding="utf-8")
        # String literal real (no una menció en comentari): el frontend fa fetch
        # a /ui/chat amb una crida fetchWithCsrf('/ui/chat', ...).
        assert ("'/ui/chat'" in text) or ('"/ui/chat"' in text), (
            "app.js ha de fer fetch al string literal /ui/chat (mateix endpoint que el CLI)"
        )

    def test_legacy_chat_paths_stay_removed(self):
        """Guard anti-regressió del de-fork (MC-054/055): el client del CLI no pot
        tornar a tenir un segon camí de chat (chat_stream/chat_offline)."""
        from core.cli.utils.api_client import NexeAPIClient
        assert not hasattr(NexeAPIClient, "chat_stream"), (
            "chat_stream (camí legacy /v1/chat/completions) no pot tornar — bifurcaria el pipeline"
        )
        assert not hasattr(NexeAPIClient, "chat_offline"), (
            "chat_offline (stub legacy) no pot tornar"
        )
