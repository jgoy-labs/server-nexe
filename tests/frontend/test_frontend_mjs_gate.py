"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/frontend/test_frontend_mjs_gate.py
Description: Runs every self-checking Node script in tests/frontend/ that does
             not already have a gate of its own.

             Why this exists: ``session_persistence.mjs`` shipped on 01/08 with
             the #858 fix, drives the real ``app.js``, passes — and NOTHING ran
             it. ``xss_render_repro.mjs`` had a wrapper; the new one didn't, so
             it sat in the tree looking like coverage while the suite never
             touched it. A per-file wrapper reproduces that failure mode every
             time someone adds a script; discovery does not.

             Scripts are expected to exit non-zero on failure and print their
             own diagnosis. Skipped only when `node` is unavailable — never
             silently passed.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_NODE = shutil.which("node")
_FRONTEND_DIR = Path(__file__).parent

# Scripts driven by a dedicated gate with its own diagnosis — running them here
# too would only duplicate the work.
_HAS_OWN_GATE = {"xss_render_repro.mjs"}

_SCRIPTS = sorted(
    p for p in _FRONTEND_DIR.glob("*.mjs") if p.name not in _HAS_OWN_GATE
)


def test_there_is_something_to_run():
    """Discovery itself must not go quiet.

    If the glob ever returns nothing — renamed directory, moved scripts — this
    file would pass by running zero tests, which is the exact shape of the
    problem it was written to prevent.
    """
    assert _SCRIPTS, (
        "no .mjs scripts found in tests/frontend/ — either they moved (update "
        "this gate) or the discovery is broken and the frontend is now untested."
    )


@pytest.mark.skipif(_NODE is None, reason="node not available on this runner")
@pytest.mark.parametrize("script", _SCRIPTS, ids=lambda p: p.name)
def test_frontend_script_passes(script: Path):
    r = subprocess.run(
        [_NODE, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, (
        f"{script.name} failed:\n"
        f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
    )
