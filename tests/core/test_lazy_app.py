"""Tests for lazy `core.app:app` resolution.

Importing `core.app` must NOT instantiate the FastAPI factory at import time.
The `app` attribute is resolved on first access via PEP 562 `__getattr__`,
then cached on the module for O(1) subsequent accesses.
"""

import importlib
import sys

import pytest


@pytest.fixture
def fresh_core_app():
  """Reload core.app so each test sees the pre-lazy state.

  Without this, the previous test's access to `core.app.app` would leave the
  singleton cached and subsequent assertions about laziness would fail.
  """
  for mod_name in list(sys.modules):
    if mod_name == 'core.app' or mod_name.startswith('core.app.'):
      del sys.modules[mod_name]
  yield
  for mod_name in list(sys.modules):
    if mod_name == 'core.app' or mod_name.startswith('core.app.'):
      del sys.modules[mod_name]


def test_import_does_not_create_app(fresh_core_app):
  """`import core.app` alone must not have populated `app` in module dict."""
  import core.app

  assert 'app' not in core.app.__dict__, (
    "Import of core.app should not eagerly create the FastAPI app "
    "(BUG-NX-5). Access to core.app.app should be the trigger."
  )


def test_app_attribute_creates_lazy(fresh_core_app):
  """Accessing `core.app.app` for the first time builds the singleton."""
  import core.app
  from fastapi import FastAPI

  app = core.app.app

  assert isinstance(app, FastAPI)
  assert 'app' in core.app.__dict__, "Singleton must be cached after first access"


def test_app_attribute_is_singleton(fresh_core_app):
  """Subsequent accesses must return the exact same instance."""
  import core.app

  app1 = core.app.app
  app2 = core.app.app

  assert app1 is app2


def test_get_app_helper_returns_same_singleton(fresh_core_app):
  """`get_app()` is the public accessor and must share the singleton."""
  import core.app

  app_attr = core.app.app
  app_helper = core.app.get_app()

  assert app_attr is app_helper


def test_unknown_attribute_raises_attribute_error(fresh_core_app):
  """Module-level __getattr__ must still raise AttributeError for unknowns."""
  import core.app

  with pytest.raises(AttributeError, match="has no attribute 'nonexistent_attr'"):
    core.app.nonexistent_attr  # noqa: B018
