"""
WS5-02 gate — runs the Node repro (xss_render_repro.mjs) that drives the real
vendored marked.min.js with app.js's renderer logic and asserts an attacker-controlled
markdown title cannot break out of an HTML attribute (XSS via poisoned RAG document).

The repro self-checks by requiring the pre-fix (vulnerable) renderer to break out on
the same inputs, so a green result cannot be test-theatre. Skipped only if `node` is
unavailable (e.g. a CI runner without Node); it never silently passes.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

_NODE = shutil.which("node")
_REPRO = Path(__file__).parent / "xss_render_repro.mjs"


@pytest.mark.skipif(_NODE is None, reason="node not available on this runner")
def test_markdown_attribute_xss_is_neutralized():
    assert _REPRO.exists(), f"repro script missing: {_REPRO}"
    r = subprocess.run(
        [_NODE, str(_REPRO)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, (
        "WS5-02 XSS repro failed (attribute breakout not neutralized):\n"
        f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
    )
