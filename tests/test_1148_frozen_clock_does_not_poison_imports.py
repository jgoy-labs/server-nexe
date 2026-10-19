"""#1148 — a test that freezes the clock must not break the one that follows.

`test_routes_chat_sentinel.py` replaces `datetime.datetime` with a mock. When
that was the first thing to import `core.lifespan`, loguru bound itself to the
mock and the three `TestWebUiHandlerEndToEnd` tests of `test_B263.py` failed
with «Mock object has no attribute 'combine'» — but only in that order, never
in the full suite (where something imported it earlier). This runs the two
files in the order that used to fail, in a fresh interpreter, so what it proves
does not depend on what the rest of the suite imported before it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_order_that_used_to_fail_passes_in_a_fresh_interpreter():
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov",
         "tests/plugins/web_ui_module/test_routes_chat_sentinel.py",
         "tests/fixos/test_B263.py"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    tail = "\n".join(proc.stdout.splitlines()[-15:])
    assert proc.returncode == 0, tail
    assert " passed" in proc.stdout, tail
