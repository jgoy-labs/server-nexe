"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_log_noise.py
Description: Tests pels Bugs 3, 4, 5, 6, 14 del Bloc 3 — soroll de log a la GUI
             durant l'instal·lador headless i a runtime del servidor.
────────────────────────────────────
"""

import os
import re
import subprocess
import sys
import warnings
from pathlib import Path
from unittest import mock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Bug 3 — HF_TOKEN warning silenciat al headless installer
# ═══════════════════════════════════════════════════════════════════════════

def test_bug3_hf_token_env_vars_set_after_install_headless_import():
    """Importar install_headless ha de fixar les env vars que silencien HF."""
    # Forcem un re-import en subprocess net per evitar contaminació de l'estat
    code = (
        "import os, sys; "
        "sys.path.insert(0, '/Users/jgoy/AI/nat/dev/server-nexe'); "
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
    assert lines == ["1", "1", "1"], f"HF env vars no fixades: {result.stdout!r} stderr={result.stderr!r}"


def test_bug3_huggingface_logger_level_error():
    """El logger huggingface_hub ha de quedar a ERROR perquè no escampi WARN."""
    import installer.install_headless  # noqa: F401
    import logging
    assert logging.getLogger("huggingface_hub").level == logging.ERROR


# ═══════════════════════════════════════════════════════════════════════════
# Bug 4 — Codis ANSI no apareixen quan stdout no és TTY
# ═══════════════════════════════════════════════════════════════════════════

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def test_bug4_installer_display_constants_empty_when_not_tty():
    """Quan stdout no és TTY (cas headless real), les constants de color
    han de ser cadenes buides."""
    code = (
        "import sys; "
        "sys.path.insert(0, '/Users/jgoy/AI/nat/dev/server-nexe'); "
        "from installer import installer_display as d; "
        "import re; "
        "ansi = re.compile(r'\\x1b\\[[0-9;]*m'); "
        "vals = (d.BLUE, d.GREEN, d.YELLOW, d.RED, d.CYAN, d.MAGENTA, d.BOLD, d.DIM, d.RESET); "
        "print(all(v == '' for v in vals))"
    )
    # Sense pty: stdout NO és TTY
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip() == "True", f"Constants no buides: {result.stdout!r}"


def test_bug4_app_logo_no_ansi_when_not_tty():
    """El logo APP_LOGO no ha de contenir cap escapament ANSI en headless."""
    code = (
        "import sys; "
        "sys.path.insert(0, '/Users/jgoy/AI/nat/dev/server-nexe'); "
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
    assert result.stdout.strip() == "CLEAN", f"APP_LOGO conté ANSI: {result.stdout!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Bug 5 — Bloc didàctic Qdrant només en mode interactiu
# ═══════════════════════════════════════════════════════════════════════════

def test_bug5_qdrant_didactic_block_guarded_by_isatty():
    """El codi font ha de tenir el bloc didàctic protegit per `sys.stdout.isatty()`."""
    src = Path("/Users/jgoy/AI/nat/dev/server-nexe/installer/installer_setup_qdrant.py").read_text()
    # Cal que les dues invocacions a `qdrant_download_info` i `qdrant_quarantine_info`
    # estiguin dins blocs `if sys.stdout.isatty():`
    assert src.count("if sys.stdout.isatty():") >= 2, (
        "Bug 5: el bloc didàctic ha d'estar emboltat amb `if sys.stdout.isatty():` "
        "(2 ocurrències esperades, una per download i una per quarantine)."
    )
    # I les dues claus de traducció han de continuar existint
    assert "qdrant_download_info" in src
    assert "qdrant_quarantine_info" in src


# ═══════════════════════════════════════════════════════════════════════════
# Bug 6 + Bug 14 — Warnings i tqdm silenciats al runtime del servidor
# ═══════════════════════════════════════════════════════════════════════════

def test_bug14_lifespan_sets_tqdm_disable():
    """Importar core.lifespan ha de fixar TQDM_DISABLE=1."""
    code = (
        "import sys; "
        "sys.path.insert(0, '/Users/jgoy/AI/nat/dev/server-nexe'); "
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
    assert result.stdout.strip() == "1", f"TQDM_DISABLE no fixat: {result.stdout!r} stderr={result.stderr[:500]!r}"


def test_bug6_lifespan_filters_position_ids_warning():
    """Els filtres de warnings han d'ignorar `.*position_ids.*` i
    `.*Some weights of.*`."""
    code = (
        "import sys, warnings; "
        "sys.path.insert(0, '/Users/jgoy/AI/nat/dev/server-nexe'); "
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
        f"Filters position_ids o Some weights no presents: {result.stdout!r} stderr={result.stderr[:500]!r}"
    )
