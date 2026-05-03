"""R6-11 v1.0.4: rotate rag.log daily, keep 14 days.

The previous handler was a plain ``logging.FileHandler``: each chat exchange
appended several DEBUG lines and the file grew without bound. A long-running
local install could fill the disk in weeks. R6-11 swaps it for a
``TimedRotatingFileHandler(when='midnight', interval=1, backupCount=14)`` so
old snapshots age out automatically and operators have a 14-day post-incident
debug window.

Tests:
  1. Static guard: source imports TimedRotatingFileHandler and configures
     when='midnight' + backupCount=14 + encoding='utf-8'. Survives someone
     swapping the handler back to FileHandler in a future PR.
  2. Functional: the handler attached to ``logging.getLogger('nexe.rag')``
     is exactly a TimedRotatingFileHandler with the expected attributes.
  3. Adversarial: the first log line after construction lands on disk in the
     primary file, not on a (non-existent) rotated suffix — verifies that
     rollover does not happen on first write.
"""

import inspect
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from unittest.mock import patch


# ─── Static guards ──────────────────────────────────────────────────────────


def test_rag_logger_imports_timed_rotating_handler():
    """The source must import TimedRotatingFileHandler — defends against a
    silent revert to plain FileHandler."""
    import memory.memory.rag_logger as rag_logger
    src = inspect.getsource(rag_logger)
    assert "from logging.handlers import TimedRotatingFileHandler" in src, (
        "memory/memory/rag_logger.py must import TimedRotatingFileHandler. "
        "R6-11 requires daily rotation; FileHandler grows unbounded."
    )


def test_rag_logger_configures_midnight_rotation_with_14_day_retention():
    """The source must configure when='midnight' + backupCount=14 — the
    rotation policy. Encoding utf-8 is also required because the log carries
    emoji prefixes (RAGEmojis)."""
    import memory.memory.rag_logger as rag_logger
    src = inspect.getsource(rag_logger)
    # Order-tolerant: arguments may be reformatted across lines.
    assert 'when="midnight"' in src or "when='midnight'" in src, (
        "TimedRotatingFileHandler must rotate at midnight (R6-11)."
    )
    assert "backupCount=14" in src, (
        "Backup count must be 14 days — older snapshots are removed (R6-11)."
    )
    assert 'encoding="utf-8"' in src or "encoding='utf-8'" in src, (
        "encoding='utf-8' is mandatory because the log carries emoji glyphs "
        "(RAGEmojis); without it Python defaults to the locale, which on "
        "minimal containers can be ASCII and break log writes."
    )


# ─── Functional contract ────────────────────────────────────────────────────


def _fresh_rag_logger(tmp_path: Path):
    """Build a RAGLogger that writes into ``tmp_path``, evicting any
    pre-existing handler on the shared ``nexe.rag`` logger so the new
    instance attaches its own."""
    rag_log_logger = logging.getLogger("nexe.rag")
    # Detach any handler from a previous test/instance — RAGLogger guards
    # against duplicate handlers via ``if not self.logger.handlers``.
    for h in list(rag_log_logger.handlers):
        rag_log_logger.removeHandler(h)
        h.close()

    from memory.memory.rag_logger import RAGLogger
    with patch.dict(os.environ, {"NEXE_LOGS_DIR": str(tmp_path)}):
        instance = RAGLogger(enabled=True)
    return instance, rag_log_logger


def test_handler_is_timed_rotating(tmp_path: Path):
    """The attached handler is a TimedRotatingFileHandler, not FileHandler."""
    _instance, rag_log_logger = _fresh_rag_logger(tmp_path)
    handlers = [h for h in rag_log_logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(handlers) == 1, (
        f"Expected exactly one FileHandler-derived handler; got {handlers}."
    )
    fh = handlers[0]
    assert isinstance(fh, TimedRotatingFileHandler), (
        f"Handler must be TimedRotatingFileHandler, got {type(fh).__name__}. "
        "R6-11 contract violated."
    )


def test_handler_rotation_policy(tmp_path: Path):
    """Concrete rotation parameters: midnight + 14-day retention + utf-8."""
    _instance, rag_log_logger = _fresh_rag_logger(tmp_path)
    fh = next(
        h for h in rag_log_logger.handlers
        if isinstance(h, TimedRotatingFileHandler)
    )
    # TimedRotatingFileHandler stores when in upper case (e.g. 'MIDNIGHT').
    assert fh.when.upper() == "MIDNIGHT", (
        f"Rotation trigger must be midnight, got {fh.when!r}."
    )
    assert fh.backupCount == 14, (
        f"Retention must be 14 days, got {fh.backupCount}."
    )
    assert fh.encoding == "utf-8", (
        f"Encoding must be utf-8 to support emoji glyphs, got {fh.encoding!r}."
    )
    assert fh.interval == 86400, (
        # 1 day in seconds — interval=1 with when='midnight' is normalised
        # by TimedRotatingFileHandler to 86400 internally.
        f"Interval must be 1 day (86400 s), got {fh.interval}."
    )


def test_log_path_preserved(tmp_path: Path):
    """The path resolution (NEXE_LOGS_DIR > storage/logs > /tmp) must be
    untouched — operators may have shipped scripts that tail the resolved path."""
    instance, _ = _fresh_rag_logger(tmp_path)
    assert instance.log_path == tmp_path / "rag.log", (
        f"Log path moved unexpectedly: {instance.log_path}. "
        "Operators tailing the original path would lose visibility."
    )


def test_first_line_lands_in_primary_file(tmp_path: Path):
    """Adversarial: the first line written after construction must end up in
    the primary file (rag.log), not on a hypothetical rotated suffix.
    TimedRotatingFileHandler computes the next rollover time at construction
    based on file mtime; a brand-new file should not trigger rollover on
    first write."""
    instance, _ = _fresh_rag_logger(tmp_path)
    instance._write("first-line-after-rotation-init")
    # Flush the handler so the line is on disk for the assertion.
    for h in instance.logger.handlers:
        h.flush()

    primary = tmp_path / "rag.log"
    assert primary.exists(), "Primary rag.log was not created on first write."
    contents = primary.read_text(encoding="utf-8")
    assert "first-line-after-rotation-init" in contents, (
        f"First log line missing from primary file. Contents: {contents!r}"
    )
    # No backup files should exist yet (we haven't crossed midnight).
    backups = list(tmp_path.glob("rag.log.*"))
    assert backups == [], (
        f"Unexpected rotated backup on first write: {backups}. "
        "TimedRotatingFileHandler should rotate on rollover only."
    )
