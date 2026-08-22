"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/frontend/test_status_dot_cascade.py
Description: The status dot must actually turn amber when a subsystem is down.

             Why this exists: the rule shipped on 22/08 (`.status-dot.degraded`)
             was written 90 lines ABOVE `.status-dot.active`, with the same
             specificity. The cascade therefore handed a connected-but-impaired
             dot straight back to green — green fill, green halo, pulse — so the
             "one glance at the footer" the feature was built for said everything
             was fine. The label changed; the dot lied.

             Nothing in the suite could see it: the class was toggled correctly,
             the JS was correct, the CSS was valid. Only rendering it shows it.

             Two layers on purpose:
               1. A render gate that asks a real browser for the computed
                  colour — the only honest answer about a cascade. Skipped when
                  no Chromium-family browser is installed.
               2. A static gate that reads style.css and holds the mechanism
                  (declared after `.active`, and resets the halo). It asserts
                  the shape rather than the behaviour, which is normally the
                  weaker kind of test — it is here because layer 1 is the one
                  that can be skipped, and this bug must not survive on a
                  runner without a browser.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_UI = Path(__file__).resolve().parents[2] / "plugins" / "web_ui_module" / "ui"
_CSS = _UI / "style.css"

_AMBER = "rgb(255, 180, 0)"
_SUCCESS_GREEN = "rgb(34, 197, 94)"

_BROWSER_CANDIDATES = (
    os.environ.get("NEXE_TEST_BROWSER", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)


def _find_browser():
    for candidate in _BROWSER_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


_BROWSER = _find_browser()

# Two dots side by side: one merely connected, one connected AND impaired. The
# first is the control — if the stylesheet never loads, it stops being green and
# the whole harness is exposed instead of passing on transparent pixels.
_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="file://{css}">
</head><body>
<span class="status-indicator">
  <span class="status-dot active" id="connected"></span>
  <span class="status-dot active degraded" id="impaired"></span>
  <span>x</span>
</span>
<pre id="out"></pre>
<script>
const read = (id) => {{
  const cs = getComputedStyle(document.getElementById(id));
  return 'NEXEDOT|' + id + '|background|' + cs.backgroundColor + '\\n'
       + 'NEXEDOT|' + id + '|shadow|' + cs.boxShadow;
}};
document.getElementById('out').textContent =
  '\\n' + read('connected') + '\\n' + read('impaired') + '\\n';
</script></body></html>
"""

_LINE = re.compile(r"NEXEDOT\|(\w+)\|(\w+)\|([^\n<]*)")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Computed styles from a real browser: {(id, prop): value}."""
    page = tmp_path_factory.mktemp("cascade") / "status_dot.html"
    page.write_text(_PAGE.format(css=_CSS))
    try:
        result = subprocess.run(
            [
                _BROWSER, "--headless", "--disable-gpu", "--no-sandbox",
                "--virtual-time-budget=3000", "--dump-dom", f"file://{page}",
            ],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        pytest.skip(f"browser could not render on this machine: {exc!r}")

    styles = {(m[0], m[1]): m[2].strip() for m in _LINE.findall(result.stdout)}
    assert styles, (
        "the browser returned no computed styles — the harness is broken, not "
        "the CSS. Fix the harness; do not delete the check.\n"
        f"--- stdout ---\n{result.stdout[:1500]}\n--- stderr ---\n{result.stderr[:800]}"
    )
    return styles


@pytest.mark.skipif(_BROWSER is None, reason="no Chromium-family browser on this runner")
class TestRenderedStatusDot:
    def test_a_connected_but_impaired_dot_is_amber(self, rendered):
        """The whole point of the indicator: at a glance, amber means impaired."""
        background = rendered[("impaired", "background")]
        assert background == _AMBER, (
            f"an impaired dot rendered {background}, expected amber {_AMBER}. "
            "A rule that loses the cascade to .status-dot.active tells the user "
            "everything is fine while a subsystem is down (the 22/08 bug)."
        )

    def test_the_green_halo_does_not_survive(self, rendered):
        """.active paints a green ring; leaving it makes an amber dot look green."""
        shadow = rendered[("impaired", "shadow")]
        assert "34, 197, 94" not in shadow, (
            f"the impaired dot keeps the green halo from .active: {shadow}"
        )

    def test_calibration_a_healthy_dot_is_still_green(self, rendered):
        """If the stylesheet failed to load, everything above would pass on a
        transparent dot. This is the control that says the harness works."""
        background = rendered[("connected", "background")]
        assert background == _SUCCESS_GREEN, (
            f"a healthy connected dot rendered {background}, expected {_SUCCESS_GREEN} — "
            "the stylesheet is probably not being applied at all."
        )


class TestCascadeMechanism:
    """Layer 2: holds the mechanism where no browser is available."""

    @staticmethod
    def _rule_start(selector: str, css: str) -> int:
        # Selectors are matched at the start of a line, as they are written.
        match = re.search(rf"^{re.escape(selector)}[,\s{{]", css, re.MULTILINE)
        assert match, f"selector {selector!r} not found in style.css"
        return match.start()

    def test_degraded_is_declared_after_active(self):
        css = _CSS.read_text()
        active = self._rule_start(".status-dot.active", css)
        degraded = self._rule_start(".status-dot.degraded", css)
        assert degraded > active, (
            ".status-dot.degraded is declared BEFORE .status-dot.active. They have "
            "the same specificity, so the later one wins and the impaired dot goes "
            "back to green. Move it below .active (see the render gate above)."
        )

    def test_degraded_resets_the_halo(self):
        css = _CSS.read_text()
        block = re.search(
            r"^\.status-dot\.degraded[^{]*\{([^}]*)\}", css, re.MULTILINE
        )
        assert block, ".status-dot.degraded rule not found"
        body = block.group(1)
        assert "box-shadow" in body, (
            ".status-dot.degraded does not touch box-shadow, so the green halo "
            "from .active survives and the dot reads as healthy anyway."
        )
        assert "34 197 94" not in body and "34, 197, 94" not in body, (
            "the degraded halo is still the success green"
        )
