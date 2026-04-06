"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_dreaming_cycle_sql.py
Description: Tests per Bug 9 — `MIN(10, evidence_count + 1)` era una extensio
             SQLite (multi-arg function) no portable. Ara calculem el cap de
             10 en Python i passem el valor com a parametre vinculat.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from memory.memory.workers.dreaming_cycle import DreamingCycle


class _FakeCursor:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Conn que retorna evidence_count programable per al SELECT del refresh."""

    def __init__(self, current_evidence):
        self._current = current_evidence
        self.executed = []  # llista (sql, params)
        self.closed = False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT evidence_count FROM episodic"):
            return _FakeCursor(one=(self._current,))
        if "FROM staging" in sql and "ORDER BY" in sql:
            # _process_staging select — no entrar pel batch loop
            return _FakeCursor(rows=[])
        if sql_norm.startswith("SELECT") and "FROM staging" in sql_norm:
            return _FakeCursor(rows=[])
        return _FakeCursor()

    def commit(self):
        pass

    def close(self):
        self.closed = True


class _FakeStore:
    def __init__(self, conn):
        self._conn = conn

    def _connect(self):
        return self._conn

    def is_tombstoned(self, *_, **__):
        return False

    def insert_episodic(self, *_, **__):
        return 1


def _make_cycle(store, vector, embedder):
    cycle = DreamingCycle.__new__(DreamingCycle)
    cycle._store = store
    cycle._vector = vector
    cycle._embedder = embedder
    cycle._is_running = False
    cycle._should_stop = False
    cycle._consecutive_skips = 0
    cycle._force_threshold = 50
    cycle._interval = 900
    cycle._task = None
    cycle._config = MagicMock()
    cycle._config.dedup_refresh_threshold = 0.92
    return cycle


def _build_entry():
    return {
        "id": 42,
        "user_id": "u1",
        "validator_decision": "promote_episodic",
        "target_store": "episodic",
        "extractor_output_json": json.dumps({"importance": 0.5, "type": "fact"}),
        "raw_text": "the cat sat on the mat",
        "source": "test",
        "trust_level": "untrusted",
        "namespace": "default",
    }


def _make_vector_with_dup():
    vector = MagicMock()
    vector.available = True
    vector.search.return_value = [{"id": 999, "score": 0.99}]
    return vector


def _make_embedder():
    embedder = MagicMock()
    embedder.encode.return_value = [0.0, 0.1, 0.2]
    return embedder


def _find_update_evidence(executed):
    """Retorna (sql, params) de l'UPDATE episodic SET ... evidence_count = ?"""
    for sql, params in executed:
        if "UPDATE episodic" in sql and "evidence_count" in sql:
            return sql, params
    return None, None


@pytest.mark.parametrize("current,expected", [
    (5, 6),
    (15, 10),
    (10, 10),
    (0, 1),
    (9, 10),
])
def test_evidence_count_capped_in_python(current, expected):
    """Bug 9: el valor s'ha de calcular en Python i passar com a parametre."""
    conn = _FakeConn(current_evidence=current)
    store = _FakeStore(conn)
    vector = _make_vector_with_dup()
    embedder = _make_embedder()
    cycle = _make_cycle(store, vector, embedder)

    asyncio.run(cycle._process_one(_build_entry()))

    sql, params = _find_update_evidence(conn.executed)
    assert sql is not None, (
        "No s'ha trobat cap UPDATE episodic SET evidence_count. "
        f"Executed: {conn.executed}"
    )
    # SQL ha d'usar parametre vinculat, NO la funcio multi-arg MIN()
    assert "MIN(10," not in sql.replace(" ", ""), (
        f"SQL encara conte MIN(10, ...): {sql}"
    )
    assert "?" in sql
    # El primer parametre vinculat ha de ser el nou evidence_count
    assert params[0] == expected, (
        f"Esperat evidence_count={expected} per current={current}, "
        f"rebut params={params}"
    )
