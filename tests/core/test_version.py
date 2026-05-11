# -*- coding: utf-8 -*-
"""Tests for core.version — single source of truth from pyproject.toml."""

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_version_matches_pyproject():
    """__version__ must match pyproject.toml."""
    from core.version import __version__

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with open(pyproject, "rb") as f:
        expected = tomllib.load(f)["project"]["version"]

    assert __version__ == expected


def test_version_is_valid_semver():
    """__version__ must have valid semver format (X.Y.Z or X.Y.Z-tag)."""
    from core.version import __version__

    assert re.match(r"^\d+\.\d+\.\d+(-[\w.]+)?$", __version__), (
        f"Version '{__version__}' is not a valid semver"
    )


def test_version_is_not_unknown():
    """__version__ no ha de ser el fallback."""
    from core.version import __version__

    assert __version__ != "0.0.0-unknown"
