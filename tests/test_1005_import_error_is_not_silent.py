"""
────────────────────────────────────
Server Nexe
Location: tests/test_1005_import_error_is_not_silent.py
Description: Anti-regression for #1005 — four `except ImportError` that did
             nothing at all.

             Three of them are in `core/security/auth_dependencies.py`, around
             the import of the IRONCLAD security logger: the DEV MODE bypass,
             the primary key and the secondary key each log an AUTH_SUCCESS
             event, and each swallowed the failed import with `pass`. SECURITY.md
             states those authentications are recorded, so a broken or missing
             `plugins.security.security_logger` produced an audit trail with
             holes in it and not one line saying why. The request still
             succeeds — that part is deliberate, a missing plugin must not turn
             a valid key into a 500 — but it now says out loud what stopped
             being written.

             The fourth is in `memory/memory/api/documents.py`: a one-shot lazy
             import of the Prometheus registry. Losing it is not a security
             matter, it silently flatlines the memory counters for the whole
             process.

             Each site gets a pair: the import forced to fail (the warning must
             appear, and the call must still return what it returned before)
             and the import intact (no warning — otherwise a `logger.warning`
             left unconditionally outside the handler would pass the first half
             of every test here).
────────────────────────────────────
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

AUTH_LOGGER = "core.security.auth_dependencies"
DOCS_LOGGER = "memory.memory.api.documents"

SECURITY_LOGGER_MODULE = "plugins.security.security_logger"
METRICS_MODULE = "core.metrics.registry"


@pytest.fixture(autouse=True)
def _forget_the_damper():
    """#1005b added a per-site damper to those three warnings: the first one
    through is emitted, the rest are counted and folded into the next.

    These tests each expect THEIR call to warn, so they start from a clean
    damper instead of inheriting whatever ran before them in the process. The
    eight assertions themselves are unchanged — the first failure at a site
    still warns, which is the contract #1005 bought.
    """
    from core.security import auth_dependencies
    auth_dependencies._reset_audit_warn_state()
    yield
    auth_dependencies._reset_audit_warn_state()


def _request(host: str = "127.0.0.1"):
    """A request shaped like the one FastAPI hands the dependency."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = host
    request.url.path = "/admin/test"
    return request


def _break_import(monkeypatch, dotted: str) -> None:
    """``None`` in sys.modules makes any `import` of that name raise ImportError.

    Global by design: every importer of the module sees the same failure, so no
    path can quietly keep working on a probe the mock let through.
    """
    monkeypatch.setitem(sys.modules, dotted, None)


def _warnings(caplog, logger_name: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger_name and record.levelno == logging.WARNING
    ]


# ─── The three security-logger sites ─────────────────────────────────────────

class TestDevModeBypass:
    """`_check_dev_mode`, reached through the real `require_api_key`."""

    async def _call(self):
        from core.security.auth_dependencies import require_api_key
        from core.security.auth_models import ApiKeyConfig

        with patch("core.security.auth_dependencies.load_api_keys",
                   return_value=ApiKeyConfig()), \
             patch("core.security.auth_dependencies.is_dev_mode", return_value=True):
            return await require_api_key(_request(), x_api_key=None)

    @pytest.mark.asyncio
    async def test_broken_logger_warns_that_the_bypass_went_unaudited(
        self, monkeypatch, caplog,
    ):
        _break_import(monkeypatch, SECURITY_LOGGER_MODULE)
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        assert await self._call() == "dev-mode-bypass", (
            "a missing audit logger must not take the bypass down with it"
        )

        messages = _warnings(caplog, AUTH_LOGGER)
        assert messages, "the DEV MODE bypass went unaudited in total silence"
        assert any("DEV MODE" in m and "AUTH_SUCCESS" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_working_logger_says_nothing(self, caplog):
        """Control: the warning belongs to the handler, not to the happy path."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await self._call() == "dev-mode-bypass"
        assert _warnings(caplog, AUTH_LOGGER) == []


class TestPrimaryKey:
    """`_authenticate_primary`, through `require_api_key`."""

    KEY = "primary-key-1005"

    async def _call(self):
        from core.security.auth_dependencies import require_api_key
        from core.security.auth_models import ApiKeyConfig, ApiKeyData

        config = ApiKeyConfig(primary=ApiKeyData(key=self.KEY))
        with patch("core.security.auth_dependencies.load_api_keys",
                   return_value=config), \
             patch("core.security.auth_dependencies.is_dev_mode", return_value=False):
            return await require_api_key(_request("127.0.0.5"), x_api_key=self.KEY)

    @pytest.mark.asyncio
    async def test_broken_logger_warns_that_the_success_went_unaudited(
        self, monkeypatch, caplog,
    ):
        _break_import(monkeypatch, SECURITY_LOGGER_MODULE)
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        assert await self._call() == self.KEY

        messages = _warnings(caplog, AUTH_LOGGER)
        assert messages, "a primary-key AUTH_SUCCESS was lost without a word"
        assert any("primary" in m and "AUTH_SUCCESS" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_working_logger_says_nothing(self, caplog):
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await self._call() == self.KEY
        assert _warnings(caplog, AUTH_LOGGER) == []


class TestSecondaryKey:
    """`_authenticate_secondary` — the rotation key, through `require_api_key`."""

    PRIMARY = "primary-key-1005-b"
    SECONDARY = "secondary-key-1005"

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
    async def test_broken_logger_warns_that_the_success_went_unaudited(
        self, monkeypatch, caplog,
    ):
        _break_import(monkeypatch, SECURITY_LOGGER_MODULE)
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)

        assert await self._call() == self.SECONDARY

        messages = _warnings(caplog, AUTH_LOGGER)
        assert messages, "a secondary-key AUTH_SUCCESS was lost without a word"
        assert any("secondary" in m and "AUTH_SUCCESS" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_working_logger_says_nothing(self, caplog):
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await self._call() == self.SECONDARY
        assert _warnings(caplog, AUTH_LOGGER) == []


# ─── The memory metrics site ─────────────────────────────────────────────────

class TestMemoryMetrics:
    """`_get_metrics`, reached through `store_document` — the real caller."""

    async def _store(self, monkeypatch):
        from memory.memory.api import documents

        # One-shot lazy import: without resetting the flag the module keeps
        # whatever the rest of the suite already resolved and the handler is
        # never reached.
        monkeypatch.setattr(documents, "_metrics_imported", False)
        monkeypatch.setattr(documents, "_MEMORY_OPERATIONS", None)
        monkeypatch.setattr(documents, "_MEMORY_STORE_SIZE", None)

        qdrant = MagicMock()
        qdrant.upsert = MagicMock()

        async def _embedding(text: str):
            return [0.1] * 768

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            return await documents.store_document(
                qdrant, executor, _embedding, "text de prova", "col-1005",
            )
        finally:
            executor.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_broken_registry_warns_that_the_counters_go_flat(
        self, monkeypatch, caplog,
    ):
        _break_import(monkeypatch, METRICS_MODULE)
        caplog.set_level(logging.WARNING, logger=DOCS_LOGGER)

        assert await self._store(monkeypatch), "the store must survive it"

        messages = _warnings(caplog, DOCS_LOGGER)
        assert messages, "the memory counters flatlined in silence"
        assert any("metrics" in m.lower() for m in messages), messages

    @pytest.mark.asyncio
    async def test_working_registry_says_nothing(self, monkeypatch, caplog):
        caplog.set_level(logging.WARNING, logger=DOCS_LOGGER)
        assert await self._store(monkeypatch)
        assert _warnings(caplog, DOCS_LOGGER) == []
