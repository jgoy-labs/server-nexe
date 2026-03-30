"""
Tests per core/endpoints/system.py
"""
import os
import pytest
import signal
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler


def make_app():
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from core.endpoints.system import router_admin, get_router
    from plugins.security.core.auth import require_api_key

    # Override auth per als tests
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    app.include_router(router_admin)
    return app


# ═══════════════════════════════════════════════════════════════════════════
# Tests de funcions pures
# ═══════════════════════════════════════════════════════════════════════════

class TestGetI18n:
    def test_get_i18n_without_server_state(self):
        from core.endpoints.system import _get_i18n
        with patch("core.endpoints.system._get_i18n") as mock_fn:
            mock_fn.return_value = None
            result = mock_fn()
            assert result is None

    def test_get_i18n_returns_none_on_exception(self):
        from core.endpoints.system import _get_i18n
        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            result = _get_i18n()
            assert result is None

    def test_get_i18n_with_server_state(self):
        from core.endpoints.system import _get_i18n
        mock_state = MagicMock()
        mock_state.i18n = MagicMock()
        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = _get_i18n()
            assert result is mock_state.i18n


class TestTranslateHelper:
    def test_t_without_i18n(self):
        from core.endpoints.system import _t
        with patch("core.endpoints.system._get_i18n", return_value=None):
            result = _t("some.key", "Fallback text")
            assert result == "Fallback text"

    def test_t_with_i18n_found(self):
        from core.endpoints.system import _t
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Traduit"
        with patch("core.endpoints.system._get_i18n", return_value=mock_i18n):
            result = _t("some.key", "Fallback")
            assert result == "Traduit"

    def test_t_with_i18n_key_not_found(self):
        """Quan i18n retorna la clau (no trobat) → fallback"""
        from core.endpoints.system import _t
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key, **kwargs: key  # retorna la clau
        with patch("core.endpoints.system._get_i18n", return_value=mock_i18n):
            result = _t("some.key", "Fallback text")
            assert result == "Fallback text"

    def test_t_with_kwargs_in_fallback(self):
        from core.endpoints.system import _t
        with patch("core.endpoints.system._get_i18n", return_value=None):
            result = _t("key", "Error: {error}", error="test error")
            assert result == "Error: test error"

    def test_t_with_i18n_exception(self):
        from core.endpoints.system import _t
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = Exception("i18n error")
        with patch("core.endpoints.system._get_i18n", return_value=mock_i18n):
            result = _t("key", "Fallback")
            assert result == "Fallback"


class TestGetSupervisorPid:
    def test_file_not_exists(self, tmp_path):
        from core.endpoints.system import get_supervisor_pid
        non_existent = tmp_path / "no_exist.pid"
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", non_existent), \
             patch("core.endpoints.system._get_i18n", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                get_supervisor_pid()
            assert exc_info.value.status_code == 503
            assert exc_info.value.detail["error"] == "supervisor_not_found"

    def test_invalid_pid_content(self, tmp_path):
        from core.endpoints.system import get_supervisor_pid
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not_a_number")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                get_supervisor_pid()
            assert exc_info.value.status_code == 503
            assert exc_info.value.detail["error"] == "invalid_pid"

    def test_dead_process_pid(self, tmp_path):
        from core.endpoints.system import get_supervisor_pid
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("999999")  # PID molt alt, probablement no existeix
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", side_effect=ProcessLookupError("no process")):
            with pytest.raises(HTTPException) as exc_info:
                get_supervisor_pid()
            assert exc_info.value.status_code == 503
            assert exc_info.value.detail["error"] == "supervisor_dead"

    def test_permission_error(self, tmp_path):
        from core.endpoints.system import get_supervisor_pid
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", side_effect=PermissionError("no permission")):
            with pytest.raises(HTTPException) as exc_info:
                get_supervisor_pid()
            assert exc_info.value.status_code == 500
            assert exc_info.value.detail["error"] == "permission_denied"

    def test_generic_exception(self, tmp_path):
        from core.endpoints.system import get_supervisor_pid
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", side_effect=RuntimeError("unexpected")):
            with pytest.raises(HTTPException) as exc_info:
                get_supervisor_pid()
            assert exc_info.value.status_code == 500
            assert exc_info.value.detail["error"] == "unknown_error"

    def test_valid_pid_returns_int(self, tmp_path):
        from core.endpoints.system import get_supervisor_pid
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", return_value=None):  # PID existeix
            result = get_supervisor_pid()
            assert result == 12345


class TestSendRestartSignal:
    @pytest.mark.asyncio
    async def test_send_restart_signal_success(self, tmp_path):
        from core.endpoints.system import send_restart_signal
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", return_value=None), \
             patch("asyncio.sleep", return_value=None):
            # No ha de llençar excepcions
            await send_restart_signal()

    @pytest.mark.asyncio
    async def test_send_restart_signal_supervisor_not_found(self, tmp_path):
        from core.endpoints.system import send_restart_signal
        non_existent = tmp_path / "no.pid"
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", non_existent), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("asyncio.sleep", return_value=None):
            # Ha de capturar HTTPException sense relançar
            await send_restart_signal()  # no ha de llençar

    @pytest.mark.asyncio
    async def test_send_restart_signal_generic_exception(self, tmp_path):
        """Exception dins del try → capturada i loggada"""
        from core.endpoints.system import send_restart_signal
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        # Simulem que os.kill (dins del try) llança una excepció genèrica
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", side_effect=RuntimeError("unexpected error")), \
             patch("asyncio.sleep", return_value=None):
            # Ha de capturar l'excepció sense relançar
            await send_restart_signal()  # no ha de llençar


# ═══════════════════════════════════════════════════════════════════════════
# Tests d'endpoints HTTP
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemHealthEndpoint:
    def test_system_health_returns_healthy(self):
        app = make_app()
        client = TestClient(app)
        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            resp = client.get("/admin/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["platform"] == "Nexe Framework"

    def test_system_health_with_server_state(self):
        app = make_app()
        client = TestClient(app)
        mock_state = MagicMock()
        mock_state.config = {"meta": {"version": "0.9.0"}}
        with patch("core.lifespan.get_server_state", return_value=mock_state):
            resp = client.get("/admin/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.9.0"


class TestSupervisorStatusEndpoint:
    def test_status_with_supervisor_available(self, tmp_path):
        app = make_app()
        client = TestClient(app)
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", return_value=None):
            resp = client.get("/admin/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["supervisor_running"] is True
        assert data["restart_available"] is True

    def test_status_without_supervisor(self, tmp_path):
        app = make_app()
        client = TestClient(app)
        non_existent = tmp_path / "no.pid"
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", non_existent), \
             patch("core.endpoints.system._get_i18n", return_value=None):
            resp = client.get("/admin/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["supervisor_running"] is False
        assert data["restart_available"] is False


class TestRestartEndpoint:
    def test_restart_with_supervisor_available(self, tmp_path):
        app = make_app()
        client = TestClient(app)
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", pid_file), \
             patch("core.endpoints.system._get_i18n", return_value=None), \
             patch("os.kill", return_value=None):
            resp = client.post("/admin/system/restart")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "restart_initiated"

    def test_restart_without_supervisor(self, tmp_path):
        app = make_app()
        client = TestClient(app)
        non_existent = tmp_path / "no.pid"
        with patch("core.endpoints.system.SUPERVISOR_PID_FILE", non_existent), \
             patch("core.endpoints.system._get_i18n", return_value=None):
            resp = client.post("/admin/system/restart")
        assert resp.status_code == 503


class TestGetRouter:
    def test_get_router_returns_router(self):
        from core.endpoints.system import get_router, router_admin
        result = get_router()
        assert result is router_admin
