"""Tests for plugins/security/core/request_validators.py — coverage gaps."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import HTTPException


class TestValidateContentType:
    """Tests for validate_content_type()."""

    def test_valid_json_content_type(self):
        from plugins.security.core.request_validators import validate_content_type
        assert validate_content_type("application/json") is True

    def test_valid_with_charset(self):
        from plugins.security.core.request_validators import validate_content_type
        assert validate_content_type("application/json; charset=utf-8") is True

    def test_get_without_content_type(self):
        from plugins.security.core.request_validators import validate_content_type
        assert validate_content_type("", method="GET") is True

    def test_invalid_content_type_raises_415(self):
        from plugins.security.core.request_validators import validate_content_type
        with pytest.raises(HTTPException) as exc_info:
            validate_content_type("application/octet-stream")
        assert exc_info.value.status_code == 415

    def test_invalid_content_type_with_security_logger(self):
        from plugins.security.core.request_validators import validate_content_type
        mock_logger = MagicMock()
        mock_request = MagicMock()
        mock_request.app.state.security_logger = mock_logger
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/api/test"

        with pytest.raises(HTTPException):
            validate_content_type("application/octet-stream", request=mock_request)
        mock_logger.log_invalid_content_type.assert_called_once()


class TestValidateCharset:
    """Tests for validate_charset()."""

    def test_no_charset_returns_true(self):
        from plugins.security.core.request_validators import validate_charset
        assert validate_charset("application/json") is True

    def test_valid_charset(self):
        from plugins.security.core.request_validators import validate_charset
        assert validate_charset("application/json; charset=utf-8") is True

    def test_invalid_charset_raises_415(self):
        from plugins.security.core.request_validators import validate_charset
        with pytest.raises(HTTPException) as exc_info:
            validate_charset("application/json; charset=windows-1252")
        assert exc_info.value.status_code == 415

    def test_malformed_charset_raises_400(self):
        from plugins.security.core.request_validators import validate_charset
        with pytest.raises(HTTPException) as exc_info:
            validate_charset("application/json; charset=")
        assert exc_info.value.status_code in (400, 415)


class TestValidateRequestHeaders:
    """Tests for validate_request_headers()."""

    @pytest.mark.asyncio
    async def test_get_request_skips_content_type(self):
        from plugins.security.core.request_validators import validate_request_headers
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.app.state.i18n = None
        result = await validate_request_headers(mock_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_post_with_valid_content_type(self):
        from plugins.security.core.request_validators import validate_request_headers
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {"content-type": "application/json"}
        mock_request.app.state.i18n = None
        result = await validate_request_headers(mock_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_post_without_content_type(self):
        from plugins.security.core.request_validators import validate_request_headers
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {}
        mock_request.app.state.i18n = None
        result = await validate_request_headers(mock_request)
        assert result is True


class TestValidateRequestParams:
    """Tests for validate_request_params()."""

    @pytest.mark.asyncio
    async def test_clean_params_pass(self):
        from plugins.security.core.request_validators import validate_request_params
        mock_request = MagicMock()
        mock_request.query_params = {"q": "hello", "page": "1"}
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/api/search"
        mock_request.app.state.i18n = None
        result = await validate_request_params(mock_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_xss_in_params_raises(self):
        from plugins.security.core.request_validators import validate_request_params
        mock_request = MagicMock()
        mock_request.query_params = {"q": "<script>alert('xss')</script>"}
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/api/search"
        mock_request.app.state.i18n = None
        mock_request.app.state.security_logger = None
        with pytest.raises(HTTPException) as exc_info:
            await validate_request_params(mock_request)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_params_pass(self):
        from plugins.security.core.request_validators import validate_request_params
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/api"
        mock_request.app.state.i18n = None
        result = await validate_request_params(mock_request)
        assert result is True


class TestValidateRequestPath:
    """Tests for validate_request_path()."""

    @pytest.mark.asyncio
    async def test_normal_path_passes(self):
        from plugins.security.core.request_validators import validate_request_path
        mock_request = MagicMock()
        mock_request.url.path = "/api/v1/chat"
        mock_request.app.state.i18n = None
        result = await validate_request_path(mock_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_path_traversal_raises(self):
        from plugins.security.core.request_validators import validate_request_path
        mock_request = MagicMock()
        mock_request.url.path = "/api/../../etc/passwd"
        mock_request.client.host = "127.0.0.1"
        mock_request.app.state.i18n = None
        with pytest.raises(HTTPException) as exc_info:
            await validate_request_path(mock_request)
        assert exc_info.value.status_code == 400


class TestValidateAllRequestInputs:
    """Tests for validate_all_request_inputs()."""

    @pytest.mark.asyncio
    async def test_clean_request_passes(self):
        from plugins.security.core.request_validators import validate_all_request_inputs
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/health"
        mock_request.query_params = {}
        mock_request.client.host = "127.0.0.1"
        mock_request.app.state.i18n = None
        result = await validate_all_request_inputs(mock_request)
        assert result is True
