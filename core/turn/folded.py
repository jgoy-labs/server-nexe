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

`DESIGN_DEGRADATIONS` is the other half of the same budget: the two limits C3
declared in writing and left for C4 to close.

* `postprocess` — `adapters_api.py`: in streaming the model's memory tags have
  already been forwarded to the client by the time the step runs.
* `reprompt` — `adapters_api.py`: `/v1` does not spend the second generation
  D3 asks for when an answer cleans down to nothing but tags.

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
#: with `==`: a sub-fase may not fold a step again.
FOLDED_BASELINE: dict[str, int] = {"api": 0, "ui": 0}

#: The step ids whose degradation is a DESIGN limit C3 declared and C4 closes,
#: as opposed to an environment guard firing. A healthy turn records neither.
DESIGN_DEGRADATIONS: frozenset[str] = frozenset({"postprocess", "reprompt"})
