"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_folded_is_measured.py
Description: `FOLDED_BASELINE` must be a measurement, not a decoration.

             Why this exists: from C4.2 until 19/09 the contract read
             `FOLDED_BASELINE = {"api": 0, "ui": 0}` and `test_folded_never_grows`
             compared it with `==` — against `ctx.usage["folded"]`, a bucket NO
             production line ever wrote to. `core/turn/trace.py:56` read it;
             nothing filled it. The assertion was therefore true by
             construction, and an audit measured what that cost: folding the
             UI's `recall` back into `return` (a real fold, the exact
             regression the gate names) left `test_folded_never_grows` GREEN.

             The engine now compares what each step actually wrote against
             `Step.writes_always` and fills the bucket itself. This file is the
             gate ON that mechanism: `test_folded_never_grows` can only protect
             the pipeline while a folded step really does show up in the
             bucket, and nothing else in the suite would notice if the recorder
             went quiet again — that is precisely the failure it went unnoticed
             through for four sub-phases.

             Both checks drive the REAL engine over the REAL step table; only
             the adapters are stand-ins, which is the one thing a fold is.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.turn.context import TurnContext
from core.turn.folded import FOLDED_BASELINE
from core.turn.run import run_turn
from core.turn.steps import TURN_STEPS

#: Steps whose work leaves no mark on the context, so a fold cannot be seen
#: this way: they persist, authorise or hand work to a queue. Listed here so
#: the count below is explicit rather than implied — if a step gains a
#: `writes_always`, this test gets stricter on its own.
WATCHED = [s for s in TURN_STEPS if s.writes_always]


def _table(fold: str = "") -> dict:
    """An adapter table that writes what each step declares — except `fold`,
    which returns without doing anything, exactly as a folded step would."""
    def make(step):
        async def adapter(ctx: TurnContext) -> None:
            if step.id == fold:
                return
            for name in step.writes_always:
                setattr(ctx, name, getattr(ctx, name, None) or "x")
        return adapter
    return {s.id: make(s) for s in TURN_STEPS}


def _ctx() -> TurnContext:
    return TurnContext(turn_id="t", entry="api", principal="k")


async def test_a_full_table_folds_nothing():
    """The control: every step writing what it declares folds nothing.

    Without this, the test below would pass just as well against a recorder
    that marked EVERY step folded.
    """
    ctx = _ctx()
    await run_turn(ctx, _table())
    assert ctx.usage.get("folded", {}) == {}, (
        "a table where every step writes what it declares recorded a fold"
    )
    assert len(ctx.usage.get("folded", {})) == FOLDED_BASELINE["api"]


@pytest.mark.parametrize("step", WATCHED, ids=lambda s: s.id)
async def test_a_folded_step_is_recorded(step):
    """Fold one watched step; the engine must name it.

    Parametrised over every step with a `writes_always`, so the mechanism is
    proven for each of them and not just for whichever one a single example
    happened to pick.
    """
    ctx = _ctx()
    await run_turn(ctx, _table(fold=step.id))
    folded = ctx.usage.get("folded", {})
    assert step.id in folded, (
        f"`{step.id}` returned without writing any of "
        f"{sorted(step.writes_always)} and the engine did not record it as "
        f"folded — the recorder is quiet again, and `FOLDED_BASELINE` is back "
        f"to guarding a bucket nobody fills. Recorded: {folded}"
    )
    assert sorted(step.writes_always)[0] in folded[step.id]


async def test_writes_always_is_a_subset_of_writes():
    """A step cannot be required to always write a field it never declares."""
    for s in TURN_STEPS:
        assert s.writes_always <= s.writes, (
            f"`{s.id}` declares writes_always={sorted(s.writes_always)} which "
            f"is not covered by writes={sorted(s.writes)}"
        )


async def test_the_watch_covers_the_steps_that_carry_the_turn():
    """The count is written down, so shrinking the watch is a visible act.

    Ten of the seventeen steps are watched this way. The other seven
    (`validate`, `authorize`, `persist_user_turn`, `persist_assistant_turn`,
    `emit`, `memory.write`, `compact`) write no context field on every turn —
    `steps.py` says why for each — and need a behavioural test to catch a fold.
    That gap is real and this number is where it is stated.
    """
    assert len(WATCHED) == 10, (
        f"the write-watch now covers {len(WATCHED)} steps, not 10: "
        f"{[s.id for s in WATCHED]}"
    )
