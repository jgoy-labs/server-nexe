"""
TDD xfail — Onada 4.6c: B5 (get_health hasattr guard) + B6 (stop_module state ERROR)
"""
import asyncio
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from personality.data.models import ModuleInfo, ModuleState


# ────────────────────────────────────────────────────────────────────────────
# Helpers compartits
# ────────────────────────────────────────────────────────────────────────────

def _make_module_info(name, state=ModuleState.DISCOVERED, enabled=True):
    return ModuleInfo(
        name=name,
        path=Path(f"/fake/{name}"),
        manifest_path=Path(f"/fake/{name}/manifest.toml"),
        state=state,
        enabled=enabled,
    )


@pytest.fixture
def lm():
    from personality.module_manager.module_lifecycle import ModuleLifecycleManager
    modules = {}
    loader = MagicMock()
    loader.load_module = AsyncMock(return_value=MagicMock())
    loader.unload_module = AsyncMock()
    registry = MagicMock()
    events = MagicMock()
    events.emit_event = AsyncMock()
    metrics = MagicMock()
    return ModuleLifecycleManager(modules, loader, registry, events, metrics)


@pytest.fixture
def mm(tmp_path):
    config_file = tmp_path / "personality" / "server.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        '[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n'
    )
    with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
        from personality.module_manager.module_manager import ModuleManager
        return ModuleManager(config_path=config_file)


# ────────────────────────────────────────────────────────────────────────────
# B5 — get_health sense hasattr guard
# ────────────────────────────────────────────────────────────────────────────

class TestB5GetHealthHashattrGuard:

    def test_b5_module_without_get_health_is_registered(self, mm, tmp_path):
        """xfail: mòdul sense get_health() hauria de registrar-se amb default health.

        Bug actual: AttributeError és capturat per except Exception → continue →
        mòdul no apareix a loaded_modules. Post-fix amb hasattr guard, el mòdul
        es registra amb {"status": "ok", "note": "module without get_health()"}.
        """
        mem_path = tmp_path / "memory" / "embeddings"
        mem_path.mkdir(parents=True)
        (mem_path / "manifest.py").touch()

        class FakeEmbeddingsModule:
            """Mòdul sense get_health — simula B5."""

            @classmethod
            def get_instance(cls):
                return cls()

            async def initialize(self, config=None):
                return True

            # get_health() deliberadament absent

        fake_manifest = MagicMock()
        fake_manifest.MODULE_ID = "test_embeddings_id"

        fake_module_py = MagicMock()
        fake_module_py.EmbeddingsModule = FakeEmbeddingsModule

        def _fake_import(name):
            if name == "memory.embeddings.manifest":
                return fake_manifest
            if name == "memory.embeddings.module":
                return fake_module_py
            raise ImportError(name)

        mm.path_discovery.base_path = tmp_path
        with patch("importlib.import_module", side_effect=_fake_import):
            result = asyncio.run(mm.load_memory_modules())

        # Post-fix: mòdul HA d'estar registrat; ara FALLA (és descartat)
        assert "test_embeddings_id" in result

    def test_b5_antireg_module_with_get_health_is_registered(self, mm, tmp_path):
        """Anti-reg: mòdul AMB get_health() segueix registrant-se correctament."""
        mem_path = tmp_path / "memory" / "embeddings"
        mem_path.mkdir(parents=True)
        (mem_path / "manifest.py").touch()

        class FakeEmbeddingsModuleWithHealth:
            @classmethod
            def get_instance(cls):
                return cls()

            async def initialize(self, config=None):
                return True

            def get_health(self):
                return {"status": "ok"}

        fake_manifest = MagicMock()
        fake_manifest.MODULE_ID = "test_embeddings_with_health"

        fake_module_py = MagicMock()
        fake_module_py.EmbeddingsModule = FakeEmbeddingsModuleWithHealth

        def _fake_import(name):
            if name == "memory.embeddings.manifest":
                return fake_manifest
            if name == "memory.embeddings.module":
                return fake_module_py
            raise ImportError(name)

        mm.path_discovery.base_path = tmp_path
        with patch("importlib.import_module", side_effect=_fake_import):
            result = asyncio.run(mm.load_memory_modules())

        assert "test_embeddings_with_health" in result


# ────────────────────────────────────────────────────────────────────────────
# B6 — stop_module STOPPING leak (state no passa a ERROR)
# ────────────────────────────────────────────────────────────────────────────

class TestB6StopModuleStateErrorLeak:

    def test_b6_stop_module_error_sets_state_error(self, lm):
        """xfail: state hauria de ser ERROR quan stop() llança excepció.

        Bug actual (línia ~308-314 module_lifecycle.py): el bloc except captura
        l'error, fa return False però NO actualitza module_info.state. El mòdul
        queda en state=STOPPING per sempre. Post-fix: state = ModuleState.ERROR.
        """
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock()
        mod.instance.stop = MagicMock(side_effect=RuntimeError("shutdown error"))
        lm.modules["test"] = mod

        result = asyncio.run(lm.stop_module("test"))

        assert result is False
        # Post-fix: state HA de ser ERROR; ara FALLA (és STOPPING)
        assert mod.state == ModuleState.ERROR

    def test_b6_antireg_stop_module_success_sets_state_stopped(self, lm):
        """Anti-reg: stop_module sense error manté state=STOPPED."""
        mod = _make_module_info("test", state=ModuleState.RUNNING)
        mod.instance = MagicMock()
        mod.instance.stop = MagicMock(return_value=None)
        lm.modules["test"] = mod
        lm.loader.unload_module = AsyncMock()

        result = asyncio.run(lm.stop_module("test"))

        assert result is True
        assert mod.state == ModuleState.STOPPED
