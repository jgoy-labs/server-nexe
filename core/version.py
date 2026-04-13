# -*- coding: utf-8 -*-
"""Single source of truth for server-nexe version. Reads from pyproject.toml."""

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python < 3.11 fallback

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

try:
    with open(_PYPROJECT, "rb") as f:
        __version__: str = tomllib.load(f)["project"]["version"]
except Exception:
    __version__ = "0.0.0-unknown"
