"""
Tests per SC08 — POST /ui/lang ha de propagar l'idioma via i18n.set_language(lang).

Bug: routes_auth.py::set_language actualitzava os.environ["NEXE_LANG"] però no cridava
i18n.set_language(lang), de manera que els missatges d'error de l'API quedaven en
l'idioma d'arrencada fins al pròxim reinici.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

import plugins.web_ui_module.api.routes_auth as _mod


def _make_i18n_mock():
    """Crea un mock d'instància i18n amb set_language."""
    mock = MagicMock()
    mock.set_language = MagicMock(return_value=True)
    return mock


def _make_set_language_fn(i18n_mock=None):
    """
    Extreu la funció set_language del router registrat.
    Retorna la coroutine directament per poder cridar-la en tests.
    """
    from fastapi import APIRouter
    router = APIRouter()

    require_ui_auth = AsyncMock(return_value=None)
    session_mgr = MagicMock()

    with patch("plugins.web_ui_module.api.routes_auth.get_i18n", return_value=i18n_mock):
        _mod.register_auth_routes(router, require_ui_auth=require_ui_auth, session_mgr=session_mgr)

    # La funció inner és accessible al router com a route endpoint
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/lang":
            return route.endpoint

    raise RuntimeError("Ruta /lang no trobada al router")


@pytest.mark.asyncio
class TestSetLanguageI18nPropagation:
    async def test_post_lang_calls_i18n_set_language(self):
        """SC08 happy path: POST /lang ca → crida i18n.set_language('ca')."""
        i18n_mock = _make_i18n_mock()

        fn = _make_set_language_fn(i18n_mock)
        result = await fn(body={"lang": "ca"}, _auth=None, i18n=i18n_mock)

        assert result == {"status": "ok", "lang": "ca"}
        i18n_mock.set_language.assert_called_once_with("ca")

    async def test_post_lang_calls_i18n_set_language_es(self):
        """SC08: POST /lang es → crida i18n.set_language('es')."""
        i18n_mock = _make_i18n_mock()

        fn = _make_set_language_fn(i18n_mock)
        result = await fn(body={"lang": "es"}, _auth=None, i18n=i18n_mock)

        assert result == {"status": "ok", "lang": "es"}
        i18n_mock.set_language.assert_called_once_with("es")

    async def test_post_lang_calls_i18n_set_language_en(self):
        """SC08: POST /lang en → crida i18n.set_language('en')."""
        i18n_mock = _make_i18n_mock()

        fn = _make_set_language_fn(i18n_mock)
        result = await fn(body={"lang": "en"}, _auth=None, i18n=i18n_mock)

        assert result == {"status": "ok", "lang": "en"}
        i18n_mock.set_language.assert_called_once_with("en")

    async def test_post_lang_no_i18n_no_crash(self):
        """SC08: si i18n és None (app.state sense i18n), no peta."""
        fn = _make_set_language_fn(i18n_mock=None)
        result = await fn(body={"lang": "ca"}, _auth=None, i18n=None)

        assert result == {"status": "ok", "lang": "ca"}

    async def test_post_lang_updates_env(self):
        """SC08: os.environ['NEXE_LANG'] s'actualitza correctament."""
        i18n_mock = _make_i18n_mock()
        fn = _make_set_language_fn(i18n_mock)

        with patch.dict(os.environ, {}, clear=False):
            await fn(body={"lang": "en"}, _auth=None, i18n=i18n_mock)
            assert os.environ.get("NEXE_LANG") == "en"

    async def test_post_lang_invalid_returns_400(self):
        """SC08: idioma no suportat → HTTPException 400."""
        i18n_mock = _make_i18n_mock()
        fn = _make_set_language_fn(i18n_mock)

        with pytest.raises(HTTPException) as exc_info:
            await fn(body={"lang": "fr"}, _auth=None, i18n=i18n_mock)

        assert exc_info.value.status_code == 400
        i18n_mock.set_language.assert_not_called()

    async def test_post_lang_empty_body_returns_400(self):
        """SC08: body sense 'lang' → HTTPException 400 (string buit no és idioma vàlid)."""
        i18n_mock = _make_i18n_mock()
        fn = _make_set_language_fn(i18n_mock)

        with pytest.raises(HTTPException) as exc_info:
            await fn(body={}, _auth=None, i18n=i18n_mock)

        assert exc_info.value.status_code == 400
        i18n_mock.set_language.assert_not_called()

    async def test_post_lang_whitespace_normalized(self):
        """SC08: idioma amb espais es normalitza (strip + lower)."""
        i18n_mock = _make_i18n_mock()
        fn = _make_set_language_fn(i18n_mock)

        result = await fn(body={"lang": "  CA  "}, _auth=None, i18n=i18n_mock)
        assert result["lang"] == "ca"
        i18n_mock.set_language.assert_called_once_with("ca")

    async def test_post_lang_set_language_returns_false(self):
        """SC08: si i18n.set_language retorna False (idioma sense traduccions),
        l'endpoint retorna OK igualment — el lang ja ha passat whitelist.
        Comportament documentat: error de configuració del servidor, no de l'usuari.
        """
        i18n_mock = _make_i18n_mock()
        i18n_mock.set_language = MagicMock(return_value=False)
        fn = _make_set_language_fn(i18n_mock)

        result = await fn(body={"lang": "ca"}, _auth=None, i18n=i18n_mock)

        assert result == {"status": "ok", "lang": "ca"}
        i18n_mock.set_language.assert_called_once_with("ca")
