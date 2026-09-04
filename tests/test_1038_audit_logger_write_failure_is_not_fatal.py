"""
────────────────────────────────────
Server Nexe
Location: tests/test_1038_audit_logger_write_failure_is_not_fatal.py
Description: Anti-regression for #1038 — a security logger that imports fine
             and then fails to WRITE used to take a valid authentication down
             with it.

             #1005 gave the three AUTH_SUCCESS sites in
             `core/security/auth_dependencies.py` a warning each, and settled
             the contract explicitly: "a missing plugin never turns a valid key
             into a 500". But the handlers caught `ImportError`, while the
             `try` wraps the `log_event()` CALL as well as the import. A logger
             that is present and fails to write — full disk, a locked SQLite
             file, a bug of its own — raised straight through a SUCCESSFUL
             authentication. The server stopped authenticating because its
             audit log broke, which is the contract inverted.

             Not a regression introduced by #1005: the same `try` shape is
             there in af66d10e and older. It is the sibling case the finding
             did not look at — and the same night, `memory/rag/module.py`
             (#1004) wrote `except Exception` deliberately, for a failure that
             costs a COUNTER rather than an authentication.

             Each site gets the pair the #1005 tests established: the logger
             made to fail (the call must still return, and must say what went
             unrecorded) and the logger intact (silence — otherwise an
             unconditional warning would pass the first half of every test).
────────────────────────────────────
"""

from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

AUTH_LOGGER = "core.security.auth_dependencies"
SECURITY_LOGGER_MODULE = "plugins.security.security_logger"


@pytest.fixture(autouse=True)
def _forget_the_damper():
    """#1005b damps repeat warnings per site; each test here expects ITS call
    to warn, so it starts from a clean damper."""
    from core.security import auth_dependencies
    auth_dependencies._reset_audit_warn_state()
    yield
    auth_dependencies._reset_audit_warn_state()


def _request(host: str = "127.0.0.1"):
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = host
    request.url.path = "/admin/test"
    return request


def _warnings(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == AUTH_LOGGER and record.levelno == logging.WARNING
    ]


def _logger_that_fails_on_write(monkeypatch, exc: Exception) -> None:
    """A `security_logger` that IMPORTS cleanly and raises on `log_event`.

    This is the shape #1005 never exercised: `_break_import` (its helper) makes
    the import itself fail, so both halves of the try block are gone. Here the
    import succeeds and only the write fails, which is what a full disk or a
    locked database actually looks like.
    """
    module = types.ModuleType(SECURITY_LOGGER_MODULE)

    class _FailingLogger:
        def log_event(self, **kwargs):
            raise exc

    module.get_security_logger = lambda: _FailingLogger()
    module.SecurityEventType = types.SimpleNamespace(AUTH_SUCCESS="AUTH_SUCCESS")
    module.SecuritySeverity = types.SimpleNamespace(INFO="INFO", WARNING="WARNING")
    monkeypatch.setitem(sys.modules, SECURITY_LOGGER_MODULE, module)


# ─── The three sites ─────────────────────────────────────────────────────────

class TestDevModeBypass:
    async def _call(self):
        from core.security.auth_dependencies import require_api_key
        from core.security.auth_models import ApiKeyConfig

        with patch("core.security.auth_dependencies.load_api_keys",
                   return_value=ApiKeyConfig()), \
             patch("core.security.auth_dependencies.is_dev_mode", return_value=True):
            return await require_api_key(_request(), x_api_key=None)

    @pytest.mark.asyncio
    async def test_a_failing_write_does_not_take_the_bypass_down(
        self, monkeypatch, caplog,
    ):
        _logger_that_fails_on_write(monkeypatch, RuntimeError("disk full"))
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        assert await self._call() == "dev-mode-bypass", (
            "a logger that fails to WRITE must not take the bypass down either — "
            "#1005 settled that for the missing-plugin case and this is the same rule"
        )
        messages = _warnings(caplog)
        assert messages, "the bypass went unaudited in total silence"
        assert any("DEV MODE" in m and "AUTH_SUCCESS" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_working_logger_says_nothing(self, caplog):
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await self._call() == "dev-mode-bypass"
        assert _warnings(caplog) == []


class TestPrimaryKey:
    KEY = "primary-key-1038"

    async def _call(self):
        from core.security.auth_dependencies import require_api_key
        from core.security.auth_models import ApiKeyConfig, ApiKeyData

        config = ApiKeyConfig(primary=ApiKeyData(key=self.KEY))
        with patch("core.security.auth_dependencies.load_api_keys",
                   return_value=config), \
             patch("core.security.auth_dependencies.is_dev_mode", return_value=False):
            return await require_api_key(_request("127.0.0.5"), x_api_key=self.KEY)

    @pytest.mark.asyncio
    async def test_a_failing_write_does_not_reject_a_valid_key(
        self, monkeypatch, caplog,
    ):
        _logger_that_fails_on_write(monkeypatch, OSError("[Errno 28] No space left on device"))
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        assert await self._call() == self.KEY, (
            "a valid primary key must not become a 500 because the audit log broke"
        )
        messages = _warnings(caplog)
        assert any("primary" in m and "AUTH_SUCCESS" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_the_warning_names_the_failure_type(self, monkeypatch, caplog):
        """'unavailable' was accurate while only ImportError was caught. Now the
        line has to distinguish an absent logger from a broken one, or whoever
        reads the log goes looking for a missing plugin that is installed."""
        _logger_that_fails_on_write(monkeypatch, OSError("[Errno 28] No space left on device"))
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        await self._call()

        messages = _warnings(caplog)
        assert any("OSError" in m for m in messages), (
            f"the warning must name what actually failed: {messages}"
        )

    @pytest.mark.asyncio
    async def test_working_logger_says_nothing(self, caplog):
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await self._call() == self.KEY
        assert _warnings(caplog) == []


class TestSecondaryKey:
    PRIMARY = "primary-key-1038-b"
    SECONDARY = "secondary-key-1038"

    async def _call(self):
        from core.security.auth_dependencies import require_api_key
        from core.security.auth_models import ApiKeyConfig, ApiKeyData

        future = datetime.now(timezone.utc) + timedelta(days=7)
        config = ApiKeyConfig(
            primary=ApiKeyData(key=self.PRIMARY),
            secondary=ApiKeyData(key=self.SECONDARY, expires_at=future),
        )
        with patch("core.security.auth_dependencies.load_api_keys",
                   return_value=config), \
             patch("core.security.auth_dependencies.is_dev_mode", return_value=False):
            return await require_api_key(_request("127.0.0.6"), x_api_key=self.SECONDARY)

    @pytest.mark.asyncio
    async def test_a_failing_write_does_not_reject_the_rotation_key(
        self, monkeypatch, caplog,
    ):
        _logger_that_fails_on_write(monkeypatch, RuntimeError("database is locked"))
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        assert await self._call() == self.SECONDARY, (
            "losing the audit write during a key rotation must not also lock "
            "the rotation key out"
        )
        messages = _warnings(caplog)
        assert any("secondary" in m and "AUTH_SUCCESS" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_working_logger_says_nothing(self, caplog):
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await self._call() == self.SECONDARY
        assert _warnings(caplog) == []


# ─── What #1005 bought must still hold ───────────────────────────────────────

class TestTheImportCaseStillWorks:
    """Widening the handler must not lose the case it was widened from."""

    KEY = "primary-key-1038-import"

    @pytest.mark.asyncio
    async def test_a_missing_logger_still_warns_and_still_authenticates(
        self, monkeypatch, caplog,
    ):
        from core.security.auth_dependencies import require_api_key
        from core.security.auth_models import ApiKeyConfig, ApiKeyData

        # `None` in sys.modules makes any import of that name raise ImportError
        monkeypatch.setitem(sys.modules, SECURITY_LOGGER_MODULE, None)
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        config = ApiKeyConfig(primary=ApiKeyData(key=self.KEY))
        with patch("core.security.auth_dependencies.load_api_keys",
                   return_value=config), \
             patch("core.security.auth_dependencies.is_dev_mode", return_value=False):
            result = await require_api_key(_request("127.0.0.7"), x_api_key=self.KEY)

        assert result == self.KEY
        messages = _warnings(caplog)
        assert any("primary" in m and "AUTH_SUCCESS" in m for m in messages), messages
        # `ModuleNotFoundError`, not `ImportError`: a missing module raises the
        # subclass, and the line names the concrete type it caught. Asserting
        # the base name here would fail on a working fix — the same trap
        # `pytest.importorskip` sets, which only converts ModuleNotFoundError.
        assert any("ModuleNotFoundError" in m or "ImportError" in m for m in messages), (
            f"the import case must still name itself: {messages}"
        )
