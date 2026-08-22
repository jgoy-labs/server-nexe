"""
Tests for core/state_watcher.py — D-Q, the periodic eye.

The hysteresis tests are the ones that matter: a warning that blinks is a
warning nobody reads. Mutation guard: set confirmations to 1 (or make observe()
believe the first reading) and every "does not move on one reading" test below
must turn red.
"""

import asyncio

import pytest

from core.operational_state import (
    ModuleSignal,
    OperationalState,
    clear_refusals,
)
from core.state_watcher import (
    StateWatcher,
    clear_sensors,
    collect,
    register_sensor,
    sensor_names,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_sensors()
    clear_refusals()
    yield
    clear_sensors()
    clear_refusals()


class TestSensors:
    @pytest.mark.asyncio
    async def test_no_sensors_sees_nothing(self):
        assert await collect() == []

    @pytest.mark.asyncio
    async def test_a_sync_sensor_is_read(self):
        register_sensor("s", lambda: [ModuleSignal("rag", "missing")])
        assert [s.name for s in await collect()] == ["rag"]

    @pytest.mark.asyncio
    async def test_an_async_sensor_is_read(self):
        async def eye():
            return [ModuleSignal("qdrant", "missing")]

        register_sensor("s", eye)
        assert [s.name for s in await collect()] == ["qdrant"]

    @pytest.mark.asyncio
    async def test_a_blind_sensor_does_not_blind_the_rest(self):
        """One eye that raises must not cost the round."""

        def broken():
            raise RuntimeError("this sensor is on fire")

        register_sensor("broken", broken)
        register_sensor("good", lambda: [ModuleSignal("rag", "missing")])
        assert [s.name for s in await collect()] == ["rag"]

    def test_registering_the_same_name_replaces_it(self):
        register_sensor("s", lambda: [])
        register_sensor("s", lambda: [])
        assert sensor_names() == ("s",)


class TestHysteresis:
    def test_a_new_state_does_not_land_on_one_reading(self):
        w = StateWatcher(interval=0, confirmations=2)
        assert w.observe(OperationalState.LIMITED) is OperationalState.NORMAL
        assert w.state is OperationalState.NORMAL

    def test_a_repeated_reading_is_believed(self):
        w = StateWatcher(interval=0, confirmations=2)
        w.observe(OperationalState.LIMITED)
        assert w.observe(OperationalState.LIMITED) is OperationalState.LIMITED

    def test_a_flapping_module_never_moves_the_state(self):
        """The whole point: a backend answering slowly every other round must
        not walk the banner in and out."""
        w = StateWatcher(interval=0, confirmations=2)
        for _ in range(10):
            w.observe(OperationalState.LIMITED)
            w.observe(OperationalState.NORMAL)
        assert w.state is OperationalState.NORMAL

    def test_recovery_also_has_to_hold(self):
        w = StateWatcher(interval=0, confirmations=2)
        w.observe(OperationalState.LIMITED)
        w.observe(OperationalState.LIMITED)
        assert w.state is OperationalState.LIMITED
        assert w.observe(OperationalState.NORMAL) is OperationalState.LIMITED
        assert w.observe(OperationalState.NORMAL) is OperationalState.NORMAL

    def test_confirmations_of_one_believes_immediately(self):
        w = StateWatcher(interval=0, confirmations=1)
        assert w.observe(OperationalState.LIMITED) is OperationalState.LIMITED

    def test_confirmations_never_drops_below_one(self):
        """A zero would mean "believe nothing ever"."""
        assert StateWatcher(interval=0, confirmations=0).confirmations == 1


class TestPolling:
    @pytest.mark.asyncio
    async def test_a_round_reads_the_sensors_and_decides(self):
        register_sensor("s", lambda: [ModuleSignal("rag", "missing")])
        w = StateWatcher(interval=0, confirmations=1)
        assert await w.poll_once() is OperationalState.LIMITED

    @pytest.mark.asyncio
    async def test_a_critical_module_missing_reads_as_refused(self):
        register_sensor("s", lambda: [ModuleSignal("security", "missing")])
        w = StateWatcher(interval=0, confirmations=1)
        assert await w.poll_once() is OperationalState.REFUSED

    @pytest.mark.asyncio
    async def test_an_interval_of_zero_does_not_start_the_loop(self):
        w = StateWatcher(interval=0)
        assert w.start() is None

    @pytest.mark.asyncio
    async def test_start_then_stop_leaves_no_task_behind(self):
        w = StateWatcher(interval=0.01, confirmations=1)
        task = w.start()
        assert task is not None
        await asyncio.sleep(0.05)
        await w.stop()
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_the_loop_survives_a_sensor_that_raises(self):
        def broken():
            raise RuntimeError("still on fire")

        register_sensor("broken", broken)
        w = StateWatcher(interval=0.01, confirmations=1)
        task = w.start()
        await asyncio.sleep(0.05)
        assert not task.done(), "the watcher died on a failing sensor"
        await w.stop()


class TestPrime:
    """The first round is believed on the spot — and nothing guarded that.

    Mutation check (22/08 review): routing prime() through observe() left the
    whole suite green at 8000 passed. A user whose RAG failed to load would sit
    two rounds (a minute, at the default interval) being told everything is
    fine, which is the same silence #889 was about. These tests are the ones
    that go red for it.
    """

    @pytest.mark.asyncio
    async def test_a_problem_at_startup_is_believed_at_once(self):
        """Hysteresis defends against a state that CHANGES; a starting point
        is not a change."""
        register_sensor("s", lambda: [ModuleSignal("rag", "missing")])
        w = StateWatcher(interval=0, confirmations=2)

        assert await w.prime() is OperationalState.LIMITED
        assert w.state is OperationalState.LIMITED, (
            "the state the UI reads must already say LIMITED after priming — "
            "waiting for confirmations here means the user is told a minute late"
        )

    @pytest.mark.asyncio
    async def test_a_clean_start_stays_normal(self):
        """Control: priming does not invent a problem when there is none."""
        w = StateWatcher(interval=0, confirmations=2)
        assert await w.prime() is OperationalState.NORMAL

    @pytest.mark.asyncio
    async def test_priming_leaves_no_streak_behind(self):
        """After priming, the hysteresis has to start from zero.

        A prime that set the state but kept a stale candidate/streak would let
        the very next reading flip it with one confirmation instead of two.
        """
        register_sensor("s", lambda: [ModuleSignal("rag", "missing")])
        w = StateWatcher(interval=0, confirmations=2)
        await w.prime()
        clear_sensors()  # everything recovered

        assert w.observe(OperationalState.NORMAL) is OperationalState.LIMITED, (
            "one reading must not undo the primed state"
        )
        assert w.observe(OperationalState.NORMAL) is OperationalState.NORMAL

    @pytest.mark.asyncio
    async def test_priming_records_what_it_saw(self):
        """/status has to be able to NAME the subsystem right after startup."""
        register_sensor("s", lambda: [ModuleSignal("rag", "missing")])
        w = StateWatcher(interval=0, confirmations=2)
        await w.prime()
        assert [s.name for s in w.last_signals] == ["rag"]


class TestStatusContract:
    """/status is what the UI reads to decide whether to warn the user.

    Mutation guard: drop operational_state or impaired_subsystems from the
    endpoint and these turn red — the banner would silently never appear
    again, which is exactly the failure this whole item is about.
    """

    def _client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from tests.core.endpoints.test_root import _TEST_KEY, make_app

        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", _TEST_KEY)
        return TestClient(make_app(config={}, modules={}))

    def test_status_reports_the_confirmed_state(self, monkeypatch):
        from tests.core.endpoints.test_root import _HEADERS

        resp = self._client(monkeypatch).get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["operational_state"] == "normal"
        assert body["impaired_subsystems"] == []

    def test_status_names_what_is_impaired(self, monkeypatch):
        from core.state_watcher import watcher
        from tests.core.endpoints.test_root import _HEADERS

        client = self._client(monkeypatch)
        register_sensor("s", lambda: [ModuleSignal("rag", "missing")])
        monkeypatch.setattr(watcher, "_confirmed", OperationalState.LIMITED)
        monkeypatch.setattr(
            watcher, "last_signals", (ModuleSignal("rag", "missing"),)
        )

        body = client.get("/status", headers=_HEADERS).json()
        assert body["operational_state"] == "limited"
        assert body["impaired_subsystems"] == ["rag"], (
            "the UI cannot warn about a subsystem the server will not name"
        )


class TestMemoryModulesAreDeclared:
    """The root cause of the black screen: a memory module that returns False
    is dropped without raising, and until now nothing recorded it."""

    def test_the_two_module_lists_have_not_drifted(self):
        """core declares the set; core/modules uses the same
        tuple as its import allowlist. They must not diverge — importing one
        from the other would add a frozen cross-package edge."""
        from core.operational_state import MEMORY_CORE_MODULES
        from core.modules.module_manager import (
            _MEMORY_CORE_MODULE_ORDER,
        )

        assert MEMORY_CORE_MODULES == _MEMORY_CORE_MODULE_ORDER

    @pytest.mark.asyncio
    async def test_a_memory_module_that_never_loads_is_flagged(self):
        """Mutation guard: remove the loop that flags the absent ones and this
        turns red — which is exactly the silence #889 was made of."""
        from unittest.mock import AsyncMock, MagicMock

        from core import lifespan_modules

        state = MagicMock()
        state.degraded_modules = []
        state.i18n = None
        # embeddings and memory came up; rag did not
        state.module_manager.load_memory_modules = AsyncMock(
            return_value={"embeddings": MagicMock(), "memory": MagicMock()}
        )
        app = MagicMock()
        app.state.modules = {}

        await lifespan_modules.load_memory_modules(
            app, state, lambda _i18n, _k, default, **kw: default
        )

        assert "rag" in state.degraded_modules, (
            "a memory module that never loaded must be recorded, or nothing "
            "downstream can warn the user"
        )
        assert "embeddings" not in state.degraded_modules

    def test_each_memory_module_id_matches_its_folder_name(self):
        """The flag above compares FOLDER NAMES against a dict the manager keys
        by MODULE_ID (core/modules/module_manager.py:_load_single_memory_module
        returns manifest.MODULE_ID). They happen to be equal today and nothing
        said they had to be.

        If a manifest ever renamed its id — "NexeRAG", say — every load would
        look like a failure to load: the banner would tell the user the search
        never started, forever, with the search working. A silent lie is worse
        than the silence it replaced.
        """
        import importlib

        from core.operational_state import MEMORY_CORE_MODULES

        for name in MEMORY_CORE_MODULES:
            manifest = importlib.import_module(f"memory.{name}.manifest")
            assert manifest.MODULE_ID == name, (
                f"memory/{name} declares MODULE_ID={manifest.MODULE_ID!r}. The "
                "startup check that flags a module as missing looks it up by "
                "folder name, so this rename would mark it degraded forever. "
                "Either keep the id, or make the check translate one to the other."
            )


class TestQdrantEye:
    """#891 — the watcher's Qdrant sensor could not fire.

    It read server_state.qdrant_available, which startup set to True
    unconditionally (in external mode without contacting the URL at all) and
    only shutdown ever set back to False. So the eye reported a constant, the
    'qdrant' entry of the interface's degraded_names was unreachable, and the
    doctrine 'one place decides, the rest report a signal' had a sensor that
    reported nothing.
    """

    @pytest.mark.asyncio
    async def test_a_store_that_does_not_answer_raises_the_signal(self, monkeypatch):
        from core import lifespan as lifespan_mod

        monkeypatch.setattr(lifespan_mod, "probe_qdrant", lambda: (False, "Connection refused"))
        lifespan_mod.server_state.qdrant_available = True  # the old lie

        signals = await lifespan_mod._qdrant_sensor()

        assert [s.name for s in signals] == ["qdrant"]
        assert signals[0].status == "missing"
        assert lifespan_mod.server_state.qdrant_available is False, (
            "the eye must refresh what /health and /status read, or they keep "
            "reporting the startup value forever"
        )

    @pytest.mark.asyncio
    async def test_a_responding_store_raises_nothing(self, monkeypatch):
        from core import lifespan as lifespan_mod

        monkeypatch.setattr(lifespan_mod, "probe_qdrant", lambda: (True, "6 collection(s)"))
        lifespan_mod.server_state.qdrant_available = False

        assert await lifespan_mod._qdrant_sensor() == []
        assert lifespan_mod.server_state.qdrant_available is True

    @pytest.mark.asyncio
    async def test_the_eye_asks_instead_of_reading_the_flag(self, monkeypatch):
        """Mutation guard: point the sensor back at server_state.qdrant_available
        and this turns red, because the flag says one thing and the store says
        the other — which is exactly the situation #891 describes."""
        from core import lifespan as lifespan_mod

        monkeypatch.setattr(lifespan_mod, "probe_qdrant", lambda: (False, "down"))
        lifespan_mod.server_state.qdrant_available = True

        signals = await lifespan_mod._qdrant_sensor()
        assert signals, "the sensor believed the flag instead of asking the store"

    @pytest.mark.asyncio
    async def test_the_probe_runs_off_the_event_loop(self, monkeypatch):
        """A blocking probe inline would stall every request while it waits."""
        import threading

        from core import lifespan as lifespan_mod

        loop_thread = threading.get_ident()
        seen: list[int] = []

        def _probe():
            seen.append(threading.get_ident())
            return True, "ok"

        monkeypatch.setattr(lifespan_mod, "probe_qdrant", _probe)
        await lifespan_mod._qdrant_sensor()

        assert seen and seen[0] != loop_thread, (
            "the probe ran on the event loop thread; a slow store would freeze the server"
        )
