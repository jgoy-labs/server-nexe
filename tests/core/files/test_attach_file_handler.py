"""The uploaded-document handler is core furniture: it exists without the UI
plugin.

C4.3-b — the instance moved out of plugins/web_ui_module/module.py, same
pattern ADR-007 C3.0 already set for MemoryHelper. These tests hold that
line: a bare server_state, zero modules loaded, and FileHandler still
attaches. Calcat de tests/core/memory_facts/test_attach.py.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.files import FileHandler, attach_file_handler
from core.lifespan_sessions import _expose_file_handler

ROOT = Path(__file__).resolve().parents[3]


class _BareState:
    """A server_state with nothing on it — no modules, no plugins, no config."""


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))


def test_handler_builds_with_zero_plugins_loaded():
    state = _BareState()
    assert not hasattr(state, "modules")

    handler = attach_file_handler(state)

    assert isinstance(handler, FileHandler)
    assert state.file_handler is handler


def test_attach_is_idempotent():
    state = _BareState()
    assert attach_file_handler(state) is attach_file_handler(state)


def test_upload_dir_resolves_via_get_data_dir(tmp_path):
    state = _BareState()
    handler = attach_file_handler(state)
    assert handler.upload_dir == tmp_path / "uploads"


def test_expose_puts_the_same_instance_on_app_state():
    """One registry, one brain: what /v1/attachments reads IS what the
    lifespan attached."""
    state = _BareState()
    handler = attach_file_handler(state)
    app = SimpleNamespace(state=SimpleNamespace())

    _expose_file_handler(app, state)

    assert app.state.file_handler is handler


def test_expose_without_attach_warns_and_leaves_app_state_alone(caplog):
    app = SimpleNamespace(state=SimpleNamespace())
    with caplog.at_level(logging.WARNING):
        _expose_file_handler(app, SimpleNamespace(file_handler=None))
    assert not hasattr(app.state, "file_handler")
    assert any("not attached" in r.getMessage() for r in caplog.records)


def test_lifespan_attaches_and_exposes_the_handler():
    """Placement guard: without this the mutation "drop the attach from the
    lifespan" passes every behavioural test — nothing else drives the real
    startup path."""
    lines = (ROOT / "core" / "lifespan.py").read_text(encoding="utf-8").splitlines()

    def line_of(call):
        """The line that CALLS it — a commented-out call is not a call."""
        hits = [i for i, ln in enumerate(lines)
                if ln.strip().startswith(call) and not ln.strip().startswith("#")]
        assert hits, f"the lifespan never calls {call}"
        return hits[0]

    attach = line_of("await _startup_file_handler(server_state)")
    expose = line_of("_expose_file_handler(app, server_state)")
    modules = line_of("await _startup_module_discovery(app, server_state, _translate)")
    assert attach < expose < modules


def test_files_package_imports_nothing_from_plugins():
    """core/files/ imports only from core/, same guarantee C3.0 set for memory."""
    import pathlib

    import core.files as pkg

    pkg_dir = pathlib.Path(pkg.__file__).parent
    for name in ("attach.py", "handler.py"):
        src = (pkg_dir / name).read_text()
        assert "import plugins" not in src, f"{name} imports plugins"
        assert "from plugins" not in src, f"{name} imports from plugins"
