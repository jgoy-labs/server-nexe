"""Tests for plugins/web_ui_module/api/routes_auth.py — coverage gaps."""
from unittest.mock import patch, MagicMock


class TestGetServerLang:
    def test_returns_string(self):
        from plugins.web_ui_module.api.routes_auth import get_server_lang
        lang = get_server_lang()
        assert isinstance(lang, str)
        assert len(lang) >= 2


class TestMakeRequireUiAuth:
    def test_returns_callable(self):
        from plugins.web_ui_module.api.routes_auth import make_require_ui_auth
        dep = make_require_ui_auth()
        assert callable(dep)

