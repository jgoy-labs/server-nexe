"""The memory helper is core furniture: it exists without the UI plugin.

ADR-007 C3.0 — the brain moved out of plugins/web_ui_module. These tests hold
that line: a bare server_state, zero modules loaded, and memory still attaches.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.lifespan_sessions import _expose_memory_helper
from core.memory_facts import MemoryHelper, MemoryPort, attach_memory_helper, helper_for

ROOT = Path(__file__).resolve().parents[3]


class _BareState:
    """A server_state with nothing on it — no modules, no plugins, no config."""


def test_helper_builds_with_zero_plugins_loaded():
    state = _BareState()
    assert not hasattr(state, "modules")

    helper = attach_memory_helper(state)

    assert isinstance(helper, MemoryHelper)
    assert state.memory_helper is helper


def test_attach_is_idempotent():
    state = _BareState()
    assert attach_memory_helper(state) is attach_memory_helper(state)


def test_helper_for_returns_the_attached_one():
    state = _BareState()
    helper = attach_memory_helper(state)
    assert helper_for(state) is helper


def test_helper_for_without_attach_says_so():
    """No silent fallback: a helper nobody attached would read nobody's memory."""
    with pytest.raises(RuntimeError, match="attach_memory_helper"):
        helper_for(_BareState())


def test_helper_satisfies_the_port():
    assert isinstance(attach_memory_helper(_BareState()), MemoryPort)


def test_expose_puts_the_same_instance_on_app_state():
    """One brain: what the doors read IS what the lifespan attached."""
    state = _BareState()
    helper = attach_memory_helper(state)
    app = SimpleNamespace(state=SimpleNamespace())

    _expose_memory_helper(app, state)

    assert app.state.memory_helper is helper
    assert helper_for(app.state) is helper


def test_expose_without_attach_warns_and_leaves_app_state_alone(caplog):
    app = SimpleNamespace(state=SimpleNamespace())
    with caplog.at_level(logging.WARNING):
        _expose_memory_helper(app, SimpleNamespace(memory_helper=None))
    assert not hasattr(app.state, "memory_helper")
    assert any("not attached" in r.getMessage() for r in caplog.records)


def test_lifespan_attaches_and_exposes_the_helper():
    """Placement guard: without this the mutation "drop the attach from the
    lifespan" passes every behavioural test — nothing else drives the real
    startup path, exactly how #1046 stayed invisible until a live run."""
    lines = (ROOT / "core" / "lifespan.py").read_text(encoding="utf-8").splitlines()

    def line_of(call):
        """The line that CALLS it — a commented-out call is not a call."""
        hits = [i for i, ln in enumerate(lines)
                if ln.strip().startswith(call) and not ln.strip().startswith("#")]
        assert hits, f"the lifespan never calls {call}"
        return hits[0]

    attach = line_of("await _startup_memory_helper(server_state)")
    expose = line_of("_expose_memory_helper(app, server_state)")
    modules = line_of("await _startup_module_discovery(app, server_state, _translate)")
    assert attach < expose < modules


def test_helper_imports_nothing_from_plugins():
    """C3.0's whole point: core/memory_facts/ imports only from core/."""
    import pathlib

    import core.memory_facts as pkg

    pkg_dir = pathlib.Path(pkg.__file__).parent
    for name in ("helper.py", "intent_patterns.py", "port.py", "attach.py"):
        src = (pkg_dir / name).read_text()
        assert "import plugins" not in src, f"{name} imports plugins"
        assert "from plugins" not in src, f"{name} imports from plugins"
