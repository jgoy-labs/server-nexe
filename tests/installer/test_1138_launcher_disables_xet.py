"""#1138 — `./nexe` turns hf_xet off before Python starts.

huggingface_hub reads HF_HUB_DISABLE_XET at import, and with hf_xet active
large model downloads stall (huggingface_hub#3266). The nexe-app launcher set
it (lib.rs); `./nexe` did not, and every start of DEV warned «hf_xet active at
startup» (log 02/10 and 03/10).

Not a grep of the script: this RUNS the real launcher, copied next to a fake
`venv/bin/python3` that prints the variable it was handed.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_LAUNCHER = Path(__file__).resolve().parents[2] / "nexe"


@pytest.fixture
def launcher(tmp_path):
    shutil.copy2(_LAUNCHER, tmp_path / "nexe")
    fake = tmp_path / "venv" / "bin" / "python3"
    fake.parent.mkdir(parents=True)
    fake.write_text('#!/bin/sh\necho "XET=${HF_HUB_DISABLE_XET-unset} ARGS=$*"\n')
    fake.chmod(0o755)
    return tmp_path / "nexe"


def _run(launcher, **env):
    base = {k: v for k, v in os.environ.items() if k != "HF_HUB_DISABLE_XET"}
    out = subprocess.run(["bash", str(launcher), "go"], env={**base, **env},
                         capture_output=True, text=True, timeout=30, check=True)
    return out.stdout.strip()


def test_the_launcher_hands_python_xet_off(launcher):
    assert _run(launcher) == "XET=1 ARGS=-m core.cli go"


def test_a_value_from_outside_wins(launcher):
    assert _run(launcher, HF_HUB_DISABLE_XET="0") == "XET=0 ARGS=-m core.cli go"


def test_an_empty_value_from_outside_wins_too(launcher):
    # Same as the tray's os.environ.get(..., "1"): set-but-empty is a choice.
    assert _run(launcher, HF_HUB_DISABLE_XET="") == "XET= ARGS=-m core.cli go"
