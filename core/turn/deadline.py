"""Per-turn engine deadline (#1041, ADR-007 §8, C2.5).

Every turn since C0 could run its `generate` step forever: a hung model, a
runaway prompt, a driver stuck mid-inference — nothing on either door ever
cut it short. `cancel_event` (the same one the UI's disconnect monitor
already sets when the client goes away) is now ALSO set by a timer armed in
`generate`, so a turn that runs past its deadline stops exactly the way a
client disconnect already does: the engine notices `cancel_event.is_set()`
between tokens and returns what it had.

Measured, not guessed (C2.0, `dev-tools/reports/` — see the diari entry for
2026-09-06): three MLX turns on THIS machine's 128 GB (two local models,
gemma-4-e4b-4bit and gpt-oss-20b-MLX-8bit) timed `generate` at 14.3s / 23.1s
/ 24.1s (n=3, the last one hitting the 2048-token ceiling). The default below
is ``min(300, ceil(3 × 24.1))`` rounded up to the nearest 30s = 90. This is a
LOWER bound measured on a machine far bigger than the shipped default — it
gets re-measured against an 8 GB target at the DMG live-test stage, not
extrapolated with an invented factor.
"""
from __future__ import annotations

import os

#: 0 disables the deadline entirely.
ENV_DEADLINE_S = "NEXE_ENGINE_DEADLINE_S"
DEFAULT_DEADLINE_S = 90.0


def resolve_deadline_s() -> float:
    """Seconds a turn's `generate` step may run before `cancel_event` is set
    for it. 0 (or an unparsable value) disables the deadline."""
    try:
        return float(os.environ.get(ENV_DEADLINE_S, DEFAULT_DEADLINE_S))
    except ValueError:
        return DEFAULT_DEADLINE_S
