"""API providers, phase 3 — the hosted engines' OWN gate (`core/turn/gate.py`).

The local gate has one slot because two generations on one GPU crashed Metal. An answer from a
provider uses no GPU here and takes as long as the provider takes: sharing the one slot would make
a cloud answer block every local engine for its whole duration, and the other way round. These
tests pin that the two gates are two, that each door and each internal step takes the right one,
and that a cloud answer that hangs cannot leave a local turn hanging (nor the contrary).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from core.turn import gate as gate_module
from core.turn.context import TurnContext
from core.turn.engine_hold import BUSY_DETAIL, EngineHold
from core.turn.gate import (
    DEFAULT_CLOUD_GATE_SLOTS, ENV_CLOUD_GATE_SLOTS, EngineGate, Priority, attach_cloud_gate, attach_engine_gate,
    gate_for,
)
from core.turn.post_commit import PostCommitQueue

HOSTED = SimpleNamespace(runs_in_the_cloud=True)


class _Request:
    async def is_disconnected(self) -> bool:
        return False


def _state(local: int = 1, cloud: int = 1):
    return SimpleNamespace(engine_gate=EngineGate(slots=local), cloud_engine_gate=EngineGate(slots=cloud))


def _ctx(state, engine, turn="t") -> TurnContext:
    return TurnContext(turn_id=turn, request=_Request(), app_state=state, engine=engine)


# ------------------------------------------------------------------ which gate

@pytest.mark.parametrize("engine", ["api", "API", HOSTED])
def test_a_hosted_engine_gets_the_cloud_gate_by_name_or_by_what_the_module_declares(engine):
    state = _state()
    assert gate_for(state, engine) is state.cloud_engine_gate
    assert gate_for(state, engine) is not state.engine_gate


@pytest.mark.parametrize("engine", [None, "mlx", "llama_cpp", "ollama", "mystery", SimpleNamespace(), SimpleNamespace(runs_in_the_cloud=False)])
def test_everything_else_gets_the_local_gate(engine):
    state = _state()
    assert gate_for(state, engine) is state.engine_gate
    assert gate_for(state) is state.engine_gate


def test_a_hosted_engine_without_a_gate_of_its_own_never_borrows_the_local_slot(caplog):
    """A missing cloud gate must not make the cloud block the local engines: it is unguarded (and said so), like
    the test harnesses `gate_for` was always lenient with — never the single local slot."""
    state = SimpleNamespace(engine_gate=EngineGate(slots=1))
    gate = gate_for(state, "api")
    assert gate is not state.engine_gate and gate is not None
    assert gate.snapshot()["slots"] > 1000
    assert gate_for(state, "ollama") is state.engine_gate


def test_the_missing_gate_is_named_in_the_warning(monkeypatch, caplog):
    monkeypatch.setattr(gate_module, "_warned_fallback", False)
    import logging
    with caplog.at_level(logging.WARNING, logger=gate_module.logger.name):
        gate_for(SimpleNamespace(), "api")
    assert "cloud_engine_gate" in caplog.text and "UNGUARDED" in caplog.text


# ---------------------------------------------------------------------- slots

def test_the_cloud_gate_has_its_own_slots_with_a_default_that_is_not_the_local_one(monkeypatch):
    monkeypatch.delenv(ENV_CLOUD_GATE_SLOTS, raising=False)
    monkeypatch.delenv("NEXE_ENGINE_SLOTS", raising=False)
    server = SimpleNamespace()
    cloud, local = attach_cloud_gate(server), attach_engine_gate(server)
    assert cloud is not local and server.cloud_engine_gate is cloud and server.engine_gate is local
    assert cloud.snapshot()["slots"] == DEFAULT_CLOUD_GATE_SLOTS == 4
    assert local.snapshot()["slots"] == 1
    assert attach_cloud_gate(server) is cloud, "attaching again returns the one that exists"


@pytest.mark.parametrize("value, slots", [("2", 2), ("8", 8), ("0", 1), ("-3", 1), ("many", DEFAULT_CLOUD_GATE_SLOTS), ("", DEFAULT_CLOUD_GATE_SLOTS)])
def test_the_cloud_slots_are_configurable_and_a_typo_never_removes_the_bound(monkeypatch, value, slots):
    monkeypatch.setenv(ENV_CLOUD_GATE_SLOTS, value)
    assert attach_cloud_gate(SimpleNamespace()).snapshot()["slots"] == slots


def test_the_local_slots_are_not_touched_by_the_cloud_variable(monkeypatch):
    monkeypatch.setenv(ENV_CLOUD_GATE_SLOTS, "9")
    monkeypatch.delenv("NEXE_ENGINE_SLOTS", raising=False)
    assert attach_engine_gate(SimpleNamespace()).snapshot()["slots"] == 1


def test_the_lifespan_attaches_and_mirrors_both_gates(monkeypatch):
    from core import lifespan_sessions as ls
    import asyncio as _asyncio

    server, app = SimpleNamespace(), SimpleNamespace(state=SimpleNamespace())
    _asyncio.run(ls._startup_engine_gate(server))
    ls._expose_engine_gate(app, server)
    assert app.state.engine_gate is server.engine_gate and app.state.cloud_engine_gate is server.cloud_engine_gate
    assert app.state.engine_gate is not app.state.cloud_engine_gate


def test_the_post_commit_queue_is_built_with_the_cloud_gate_too():
    from core import lifespan_sessions as ls
    import asyncio as _asyncio

    async def go():
        server = SimpleNamespace()
        await ls._startup_engine_gate(server)
        await ls._startup_post_commit_queue(server)
        queue = server.post_commit_queue
        try:
            assert queue._gate is server.engine_gate and queue._cloud_gate is server.cloud_engine_gate
            assert server._post_commit_task is queue._task and server._post_commit_cloud_task is queue._cloud_task
            assert queue._cloud_task is not None and queue._cloud_task is not queue._task
        finally:
            await queue.stop()

    _asyncio.run(go())


# ------------------------------------------------------------- the two do not wait for each other

async def test_a_cloud_answer_in_flight_does_not_block_a_local_turn():
    state = _state(local=1, cloud=1)
    async with EngineHold(_ctx(state, HOSTED, "cloud")):
        async with asyncio.timeout(1.0):
            async with EngineHold(_ctx(state, "ollama", "local")):
                assert len(state.engine_gate._holders) == 1 and len(state.cloud_engine_gate._holders) == 1


async def test_a_local_turn_in_flight_does_not_block_a_cloud_answer():
    state = _state(local=1, cloud=1)
    async with EngineHold(_ctx(state, "mlx", "local")):
        async with asyncio.timeout(1.0):
            async with EngineHold(_ctx(state, "api", "cloud")):
                assert len(state.engine_gate._holders) == 1 and len(state.cloud_engine_gate._holders) == 1


async def test_a_cloud_answer_that_never_comes_back_leaves_local_turns_free_to_run_and_finish(monkeypatch):
    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.2")
    state = _state(local=1, cloud=1)
    hung = EngineHold(_ctx(state, "api", "hung"))
    await hung.open()  # the provider has not answered, and holds its slot
    try:
        for number in range(3):  # three local turns, one after another, none waits on the hung one
            async with asyncio.timeout(1.0):
                async with EngineHold(_ctx(state, "ollama", f"local-{number}")):
                    pass
        assert len(state.cloud_engine_gate._holders) == 1 and len(state.engine_gate._holders) == 0
    finally:
        await hung.release()
    assert len(state.cloud_engine_gate._holders) == 0


async def test_the_cloud_gate_still_bounds_the_cloud_and_answers_429_not_a_hang(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    state = _state(local=1, cloud=2)
    first, second = EngineHold(_ctx(state, "api", "a")), EngineHold(_ctx(state, "api", "b"))
    await first.open()
    await second.open()
    try:
        with pytest.raises(HTTPException) as busy:
            await EngineHold(_ctx(state, "api", "c")).open()
        assert busy.value.status_code == 429 and busy.value.detail == BUSY_DETAIL
        async with asyncio.timeout(1.0):
            async with EngineHold(_ctx(state, "ollama", "local")):
                pass  # the full cloud gate is not the local one
    finally:
        await first.release()
        await second.release()
    assert len(state.cloud_engine_gate._holders) == 0


async def test_a_held_slot_is_given_back_to_the_gate_it_came_from_when_the_hold_ends():
    state = _state(local=1, cloud=1)
    async with EngineHold(_ctx(state, HOSTED)):
        assert state.cloud_engine_gate.snapshot()["free"] == 0 and state.engine_gate.snapshot()["free"] == 1
    assert state.cloud_engine_gate.snapshot()["free"] == 1 and state.engine_gate.snapshot()["free"] == 1


# ------------------------------------------------------------------ the internal steps

async def test_a_post_commit_job_for_a_hosted_engine_runs_under_the_cloud_gate_not_the_local_one():
    local, cloud = EngineGate(slots=1), EngineGate(slots=1)
    queue = PostCommitQueue(local, cloud_gate=cloud)
    queue.start()
    seen: dict = {}

    async def job(_cancel) -> dict:
        seen["local_held"] = len(local._holders)
        seen["cloud_held"] = len(cloud._holders)
        return {"outcome": "ok"}

    try:
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="compact", run=job, cloud=True)
        await queue.drain()
        assert seen == {"local_held": 0, "cloud_held": 1}
        seen.clear()
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="memory.write", run=job)
        await queue.drain()
        assert seen == {"local_held": 1, "cloud_held": 0}, "a local job still takes the local slot"
    finally:
        await queue.stop()
    assert len(local._holders) == 0 and len(cloud._holders) == 0, "every slot was given back"


async def test_a_hosted_job_waits_on_the_cloud_slot_and_leaves_the_local_one_alone():
    local, cloud = EngineGate(slots=1), EngineGate(slots=1)
    queue = PostCommitQueue(local, cloud_gate=cloud)
    queue.start()
    holder = await cloud.acquire(Priority.USER_TURN, holder="a user turn on the API")
    ran = asyncio.Event()

    async def job(_cancel) -> dict:
        ran.set()
        return {"outcome": "ok"}

    try:
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="compact", run=job, cloud=True)
        await asyncio.sleep(0.1)
        assert not ran.is_set(), "the cloud slot is taken: the hosted job waits for it"
        assert local.snapshot()["free"] == 1, "and the local slot was never touched"
        await cloud.release(holder)
        await asyncio.wait_for(ran.wait(), timeout=1.0)
        await queue.drain()
    finally:
        await queue.stop()


async def test_a_queue_built_without_a_cloud_gate_still_keeps_a_hosted_job_off_the_local_slot():
    local = EngineGate(slots=1)
    queue = PostCommitQueue(local)
    assert queue._cloud_gate is not local and queue._cloud_gate.snapshot()["slots"] == DEFAULT_CLOUD_GATE_SLOTS


def test_the_enqueue_of_a_step_says_which_gate_by_the_engine_the_turn_runs_on():
    """`run._enqueue_post_commit` marks the job hosted from the engine the turn is on: the module's own
    declaration at the web door, the name at /v1."""
    from core.turn import run
    from core.turn.steps import StepKind  # noqa: F401  (the step shape is the real one below)

    queued: list = []

    class Queue:
        def enqueue(self, priority, **kwargs):
            queued.append(kwargs)

    step = SimpleNamespace(id="compact")

    async def adapter(ctx):
        return None

    for engine, hosted in ((HOSTED, True), ("api", True), ("ollama", False), ("mlx", False), (None, False)):
        queued.clear()
        run._enqueue_post_commit(_ctx(_state(), engine), step, adapter, Queue())
        assert queued[0]["cloud"] is hosted, engine


# --------------------------------------------------- the names an operator types, spelled out

def test_the_variable_an_operator_sets_is_this_one_and_its_default_is_declared_where_they_look(monkeypatch):
    """The literal, not the constant: a test that reads the constant back says nothing about the name."""
    assert ENV_CLOUD_GATE_SLOTS == "NEXE_CLOUD_ENGINE_SLOTS"
    monkeypatch.setenv("NEXE_CLOUD_ENGINE_SLOTS", "7")
    assert attach_cloud_gate(SimpleNamespace()).snapshot()["slots"] == 7
    from core.config_catalog import CATALOG

    (entry,) = [k for k in CATALOG if k.env == "NEXE_CLOUD_ENGINE_SLOTS"]
    assert entry.default == DEFAULT_CLOUD_GATE_SLOTS == 4 and entry.id == "cloud_engine_slots"
    assert "local slot" in entry.description


def test_the_lifespan_says_when_a_gate_is_missing_and_mirrors_nothing_it_does_not_have(caplog):
    from core import lifespan_sessions as ls

    with caplog.at_level(logging.WARNING, logger=ls.logger.name):
        app = SimpleNamespace(state=SimpleNamespace())
        ls._expose_engine_gate(app, SimpleNamespace(engine_gate=EngineGate(slots=1)))
        assert not hasattr(app.state, "cloud_engine_gate") and "Cloud EngineGate not attached" in caplog.text
        caplog.clear()
        app = SimpleNamespace(state=SimpleNamespace())
        ls._expose_engine_gate(app, SimpleNamespace())
        assert not hasattr(app.state, "engine_gate") and not hasattr(app.state, "cloud_engine_gate")
        assert "EngineGate not attached" in caplog.text


def test_attaching_the_queue_uses_the_gates_it_is_given_and_otherwise_the_servers_own():
    from core.turn.post_commit import attach_post_commit_queue

    local, cloud = EngineGate(slots=1), EngineGate(slots=2)
    explicit = attach_post_commit_queue(SimpleNamespace(), gate=local, cloud_gate=cloud)
    assert explicit._gate is local and explicit._cloud_gate is cloud
    server = SimpleNamespace()
    own_local, own_cloud = attach_engine_gate(server), attach_cloud_gate(server)
    implicit = attach_post_commit_queue(server)
    assert implicit._gate is own_local and implicit._cloud_gate is own_cloud
    assert attach_post_commit_queue(server) is implicit, "attaching again returns the queue that exists"


async def test_a_job_holds_its_slot_under_its_own_name_and_with_its_own_cancel_signal():
    import threading

    local, cloud = EngineGate(slots=1), EngineGate(slots=1)
    queue = PostCommitQueue(local, cloud_gate=cloud)
    queue.start()
    seen: dict = {}
    cancel = threading.Event()

    async def job(_cancel) -> dict:
        (slot,) = cloud._holders.values()
        seen["holder"], seen["cancel"], seen["priority"] = slot.holder, slot.cancel, slot.priority
        return {"outcome": "ok"}

    try:
        queue.enqueue(Priority.COMPACT, turn_id="turn-77", session_id="s", step_id="compact", run=job, cancel=cancel, cloud=True)
        await queue.drain()
    finally:
        await queue.stop()
    assert seen == {"holder": "turn-77", "cancel": cancel, "priority": Priority.COMPACT}


def test_a_job_is_local_unless_it_says_it_is_hosted():
    queue = PostCommitQueue(EngineGate(slots=1))
    job = queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="compact", run=None)
    assert job.cloud is False
    assert queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="x", run=None, cloud=True).cloud is True


# ----------------------------------------- one slow provider must not hold the local jobs back

async def test_a_hosted_job_stuck_behind_a_full_cloud_gate_does_not_hold_back_a_local_one():
    """The queue used to have ONE worker: a hosted job waiting for its gate (no timeout) kept every job behind it
    waiting too, local ones included, for as long as the provider took."""
    local, cloud = EngineGate(slots=1), EngineGate(slots=1)
    queue = PostCommitQueue(local, cloud_gate=cloud)
    queue.start()
    held = await cloud.acquire(Priority.USER_TURN, holder="a user turn waiting on the provider")
    order: list = []

    async def job(name: str):
        async def run(_cancel) -> dict:
            order.append(name)
            return {"outcome": "ok"}
        return run

    try:
        queue.enqueue(Priority.COMPACT, turn_id="t1", session_id="s1", step_id="compact", run=await job("hosted"), cloud=True)
        queue.enqueue(Priority.COMPACT, turn_id="t2", session_id="s2", step_id="compact", run=await job("local"))
        async with asyncio.timeout(1.0):
            while "local" not in order:
                await asyncio.sleep(0.01)
        assert order == ["local"], "the local job ran while the hosted one still waits for the provider's slot"
        assert queue.pending("s1") == set() and queue.running("s1") == "compact", "the hosted job is the one in flight"
        await cloud.release(held)
        await queue.drain()
        assert order == ["local", "hosted"]
    finally:
        await queue.stop()


async def test_both_workers_start_stop_and_drain_together():
    queue = PostCommitQueue(EngineGate(slots=1), cloud_gate=EngineGate(slots=1))
    first = queue.start()
    cloud_task = queue._cloud_task
    assert first is queue._task and first is not cloud_task and not first.done() and not cloud_task.done()
    assert queue.start() is first and queue._cloud_task is cloud_task, "starting again is a no-op while they are alive"
    done: list = []

    async def run(_cancel) -> dict:
        done.append(1)
        return {"outcome": "ok"}

    queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="a", run=run, cloud=True)
    queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="b", run=run)
    await queue.drain()
    assert done == [1, 1], "drain waits for the jobs of both queues"
    await queue.stop()
    assert first.done() and cloud_task.done() and queue._task is None and queue._cloud_task is None
    queue.start()  # a stopped queue can be started again
    assert queue._task is not None and queue._cloud_task is not None
    await queue.stop()


async def test_a_preempted_hosted_job_is_put_back_on_the_hosted_queue_and_a_user_turn_signals_both_kinds():
    import threading

    local, cloud = EngineGate(slots=1), EngineGate(slots=1)
    queue = PostCommitQueue(local, cloud_gate=cloud)
    queue.start()
    attempts: list = []
    release = asyncio.Event()

    async def hosted(cancel) -> dict:
        attempts.append("hosted")
        if len(attempts) == 1:
            await release.wait()
            return {"outcome": "preempted"}
        return {"outcome": "ok"}

    local_seen: dict = {}
    local_release = asyncio.Event()

    async def local_job(cancel) -> dict:
        local_seen["cancel"] = cancel
        await local_release.wait()
        return {"outcome": "ok"}

    hosted_cancel, local_cancel = threading.Event(), threading.Event()
    try:
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="same", step_id="compact", run=hosted, cancel=hosted_cancel, cloud=True)
        queue.enqueue(Priority.MEMORY_WRITE, turn_id="t", session_id="same", step_id="describe_image", run=local_job, cancel=local_cancel)
        async with asyncio.timeout(1.0):
            while len(attempts) < 1 or "cancel" not in local_seen:
                await asyncio.sleep(0.01)
        assert queue.running("same") in ("compact", "describe_image")
        queue.preempt("same")
        assert hosted_cancel.is_set() and local_cancel.is_set(), "a user turn signals the running job of EITHER kind"
        release.set()
        local_release.set()
        await queue.drain()
        assert attempts == ["hosted", "hosted"], "the preempted hosted job was queued again, and ran on its own worker"
    finally:
        await queue.stop()
    assert queue.running("same") is None and queue.running(None) is None


# ------------------------------------ the second call of a turn and the atomiser take the engine's own gate

def _reprompt_ctx(state, engine):
    return TurnContext(turn_id="t-rp", app_state=state, system_prompt="sys", lang="ca", engine=engine)


def _answering(*chunks):
    async def gen():
        for chunk in chunks:
            yield chunk

    return lambda system_prompt: gen()


@pytest.mark.parametrize("engine, busy, free", [
    (HOSTED, "engine_gate", "cloud_engine_gate"),
    ("api", "engine_gate", "cloud_engine_gate"),
    ("ollama", "cloud_engine_gate", "engine_gate"),
    ("mlx", "cloud_engine_gate", "engine_gate"),
])
async def test_the_reprompt_waits_for_the_gate_of_its_own_engine_and_for_no_other(monkeypatch, engine, busy, free):
    """The other gate is full and the one of its engine is free: the second call goes through. The slot it takes is
    the one of its own gate (and is given back)."""
    from core.turn import policy

    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    state = _state(local=1, cloud=1)
    held = await getattr(state, busy).acquire(Priority.USER_TURN, holder="another turn, on the other kind of engine")
    ctx = _reprompt_ctx(state, engine)
    out = [c async for c in policy.reprompt_chunks(ctx, ["l'usuari es diu Aran"], call=_answering("Encantat."),
                                                   engine_name="api", model="m")]
    assert "".join(out) == "Encantat."
    assert getattr(state, free).snapshot()["free"] == getattr(state, free).snapshot()["slots"], "its own slot was given back"
    await getattr(state, busy).release(held)


@pytest.mark.parametrize("engine, own", [(HOSTED, "cloud_engine_gate"), ("ollama", "engine_gate")])
async def test_the_reprompt_is_skipped_not_hung_when_its_own_gate_is_full(monkeypatch, engine, own):
    from core.turn import policy

    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    state = _state(local=1, cloud=1)
    held = await getattr(state, own).acquire(Priority.USER_TURN, holder="a turn on the same engine")
    called: list = []

    def call(system_prompt):
        called.append(1)
        return _answering("x")(system_prompt)

    out = [c async for c in policy.reprompt_chunks(_reprompt_ctx(state, engine), ["f"], call=call, engine_name="e", model=None)]
    assert out == [] and called == []
    await getattr(state, own).release(held)


@pytest.mark.parametrize("engine, busy, free", [
    (HOSTED, "engine_gate", "cloud_engine_gate"), ("ollama", "cloud_engine_gate", "engine_gate"),
])
async def test_the_atomiser_takes_the_slot_of_the_engine_it_will_ask(monkeypatch, engine, busy, free):
    from plugins.web_ui_module.api.turn_adapters import _atomiser_slot

    monkeypatch.setenv("NEXE_ENGINE_GATE_WAIT_S", "0.05")
    state = _state(local=1, cloud=1)
    held = await getattr(state, busy).acquire(Priority.USER_TURN, holder="the other kind of engine")
    ctx = TurnContext(turn_id="t-at", app_state=state)
    ctx.facts = ["l'usuari es diu Aran i viu a Girona"]  # a compound fact: it will be atomised
    taken_engine, gate, slot = await _atomiser_slot(ctx, engine)
    try:
        assert taken_engine is engine and gate is getattr(state, free) and slot is not None
        assert getattr(state, free).snapshot()["free"] == 0, "it holds a slot of its own engine's gate"
    finally:
        await gate.release(slot)
        await getattr(state, busy).release(held)


async def test_what_runs_is_reported_for_either_kind_and_for_nobody_when_idle():
    local, cloud = EngineGate(slots=1), EngineGate(slots=1)
    queue = PostCommitQueue(local, cloud_gate=cloud)
    queue.start()
    release_local, release_cloud = asyncio.Event(), asyncio.Event()
    started: list = []

    def job(name, release):
        async def run(_cancel) -> dict:
            started.append(name)
            await release.wait()
            return {"outcome": "ok"}
        return run

    try:
        assert queue.running("only-local") is None
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="only-local", step_id="compact", run=job("l", release_local))
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="only-cloud", step_id="describe_image", run=job("c", release_cloud), cloud=True)
        async with asyncio.timeout(1.0):
            while len(started) < 2:
                await asyncio.sleep(0.01)
        assert queue.running("only-local") == "compact", "a LOCAL job is reported too"
        assert queue.running("only-cloud") == "describe_image"
        assert queue.running("somebody-else") is None
        release_local.set()
        release_cloud.set()
        await queue.drain()
        assert queue.running("only-local") is None and queue.running("only-cloud") is None
    finally:
        await queue.stop()


async def test_stopping_a_queue_that_was_never_started_is_fine():
    queue = PostCommitQueue(EngineGate(slots=1), cloud_gate=EngineGate(slots=1))
    await queue.stop()
    assert queue._task is None and queue._cloud_task is None
    queue.start()
    await queue.stop()


async def test_draining_gives_up_when_a_job_never_ends_instead_of_waiting_for_ever():
    queue = PostCommitQueue(EngineGate(slots=1), cloud_gate=EngineGate(slots=1))
    queue.start()
    never = asyncio.Event()

    async def run(_cancel) -> dict:
        await never.wait()
        return {"outcome": "ok"}

    try:
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="compact", run=run, cloud=True)
        with pytest.raises(asyncio.TimeoutError):
            await queue.drain(timeout=0.1)
    finally:
        never.set()
        await queue.stop()


async def test_the_shutdown_cancels_the_hosted_worker_as_well_as_the_local_one(monkeypatch):
    """A hosted job in flight to a provider must not outlive the shutdown: both workers are among the background
    tasks the lifespan cancels before the stores are torn down."""
    from core import lifespan
    from core.lifespan import server_state

    queue = PostCommitQueue(EngineGate(slots=1), cloud_gate=EngineGate(slots=1))
    queue.start()
    stuck = asyncio.Event()

    async def run(_cancel) -> dict:
        await stuck.wait()
        return {"outcome": "ok"}

    queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="compact", run=run, cloud=True)
    await asyncio.sleep(0.05)  # the hosted job is in flight
    for attr in ("_cleanup_task", "_session_cleanup_task", "_prewarm_task", "_knowledge_ingest_task", "_dreaming_task",
                 "_dreaming_cycle"):
        monkeypatch.setattr(server_state, attr, None, raising=False)
    monkeypatch.setattr(server_state, "_post_commit_task", queue._task, raising=False)
    monkeypatch.setattr(server_state, "_post_commit_cloud_task", queue._cloud_task, raising=False)
    await lifespan._cancel_background_tasks()
    assert queue._task.done() and queue._cloud_task.done()
    assert queue.running("s") is None, "the in-flight hosted job was torn down with its worker"


async def test_a_preempted_hosted_job_is_requeued_on_the_hosted_queue_and_always_run_by_the_hosted_worker():
    import threading

    queue = PostCommitQueue(EngineGate(slots=1), cloud_gate=EngineGate(slots=1))
    queue.start()
    workers: list = []
    sizes: list = []

    async def hosted(cancel) -> dict:
        workers.append(asyncio.current_task())
        if len(workers) == 1:
            sizes.append((queue._queue.qsize(), queue._cloud_queue.qsize()))
            return {"outcome": "preempted"}
        return {"outcome": "ok"}

    try:
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="s", step_id="compact", run=hosted, cancel=threading.Event(), cloud=True)
        await queue.drain()
    finally:
        await queue.stop()
    assert len(workers) == 2 and all(task is not None for task in workers)
    assert workers[0] is workers[1], "the same worker, the hosted one, ran both attempts"
    assert queue._queue.qsize() == 0 and queue._cloud_queue.qsize() == 0


async def test_a_local_job_is_never_run_by_the_hosted_worker_and_the_other_way_round():
    queue = PostCommitQueue(EngineGate(slots=1), cloud_gate=EngineGate(slots=1))
    queue.start()
    ran: dict = {}

    def job(name):
        async def run(_cancel) -> dict:
            ran[name] = asyncio.current_task()
            return {"outcome": "ok"}
        return run

    local_task, cloud_task = queue._task, queue._cloud_task
    try:
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="a", step_id="x", run=job("local"))
        queue.enqueue(Priority.COMPACT, turn_id="t", session_id="b", step_id="x", run=job("hosted"), cloud=True)
        await queue.drain()
    finally:
        await queue.stop()
    assert ran["local"] is local_task and ran["hosted"] is cloud_task
