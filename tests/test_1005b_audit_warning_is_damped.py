"""
────────────────────────────────────
Server Nexe
Location: tests/test_1005b_audit_warning_is_damped.py
Description: #1005b — the volume of the three AUTH_SUCCESS warnings #1005
             added.

             #1005 made a broken IRONCLAD logger say so instead of passing.
             Shipped as written it warned on EVERY authentication, and the
             measurement that settles the volume is this: the web UI polls
             `/status` WITH authentication every 10 seconds
             (`plugins/web_ui_module/ui/app.js` — `setInterval(checkStatus,
             10000)` over `fetchWithCsrf`). An open tab and nothing else is
             8 640 authenticated requests a day, about 26 000 identical lines
             across the three sites, on a single-user local server. A flooded
             log hides things exactly as well as a silent one.

             Warning once per process is not the fix either: that line rotates
             away and the log then reads healthy while the audit trail keeps
             losing one event per authentication.

             So the contract these tests pin: the first one through is warned,
             the rest are counted, and no warning is ever emitted without
             saying how many it stands for — since the previous warning and
             over the life of the process. A damper that dropped the count
             would be #1005 again under another name.

             `memory/memory/api/documents.py` stays one-shot and is asserted
             here to stay that way: what it loses is a counter (uniform loss,
             one line describes it), not one event per request.
────────────────────────────────────
"""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.security import auth_dependencies

AUTH_LOGGER = "core.security.auth_dependencies"
DOCS_LOGGER = "memory.memory.api.documents"
SECURITY_LOGGER_MODULE = "plugins.security.security_logger"

PRIMARY = "primary-key-1005b"


@pytest.fixture(autouse=True)
def _clean_damper():
    auth_dependencies._reset_audit_warn_state()
    yield
    auth_dependencies._reset_audit_warn_state()


@pytest.fixture
def broken_logger(monkeypatch):
    """Global, not per-argument: every importer of the module fails alike."""
    monkeypatch.setitem(sys.modules, SECURITY_LOGGER_MODULE, None)


class _Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(auth_dependencies, "time", SimpleNamespace(monotonic=fake.monotonic))
    return fake


def _request(host: str = "127.0.0.9"):
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = host
    request.url.path = "/admin/test"
    return request


async def _authenticate_with_primary() -> str:
    """The real dependency, primary key accepted."""
    from core.security.auth_dependencies import require_api_key
    from core.security.auth_models import ApiKeyConfig, ApiKeyData

    config = ApiKeyConfig(primary=ApiKeyData(key=PRIMARY))
    with patch("core.security.auth_dependencies.load_api_keys", return_value=config), \
         patch("core.security.auth_dependencies.is_dev_mode", return_value=False):
        return await require_api_key(_request(), x_api_key=PRIMARY)


async def _dev_mode_bypass() -> str:
    from core.security.auth_dependencies import require_api_key
    from core.security.auth_models import ApiKeyConfig

    with patch("core.security.auth_dependencies.load_api_keys", return_value=ApiKeyConfig()), \
         patch("core.security.auth_dependencies.is_dev_mode", return_value=True):
        return await require_api_key(_request("127.0.0.1"), x_api_key=None)


def _warnings(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.name == AUTH_LOGGER and r.levelno == logging.WARNING
    ]


@pytest.mark.asyncio
class TestTheFloodIsGone:

    async def test_the_first_failure_still_warns(self, broken_logger, caplog, clock):
        """#1005's contract survives the damper: the hole is announced."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        assert await _authenticate_with_primary() == PRIMARY
        messages = _warnings(caplog)
        assert len(messages) == 1, messages
        assert "AUTH_SUCCESS" in messages[0]

    async def test_a_burst_inside_the_window_produces_one_line(
        self, broken_logger, caplog, clock,
    ):
        """The /status poll shape: many authentications, no time passing."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        for _ in range(50):
            clock.advance(10)  # the real poll interval
            assert await _authenticate_with_primary() == PRIMARY

        messages = _warnings(caplog)
        assert len(messages) == 2, (
            "50 polls over 500 s must cross the 300 s window exactly once after "
            f"the first line: {messages}"
        )

    async def test_the_warning_that_gets_through_says_how_many_it_stands_for(
        self, broken_logger, caplog, clock,
    ):
        """Without the count, damping is #1005 with better manners."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        await _authenticate_with_primary()          # warns, count 1
        for _ in range(9):
            await _authenticate_with_primary()      # suppressed
        clock.advance(301)
        await _authenticate_with_primary()          # warns again

        messages = _warnings(caplog)
        assert len(messages) == 2, messages
        assert "9 more went unrecorded since the last warning" in messages[1], messages[1]
        assert "11 in this process so far" in messages[1], (
            "the running total is what says how big the hole is: " + messages[1]
        )

    async def test_a_long_enough_burst_breaks_through_before_the_window(
        self, broken_logger, caplog, clock,
    ):
        """Whichever comes first. Under a hammering client the clock alone
        would let 500 s of authentications pass on one line."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        for _ in range(auth_dependencies._AUDIT_WARN_EVERY_EVENTS + 1):
            await _authenticate_with_primary()

        messages = _warnings(caplog)
        assert len(messages) == 2, f"no time passed, so only the event budget can fire: {messages}"
        assert "499 more went unrecorded" in messages[1], messages[1]

    async def test_the_damper_is_per_site(self, broken_logger, caplog, clock):
        """Three different things stop being recorded; one going quiet must not
        gag the others."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        await _authenticate_with_primary()
        await _authenticate_with_primary()          # suppressed
        await _dev_mode_bypass()                    # different site: must warn

        messages = _warnings(caplog)
        assert len(messages) == 2, messages
        assert "primary API key" in messages[0]
        assert "DEV MODE" in messages[1]

    async def test_a_damped_warning_never_changes_the_answer(
        self, broken_logger, caplog, clock,
    ):
        """The rule #1005 set and #1005b must not break: a broken logger never
        turns a valid key into a failure, warned or suppressed."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        for _ in range(20):
            assert await _authenticate_with_primary() == PRIMARY
        assert len(_warnings(caplog)) == 1, "and the log stayed quiet after the first"

    async def test_a_working_logger_says_nothing_at_any_volume(self, caplog, clock):
        """Control: the whole mechanism lives inside the handler."""
        caplog.set_level(logging.WARNING, logger=AUTH_LOGGER)
        for _ in range(10):
            clock.advance(600)
            assert await _authenticate_with_primary() == PRIMARY
        assert _warnings(caplog) == []


class TestMemoryMetricsStayOneShot:
    """The asymmetry is deliberate, not an inconsistency to iron out."""

    async def _store(self, monkeypatch):
        from memory.memory.api import documents
        from concurrent.futures import ThreadPoolExecutor

        async def _embedding(text: str):
            return [0.1] * 768

        qdrant = MagicMock()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            return await documents.store_document(
                qdrant, executor, _embedding, "text", "col-1005b",
            )
        finally:
            executor.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_the_metrics_warning_is_emitted_once_per_process(
        self, monkeypatch, caplog,
    ):
        """What is lost there is a counter — a uniform loss one line describes
        in full — not one audit event per request."""
        from memory.memory.api import documents

        monkeypatch.setattr(documents, "_metrics_imported", False)
        monkeypatch.setattr(documents, "_MEMORY_OPERATIONS", None)
        monkeypatch.setattr(documents, "_MEMORY_STORE_SIZE", None)
        monkeypatch.setitem(sys.modules, "core.metrics.registry", None)
        caplog.set_level(logging.WARNING, logger=DOCS_LOGGER)

        await self._store(monkeypatch)
        await self._store(monkeypatch)
        await self._store(monkeypatch)

        warnings = [
            r.getMessage() for r in caplog.records
            if r.name == DOCS_LOGGER and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1, f"one lazy import, one warning: {warnings}"
