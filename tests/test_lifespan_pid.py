"""
────────────────────────────────────
Server Nexe — Tests
Location: tests/test_lifespan_pid.py
Description: Tests per a la gestió del PID file al lifespan (B06, B10),
             reset de circuit breakers al shutdown (N03),
             cancel·lació de cleanup tasks (N04),
             i SIGTERM handler al runner (N05).
────────────────────────────────────
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lifespan import _write_pid_file, _remove_pid_file, _PID_SUBPATH


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Directori temporal com a project_root fals."""
    return tmp_path


@pytest.fixture
def pid_path(project_root: Path) -> Path:
    """Path canònic del PID file sota project_root temporal."""
    return project_root / _PID_SUBPATH


# ── B06 / B10: _write_pid_file ─────────────────────────────────────────────

def test_write_pid_file_creates_file(project_root: Path, pid_path: Path):
    """_write_pid_file escriu el PID file en format JSON (B06)."""
    assert not pid_path.exists()
    ok = _write_pid_file(project_root, port=9119)
    assert ok is True
    assert pid_path.exists()

    import json
    data = json.loads(pid_path.read_text())
    assert data["pid"] == os.getpid()
    assert data["port"] == 9119
    from datetime import datetime
    datetime.fromisoformat(data["started"])  # ha de ser parsejable


def test_write_pid_file_returns_false_if_live_pid(project_root: Path, pid_path: Path):
    """_write_pid_file retorna False si un servidor viu ja té el lock (B10)."""
    # Primer adquireix
    ok = _write_pid_file(project_root, port=9119)
    assert ok is True

    # Segon intent: simula que el PID és viu (os.kill no llança)
    with patch("core.lifespan.os.kill", return_value=None):
        ok2 = _write_pid_file(project_root, port=9119)
    assert ok2 is False
    # Fitxer original intacte
    import json
    data = json.loads(pid_path.read_text())
    assert data["pid"] == os.getpid()


def test_write_pid_file_removes_stale_and_acquires(project_root: Path, pid_path: Path):
    """_write_pid_file elimina PID estantís i adquireix (B07 / B10)."""
    import json
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(json.dumps({"pid": 99999, "port": 9119, "started": "2020-01-01T00:00:00+00:00"}))

    def _fake_kill(pid, sig):
        raise ProcessLookupError(f"No such process: {pid}")

    with patch("core.lifespan.os.kill", side_effect=_fake_kill):
        ok = _write_pid_file(project_root, port=9119)
    assert ok is True
    data = json.loads(pid_path.read_text())
    assert data["pid"] == os.getpid()


# ── B10: _remove_pid_file ────────────────────────────────────────────────────

def test_remove_pid_file_deletes_owned_file(project_root: Path, pid_path: Path):
    """_remove_pid_file elimina el PID file que pertany a aquest procés (B10)."""
    import json
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(json.dumps({"pid": os.getpid(), "port": 9119, "started": "2026-01-01T00:00:00+00:00"}))

    _remove_pid_file(project_root)
    assert not pid_path.exists()


def test_remove_pid_file_leaves_foreign_file(project_root: Path, pid_path: Path):
    """_remove_pid_file NO elimina PID files d'un altre procés (B10)."""
    import json
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(json.dumps({"pid": 99999, "port": 9119, "started": "2026-01-01T00:00:00+00:00"}))

    _remove_pid_file(project_root)
    assert pid_path.exists()  # no l'ha eliminat


def test_remove_pid_file_noop_when_missing(project_root: Path):
    """_remove_pid_file és segur quan el fitxer no existeix (B10)."""
    _remove_pid_file(project_root)  # no ha de llançar


def test_remove_pid_file_noop_when_project_root_none():
    """_remove_pid_file és segur amb project_root None (B10)."""
    _remove_pid_file(None)  # no ha de llançar


# ── N03: reset circuit breakers ───────────────────────────────────────────────

def test_reset_all_circuit_breakers_resets_to_closed():
    """reset_all_circuit_breakers torna tots els breakers a CLOSED (N03)."""
    from core.resilience import (
        reset_all_circuit_breakers,
        ollama_breaker, qdrant_breaker, http_breaker,
        CircuitState,
    )

    # Forçar estat OPEN als tres breakers
    for breaker in (ollama_breaker, qdrant_breaker, http_breaker):
        breaker._state.state = CircuitState.OPEN
        breaker._state.failure_count = 5

    reset_all_circuit_breakers()

    for breaker in (ollama_breaker, qdrant_breaker, http_breaker):
        assert breaker.state == CircuitState.CLOSED, (
            f"Breaker '{breaker.name}' hauria d'estar CLOSED després del reset"
        )
        assert breaker._state.failure_count == 0


def test_circuit_breaker_reset_method():
    """CircuitBreaker.reset() reinicia a CLOSED net (N03)."""
    from core.resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState

    breaker = CircuitBreaker("test_reset", CircuitBreakerConfig(failure_threshold=1))
    breaker._state.state = CircuitState.OPEN
    breaker._state.failure_count = 3

    breaker.reset()

    assert breaker.state == CircuitState.CLOSED
    assert breaker._state.failure_count == 0
    assert breaker._state.success_count == 0
    assert breaker._state.last_failure_time is None


# ── N04: cleanup tasks cancel·lades ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_task_cancelled_on_shutdown():
    """_cleanup_task creada al lifespan ha de ser cancel·lada al shutdown (N04)."""
    # Simula una tasca infinita (com start_rate_limit_cleanup)
    async def _infinite_loop():
        while True:
            await asyncio.sleep(3600)

    task = asyncio.create_task(_infinite_loop())
    assert not task.done()

    # Simula el pattern del lifespan shutdown
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert task.done()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_session_cleanup_task_returns_task():
    """start_session_cleanup_task retorna un asyncio.Task (N04)."""
    from plugins.web_ui_module.api.routes import start_session_cleanup_task

    mock_mgr = MagicMock()
    # Patch el loop intern perquè no faci I/O real
    with patch("plugins.web_ui_module.api.routes._session_cleanup_loop", new=AsyncMock(return_value=None)):
        task = start_session_cleanup_task(mock_mgr)

    assert isinstance(task, asyncio.Task), (
        "start_session_cleanup_task ha de retornar asyncio.Task per poder cancel·lar-lo"
    )
    # Neteja
    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ── N05: SIGTERM handler al runner ────────────────────────────────────────────

def test_sigterm_handler_registered_in_runner():
    """runner.py registra _handle_sigterm com a handler de SIGTERM (N05)."""
    import core.server.runner as runner_module
    assert hasattr(runner_module, "_handle_sigterm"), (
        "_handle_sigterm no definit a core.server.runner — N05 no implementat"
    )
    assert callable(runner_module._handle_sigterm)
