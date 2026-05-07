"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_log_noise.py
Description: Tests for Bugs 3, 4, 5, 6, 14 in Block 3 — log noise in the GUI
             during the headless installer and at server runtime.
────────────────────────────────────
"""

import re
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# Bug 3 — HF_TOKEN warning silenced in the headless installer
# ═══════════════════════════════════════════════════════════════════════════

def test_bug3_hf_token_env_vars_set_after_install_headless_import():
    """Importing install_headless must set the env vars that silence HF."""
    # Force a re-import in a clean subprocess to avoid state contamination
    code = (
        "import os, sys; "
        f"sys.path.insert(0, {str(_ROOT)!r}); "
        "import installer.install_headless; "
        "print(os.environ.get('HF_HUB_DISABLE_TELEMETRY','')); "
        "print(os.environ.get('HF_HUB_DISABLE_PROGRESS_BARS','')); "
        "print(os.environ.get('HF_HUB_DISABLE_IMPLICIT_TOKEN',''))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = result.stdout.strip().splitlines()
    assert lines == ["1", "1", "1"], f"HF env vars not set: {result.stdout!r} stderr={result.stderr!r}"


def test_bug3_huggingface_logger_level_error():
    """The huggingface_hub logger must be set to ERROR to suppress WARN output.

    Uses subprocess to avoid contamination of the Python import cache:
    if install_headless has already been imported by a previous test, the
    module-level code (setLevel) is not re-executed in the current process.
    """
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(_ROOT)!r}); "
        "import installer.install_headless; "
        "import logging; "
        "print(logging.getLogger('huggingface_hub').level)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    import logging
    assert result.returncode == 0, f"Subprocess error: {result.stderr!r}"
    assert int(result.stdout.strip()) == logging.ERROR, (
        f"Incorrect logger level: {result.stdout.strip()!r} (expected {logging.ERROR})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Bug 4 — ANSI codes do not appear when stdout is not a TTY
# ═══════════════════════════════════════════════════════════════════════════

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def test_bug4_installer_display_constants_empty_when_not_tty():
    """When stdout is not a TTY (real headless case), color constants
    must be empty strings."""
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(_ROOT)!r}); "
        "from installer import installer_display as d; "
        "import re; "
        "ansi = re.compile(r'\\x1b\\[[0-9;]*m'); "
        "vals = (d.BLUE, d.GREEN, d.YELLOW, d.RED, d.CYAN, d.MAGENTA, d.BOLD, d.DIM, d.RESET); "
        "print(all(v == '' for v in vals))"
    )
    # Without pty: stdout is NOT a TTY
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip() == "True", f"Constants not empty: {result.stdout!r}"


def test_bug4_app_logo_no_ansi_when_not_tty():
    """The APP_LOGO must not contain any ANSI escape codes in headless mode."""
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(_ROOT)!r}); "
        "from installer import installer_display as d; "
        "import re; "
        "ansi = re.compile(r'\\x1b\\[[0-9;]*m'); "
        "print('CLEAN' if not ansi.search(d.APP_LOGO) else 'DIRTY')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip() == "CLEAN", f"APP_LOGO contains ANSI: {result.stdout!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Bug 5 — Qdrant didactic block only in interactive mode
# ═══════════════════════════════════════════════════════════════════════════
# Q5.5 reopened (2026-04-08): the test `test_bug5_qdrant_didactic_block_guarded_by_isatty`
# verified that installer/installer_setup_qdrant.py had didactic blocks guarded by
# `sys.stdout.isatty()`. That file has been REMOVED because Qdrant is now
# embedded (core/qdrant_pool.py) and no external binary needs to be downloaded.
# The test is obsolete by design — the bug it validated can no longer exist.


# ═══════════════════════════════════════════════════════════════════════════
# Bug 6 + Bug 14 — Warnings and tqdm silenced at server runtime
# ═══════════════════════════════════════════════════════════════════════════

def test_bug14_lifespan_sets_tqdm_disable():
    """Importing core.lifespan must set TQDM_DISABLE=1."""
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(_ROOT)!r}); "
        "import core.lifespan; "
        "import os; "
        "print(os.environ.get('TQDM_DISABLE',''))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.stdout.strip() == "1", f"TQDM_DISABLE not set: {result.stdout!r} stderr={result.stderr[:500]!r}"


def test_bug6_lifespan_filters_position_ids_warning():
    """Warning filters must ignore `.*position_ids.*` and
    `.*Some weights of.*`."""
    code = (
        "import sys, warnings; "
        f"sys.path.insert(0, {str(_ROOT)!r}); "
        "import core.lifespan; "
        # warnings.filters: tuples (action, message_re, category, module_re, lineno)
        "filters = [(f[1].pattern if f[1] is not None and hasattr(f[1],'pattern') else '') for f in warnings.filters]; "
        "has_position = any('position_ids' in p for p in filters); "
        "has_weights = any('Some weights' in p for p in filters); "
        "print(int(has_position and has_weights))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.stdout.strip() == "1", (
        f"Filters position_ids or Some weights not present: {result.stdout!r} stderr={result.stderr[:500]!r}"
    )
