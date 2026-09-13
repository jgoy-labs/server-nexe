"""C0 (ADR-007, the pipeline plan): TURN_STEPS is the map, not
the engine. This test freezes its SHAPE before run_turn (C1) exists on top of
it, so C1-C7 cannot silently add, drop or reorder a step, or quietly loosen a
must-have guarantee, while building the real engine.

Mutation check (documented, not automated here): commenting out any one
assertion below and reordering/renaming/removing a step in
`core/turn/steps.py` must turn exactly that assertion red, and no other.
"""
from __future__ import annotations

from core.turn.steps import GIVEN_BY_DOOR, TURN_STEPS, StepKind

# The order IS the contract (I2 of ADR-007). Reordering two steps, or
# adding/removing one, must fail this test — nothing else in the codebase
# enforces this today (Agent A audit, 2026-09-05: "no consta").
# 2026-09-06 (C1.2): `engine` moved before `budget` — deliberately, here and in
# ADR-007 §4 — because at BOTH doors the prompt budget is sized to the serving
# engine's context window (`get_effective_context_window(engine)` at the API,
# `ask_engine_window(engine)` inside the UI's engine loop). A budget computed
# before knowing the engine would be a budget for the wrong window.
EXPECTED_ORDER = (
    "validate", "authorize", "sanitize", "session", "persist_user_turn",
    "intent", "recall", "clock", "system_prompt", "engine", "budget",
    "generate", "postprocess", "persist_assistant_turn", "emit",
    "memory.write", "compact",
)

# The four steps ADR-007 names explicitly as must-have and non-replaceable
# (I5): sanejament, auth, and the two disk-commit points. A plugin must never
# be able to substitute these, even once C6 wires up workflow_engine.
CRITICAL_NON_REPLACEABLE = frozenset({
    "authorize", "sanitize", "persist_user_turn", "persist_assistant_turn",
})


def test_step_order_is_frozen():
    assert tuple(step.id for step in TURN_STEPS) == EXPECTED_ORDER


def test_no_duplicate_step_ids():
    ids = [step.id for step in TURN_STEPS]
    assert len(ids) == len(set(ids))


def test_critical_steps_are_must_have_and_non_replaceable():
    seen = set()
    for step in TURN_STEPS:
        if step.id in CRITICAL_NON_REPLACEABLE:
            seen.add(step.id)
            assert step.must_have, f"{step.id} must stay must_have=True"
            assert not step.replaceable, f"{step.id} must stay replaceable=False"
    assert seen == CRITICAL_NON_REPLACEABLE, (
        "one of the four critical steps disappeared from TURN_STEPS"
    )


def test_every_step_kind_is_a_valid_road():
    for step in TURN_STEPS:
        assert isinstance(step.kind, StepKind)


def test_doors_today_only_names_known_doors():
    for step in TURN_STEPS:
        assert step.doors_today <= {"ui", "api"}, step.id


def test_reads_are_satisfied_by_the_door_or_a_prior_step():
    """Referential integrity of the descriptor table: nothing reads a
    TurnContext key before something upstream (the door, or an earlier step)
    has written it. This does not run any step — it only proves the map is
    internally consistent, which is the whole point of C0."""
    known = set(GIVEN_BY_DOOR)
    for step in TURN_STEPS:
        missing = step.reads - known
        assert not missing, (
            f"step '{step.id}' reads {sorted(missing)} before any earlier "
            "step (or the door) writes it"
        )
        known |= step.writes


def test_only_generate_and_the_post_commit_steps_are_llm():
    llm_ids = {step.id for step in TURN_STEPS if step.kind is StepKind.LLM}
    assert llm_ids == {"generate", "memory.write", "compact"}
