"""Pytest entrypoint to load fixtures from dev-tools."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_dev_conftest = Path(__file__).parent / "dev-tools" / "conftest.py"
_spec = importlib.util.spec_from_file_location("dev_tools_conftest", _dev_conftest)
_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)

for _name, _value in _module.__dict__.items():
    if _name.startswith("_"):
        continue
    globals()[_name] = _value
