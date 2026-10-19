"""A frozen ``datetime.datetime`` that cannot poison later imports.

The prompt builder reads the clock through ``datetime.datetime``, so the
tests that fix the date replace that class with a mock. A module imported
for the first time WHILE the mock is in place binds to it: loguru calls
``datetime.combine`` when it is imported, and a mock has no such method, so
every later import of ``core.lifespan`` failed in whichever test happened to
come next (#1148). The modules the builder imports lazily are therefore
loaded before the class is replaced.
"""
from __future__ import annotations

import datetime as _datetime_mod
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


@contextmanager
def frozen_datetime(fixed):
    """Make ``datetime.datetime.now().astimezone()`` return `fixed`."""
    import core.lifespan  # noqa: F401  (imported here, never under the mock)

    mock_cls = MagicMock()
    mock_cls.now.return_value.astimezone.return_value = fixed
    with patch.object(_datetime_mod, "datetime", mock_cls):
        yield mock_cls
