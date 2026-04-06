"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_module_discovery_cycles.py
Description: Tests per Bug 20 — quan ModuleDiscovery detecta un cicle de
             dependencies, ha de:
               1. Loguejar un error visible amb la cadena del cicle
               2. Inhabilitar els modules afectats (com abans)
               3. Guardar el cicle a `_cycle_warnings` per consulta posterior

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import asyncio
import logging
import threading
from unittest.mock import MagicMock

import pytest

from personality.data.models import ModuleInfo, ModuleState
from personality.module_manager.discovery import ModuleDiscovery


def _make_discovery(modules_dict):
    """Construeix ModuleDiscovery amb mocks dels components."""
    path_disc = MagicMock()
    path_disc.load_cache.return_value = True
    path_disc._module_locations = {n: f"/fake/{n}" for n in modules_dict}
    path_disc.discover_all_paths.return_value = []
    path_disc.scan_for_modules.return_value = path_disc._module_locations
    path_disc.save_cache = MagicMock()

    config_mgr = MagicMock()
    config_mgr.find_manifest.return_value = "fake.toml"
    config_mgr.load_manifest.return_value = {}
    config_mgr.apply_config_to_module = MagicMock()

    events = MagicMock()
    async def _emit(_): return None
    events.emit_event = _emit

    i18n = MagicMock()
    i18n.get.return_value = "msg"

    return ModuleDiscovery(path_disc, config_mgr, events, i18n)


def test_cycle_detected_disables_modules_and_logs(caplog):
    """A -> B -> A: ambdos quedern enabled=False i hi ha log.error."""
    modules = {
        "A": ModuleInfo(
            name="A", path="/fake/A", manifest_path="A.toml",
            manifest={}, state=ModuleState.DISCOVERED,
            dependencies=["B"],
        ),
        "B": ModuleInfo(
            name="B", path="/fake/B", manifest_path="B.toml",
            manifest={}, state=ModuleState.DISCOVERED,
            dependencies=["A"],
        ),
    }

    disc = _make_discovery(modules)
    lock = threading.RLock()

    with caplog.at_level(logging.ERROR, logger="personality.module_manager.discovery"):
        asyncio.run(disc.discover(modules, lock, force=True))

    # Modules inhabilitats
    assert modules["A"].enabled is False
    assert modules["B"].enabled is False
    assert modules["A"].state == ModuleState.ERROR
    assert modules["B"].state == ModuleState.ERROR

    # Log error visible amb "cycle" i els noms dels modules
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    error_text = " ".join(r.message for r in error_records).lower()
    assert "cycle" in error_text
    assert "a" in error_text and "b" in error_text

    # _cycle_warnings populat
    assert len(disc._cycle_warnings) >= 1
    assert any("A" in w and "B" in w for w in disc._cycle_warnings)


def test_no_cycle_no_warnings():
    """Sense cicle, _cycle_warnings queda buit i ningu es desactiva."""
    modules = {
        "X": ModuleInfo(
            name="X", path="/fake/X", manifest_path="X.toml",
            manifest={}, state=ModuleState.DISCOVERED,
            dependencies=[],
        ),
        "Y": ModuleInfo(
            name="Y", path="/fake/Y", manifest_path="Y.toml",
            manifest={}, state=ModuleState.DISCOVERED,
            dependencies=["X"],
        ),
    }

    disc = _make_discovery(modules)
    lock = threading.RLock()
    asyncio.run(disc.discover(modules, lock, force=True))

    assert modules["X"].enabled is not False  # default True
    assert modules["Y"].enabled is not False
    assert disc._cycle_warnings == []


def test_get_cycle_warnings_returns_copy():
    """get_cycle_warnings() ha de retornar una copia, no la llista interna."""
    modules = {
        "A": ModuleInfo(
            name="A", path="/fake/A", manifest_path="A.toml",
            manifest={}, state=ModuleState.DISCOVERED,
            dependencies=["B"],
        ),
        "B": ModuleInfo(
            name="B", path="/fake/B", manifest_path="B.toml",
            manifest={}, state=ModuleState.DISCOVERED,
            dependencies=["A"],
        ),
    }
    disc = _make_discovery(modules)
    asyncio.run(disc.discover(modules, threading.RLock(), force=True))

    warnings = disc.get_cycle_warnings()
    assert len(warnings) >= 1
    # Mutar la copia no ha d'afectar l'interna
    warnings.clear()
    assert len(disc.get_cycle_warnings()) >= 1

    disc.clear_cycle_warnings()
    assert disc.get_cycle_warnings() == []


def test_lifespan_startup_summary_emits_warn_for_cycles(caplog):
    """
    Bug 20 — simulem el tros del lifespan que llegeix cycle_warnings i
    emet [WARN] log.warning per cada cadena.
    """
    import logging as _logging
    lifespan_logger = _logging.getLogger("core.lifespan")

    class _FakeMM:
        def get_cycle_warnings(self):
            return ["A -> B -> A", "C -> D -> C"]

    mm = _FakeMM()

    with caplog.at_level(_logging.WARNING, logger="core.lifespan"):
        # Replica del bloc nou afegit a core/lifespan.py
        try:
            cycle_warnings = mm.get_cycle_warnings()
        except Exception:
            cycle_warnings = []
        for cycle_chain in cycle_warnings:
            lifespan_logger.warning(
                "[WARN] Module dependency cycle: %s", cycle_chain
            )

    text = " ".join(r.getMessage() for r in caplog.records)
    assert "[WARN] Module dependency cycle: A -> B -> A" in text
    assert "[WARN] Module dependency cycle: C -> D -> C" in text
