"""
Bug 16 — SessionManager._sessions modificat sense lock.
Tests de race conditions amb crides concurrents.

Els metodes son sincrons pero es criden des de threadpools (FastAPI
run_in_threadpool) i tambe potencialment desde varies coroutines amb
context switches. Els protegim amb threading.RLock.
"""
import asyncio
import threading
import pytest

from plugins.web_ui_module.core.session_manager import SessionManager


@pytest.fixture
def sm(tmp_path):
    return SessionManager(storage_path=str(tmp_path))


class TestConcurrentCreateThreads:
    """N threads creant sessions amb ids diferents en paral·lel."""

    def test_create_many_sessions_threads(self, sm):
        N = 50
        ids = [f"sess-{i:03d}" for i in range(N)]

        def worker(sid):
            sm.create_session(sid)

        threads = [threading.Thread(target=worker, args=(sid,)) for sid in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Totes les sessions s'han creat
        listed = {s["id"] for s in sm.list_sessions()}
        for sid in ids:
            assert sid in listed
        assert len(listed) >= N


class TestConcurrentGetOrCreate:
    """get_or_create amb el mateix id no ha de duplicar la sessio."""

    def test_get_or_create_same_id_threads(self, sm):
        N = 30
        sid = "shared-id"
        results = []
        lock = threading.Lock()

        def worker():
            session = sm.get_or_create_session(sid)
            with lock:
                results.append(id(session))

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Una unica instancia compartida
        assert len(set(results)) == 1
        # Una unica entrada al manager
        listed = [s for s in sm.list_sessions() if s["id"] == sid]
        assert len(listed) == 1


class TestConcurrentMixedOps:
    """Crear + esborrar + carregar concurrent: estat coherent, sense exception."""

    def test_mixed_create_delete_get(self, sm):
        errors = []

        def creator(i):
            try:
                sm.create_session(f"mix-{i}")
            except Exception as e:
                errors.append(("create", i, e))

        def deleter(i):
            try:
                sm.delete_session(f"mix-{i}")
            except Exception as e:
                errors.append(("delete", i, e))

        def getter(i):
            try:
                sm.get_session(f"mix-{i}")
            except Exception as e:
                errors.append(("get", i, e))

        threads = []
        for i in range(40):
            threads.append(threading.Thread(target=creator, args=(i,)))
            threads.append(threading.Thread(target=getter, args=(i,)))
            threads.append(threading.Thread(target=deleter, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent ops: {errors}"


class TestAsyncioGather:
    """Mateix workload via asyncio.gather usant run_in_executor."""

    @pytest.mark.asyncio
    async def test_create_many_via_gather(self, sm):
        N = 30
        loop = asyncio.get_event_loop()

        async def create(i):
            return await loop.run_in_executor(None, sm.create_session, f"async-{i}")

        results = await asyncio.gather(*(create(i) for i in range(N)))
        assert len(results) == N
        listed_ids = {s["id"] for s in sm.list_sessions()}
        for i in range(N):
            assert f"async-{i}" in listed_ids
