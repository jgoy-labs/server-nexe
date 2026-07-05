"""F2.6 — BUG-NC-25: MemoryAPI must not freeze env at import time.

Verifies that `NEXE_QDRANT_URL` / `NEXE_QDRANT_HOST` / `NEXE_QDRANT_PORT` set
AFTER `memory.memory.api` is imported are honoured when a new MemoryAPI
instance is created. Before the fix these env vars were latched at import
time via class-level attribute evaluation.
"""

import os
from unittest.mock import patch

from memory.memory.api import MemoryAPI


def test_default_qdrant_url_resolves_at_instance_creation():
  """Setting NEXE_QDRANT_URL after import must be reflected in new instances."""
  with patch.dict(os.environ, {"NEXE_QDRANT_URL": "http://test-host:9999"}, clear=False):
    api = MemoryAPI()
    assert api.qdrant_url == "http://test-host:9999", (
      "Class-level DEFAULT_QDRANT_URL froze the env at import time; "
      "new instances should re-read os.environ."
    )


def test_default_qdrant_host_port_compose_at_instance_creation():
  """NEXE_QDRANT_HOST + NEXE_QDRANT_PORT compose the URL fallback at runtime."""
  env = {"NEXE_QDRANT_HOST": "memory.lan", "NEXE_QDRANT_PORT": "16333"}
  # Ensure NEXE_QDRANT_URL is not set or this test bypasses host/port logic.
  with patch.dict(os.environ, env, clear=False):
    os.environ.pop("NEXE_QDRANT_URL", None)
    api = MemoryAPI()
    assert api.qdrant_url == "http://memory.lan:16333"


def test_resolve_default_qdrant_url_classmethod_works_without_instance():
  """Classmethod accessor must be invocable without instantiating the class."""
  with patch.dict(os.environ, {"NEXE_QDRANT_URL": "http://cls:1234"}, clear=False):
    assert MemoryAPI._resolve_default_qdrant_url() == "http://cls:1234"


def test_explicit_qdrant_url_overrides_default():
  """Explicit kwarg keeps priority over env-resolved default."""
  with patch.dict(os.environ, {"NEXE_QDRANT_URL": "http://default:1"}, clear=False):
    api = MemoryAPI(qdrant_url="http://explicit:2")
    assert api.qdrant_url == "http://explicit:2"
