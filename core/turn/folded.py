"""The two numbers C4 brought down to zero, in one place (ADR-007, C4.0-C4.2).

A step is FOLDED at a door when its behaviour lives inside another step's
function or at the door itself: the adapter recorded where (a `_folded()`
helper in each door's table) and the trace never pretended the step ran.
While any step was folded, "both doors run the same sequence" was a sentence
about ids, not about behaviour — a folded adapter registers its step id
exactly like a real one, so the sequences already matched without the turns
matching.

`FOLDED_BASELINE` was therefore the decreasing line of the whole C4 phase, and
the single source of truth for it. **C4.2 brought it to zero at both doors**,
and with it `test_folded_never_grows` went from `<=` to `== 0`: from here on a
sub-fase that folds a step again turns the I1 contract red instead of quietly
spending the budget an earlier one left.

Where the numbers came from, and where each step went:

* **api: 5 → 3 → 0.** `intent`, `postprocess`, `memory.write` and `compact`
  left the list at C3.1-C3.4; `authorize` and `sanitize` at C4.1
  (`core/turn/authorize.py`, `core/turn/validate.py`); `recall`, `clock` and
  `system_prompt` at C4.2, when `_build_rag_and_system_prompt` — the one
  function `budget` called whole, and the reason those three had nowhere of
  their own — was decomposed into `core/turn/recall.py`,
  `core/turn/prompt.py` and what is left of it, `_assemble_v1_messages`.
* **ui: 4 → 2 → 0.** `compact` left at C2.2, `authorize`/`sanitize` at C4.1,
  and `recall`/`clock` at C4.2: retrieval was folded inside
  `_build_turn_context` and the on-demand clock inside
  `_assemble_engine_messages`, both of which `budget` called. They are the
  same two functions the other door now runs.

Both `_folded()` helpers are gone with the last of their callers: a factory
that manufactures a "this step did not really run" record has no reason to
exist in a pipeline where every step does. Re-folding a step means writing it
again, deliberately, which is the point.

**And that is exactly what left this number guarding nothing (C4.3-c).** With
the helpers went the only writers of `ctx.usage["folded"]`, so from C4.2 until
19/09 the bucket was filled by no production line at all —
`core/turn/trace.py:56` read it, nothing wrote it — and `== 0` was true by
construction. An audit measured the cost: folding the UI's `recall` back into
a bare `return`, the precise regression this gate is named for, left
`test_folded_never_grows` GREEN. A thermometer is not a fever just because it
reads zero; this one was unplugged.

The engine fills the bucket itself now. Each step declares in
`steps.py::Step.writes_always` the context fields it assigns on EVERY turn it
completes — measured across real turns, not asserted — and `run.py::_finish_ok`
records a step that wrote none of them as folded. **Ten of the seventeen steps
are watched this way.** The other seven (`validate`, `authorize`,
`persist_user_turn`, `persist_assistant_turn`, `emit`, `memory.write`,
`compact`) leave no mark on the context on every turn, so a fold in them is
invisible here and needs a behavioural test; `steps.py` says why for each, and
`tests/core/turn/test_folded_is_measured.py` pins the count so that narrowing
the watch is a visible act rather than a silent one.

`DESIGN_DEGRADATIONS` is the other half of the same budget: the limits C3
declared in writing and left for C4 to close. Two at C3; one since C4.5;
none since C4.6-b.

* `postprocess` — CLOSED at C4.6-b. `/v1` streaming walks `stream_turn`.
  The facts are read from the raw text while `SseCleaner` still hides the
  tags from the client, and a reply that was only tags asks the model again.
* `reprompt` — CLOSED at C4.5 (26/09). `/v1`'s JSON reply spends the second
  generation D3 asks for, through `core/turn/policy.py::reprompt_chunks` — the
  one call the web door makes too. The streaming shape of that same call
  landed with `postprocess` at C4.6-b.

The other `degraded` entries an API turn can record are environment guards — a
missing `session_manager`/`memory_helper`, an engine with no live module — and
stay: they say a healthy turn had something missing, not that the design has a
hole. A healthy turn records none of them, which is why the contract test
asserts a subset of THIS set and not of every degradation the code can write.

This module is data: no function, no class, no behaviour. Its only import is
`from __future__ import annotations`, a compiler directive with no runtime
dependency — so it pulls in nothing at all, from `core/` or anywhere else, and
the layering gate has nothing to say about it.
"""
from __future__ import annotations

#: Folded steps per door. Zero since C4.2, and the I1 contract test compares
#: with `==`: a sub-fase may not fold a step again. Since C4.3-c the engine
#: fills the bucket this counts (`run.py::_finish_ok` against
#: `Step.writes_always`), so the comparison measures the pipeline instead of an
#: empty dict — see this module's docstring for the two months it did not.
FOLDED_BASELINE: dict[str, int] = {"api": 0, "ui": 0}

#: The step ids whose degradation is a DESIGN limit C3 declared and C4 closes,
#: as opposed to an environment guard firing. A healthy turn records none.
#: `reprompt` left the set at C4.5; `postprocess` left it at C4.6-b, when
#: `/v1` streaming walks `stream_turn` and reads the facts.
DESIGN_DEGRADATIONS: frozenset[str] = frozenset()
