"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live_runs_on_isolated_storage.py
Description: The live suite never writes into the real DEV storage unless
             asked. Seen 25/09: the DEV personal memory held test facts ("em
             dic Aran", "visc a Girona", "User: AAAA…") — the live tests store
             facts and clean none up, and they reused a running server on the
             real storage, or spawned one whose relative NEXE_QDRANT_PATH still
             pointed there (#1053).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path

import tests.test_live.conftest as live


def test_a_running_server_is_not_reused_unless_asked(monkeypatch):
    monkeypatch.delenv("NEXE_TEST_URL", raising=False)
    monkeypatch.delenv("NEXE_TEST_ALLOW_REAL_STORAGE", raising=False)
    assert live._may_reuse_running_server() is False
    monkeypatch.setenv("NEXE_TEST_URL", "http://sidecar:9119")
    assert live._may_reuse_running_server() is True
    monkeypatch.delenv("NEXE_TEST_URL")
    monkeypatch.setenv("NEXE_TEST_ALLOW_REAL_STORAGE", "1")
    assert live._may_reuse_running_server() is True


def test_the_spawned_server_keeps_its_vectors_under_the_test_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXE_TEST_ALLOW_REAL_STORAGE", raising=False)
    monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXE_QDRANT_PATH", "storage/vectors")  # what .env says
    env = live._build_env()
    qdrant = Path(env["NEXE_QDRANT_PATH"])
    assert qdrant.is_absolute() and tmp_path.resolve() in qdrant.parents
