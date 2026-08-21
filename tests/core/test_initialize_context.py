"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_initialize_context.py
Description: D-C — one initialize() context for plugins and memory.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.loader.protocol import (
    build_initialize_context,
    module_config_from_context,
    services_from_server_state,
)
from core.lifespan_modules import initialize_plugin_modules


class TestBuildInitializeContext:
    def test_keys_match_the_protocol(self):
        ctx = build_initialize_context(
            config={"a": 1},
            services={"i18n": "x"},
            modules={"m": 1},
            project_root="/repo",
        )
        assert set(ctx) == {"config", "services", "modules", "project_root"}
        assert ctx["config"] == {"a": 1}
        assert ctx["services"] == {"i18n": "x"}
        assert ctx["modules"] == {"m": 1}
        assert ctx["project_root"] == "/repo"

    def test_defaults_are_empty_dicts_not_none(self):
        ctx = build_initialize_context()
        assert ctx["config"] == {}
        assert ctx["services"] == {}
        assert ctx["modules"] == {}
        assert ctx["project_root"] is None


class TestModuleConfigFromContext:
    def test_module_section_is_the_slice(self):
        ctx = {"config": {"memory": {"flash_ttl_seconds": 3600}}}
        assert module_config_from_context(ctx, "memory") == {"flash_ttl_seconds": 3600}

    def test_flat_dict_is_not_a_module_section(self):
        """D-P: production code no longer sniffs test-shaped dicts."""
        ctx = {"config": {"flash_ttl_seconds": 3600}}
        assert module_config_from_context(ctx, "memory") == {}

    def test_toml_section_slice(self):
        ctx = {"config": {"memory": {"ram_max_entries": 50}, "plugins": {}}}
        assert module_config_from_context(ctx, "memory") == {"ram_max_entries": 50}

    def test_full_toml_without_module_section_is_empty(self):
        ctx = {"config": {"plugins": {"modules": {}}, "personality": {}}}
        assert module_config_from_context(ctx, "memory") == {}

    def test_none_and_empty(self):
        assert module_config_from_context(None, "memory") == {}
        assert module_config_from_context({}, "memory") == {}


class TestServicesFromServerState:
    def test_omits_missing_and_keeps_present(self):
        state = MagicMock()
        state.i18n = "i18n-obj"
        state.crypto_provider = None
        services = services_from_server_state(state)
        assert services["i18n"] == "i18n-obj"
        assert "crypto_provider" not in services
        from core.memory_access import get_memory_view
        assert services["memory"] is get_memory_view


class TestPluginInitializeGetsTheFullContext:
    @pytest.mark.asyncio
    async def test_plugin_receives_services_and_modules(self):
        captured = {}

        async def _init(context):
            captured.update(context)
            return True

        fake = MagicMock()
        fake.initialize = _init
        app = MagicMock()
        app.state.modules = {"fake_plugin": fake}
        server_state = MagicMock()
        server_state.config = {"core": {}}
        server_state.project_root = "/tmp"
        server_state.i18n = "i18n-obj"
        server_state.crypto_provider = None

        await initialize_plugin_modules(app, server_state)

        assert captured["config"] == {"core": {}}
        assert captured["project_root"] == "/tmp"
        assert captured["services"]["i18n"] == "i18n-obj"
        assert "crypto_provider" not in captured["services"]
        from core.memory_access import get_memory_view
        assert captured["services"]["memory"] is get_memory_view
        assert "fake_plugin" in captured["modules"]
        assert captured["modules"]["fake_plugin"] is fake


class TestMemoryModuleGetsTheSameContext:
    """D-C: the memory branch of the loader must deliver the same dict.

    Mutation proof: revert `_load_single_memory_module` to
    `initialize(config=config.get(name))` and this test goes RED. Without it the
    whole suite stays green with the fix undone — the plugin-side tests above do
    not exercise this path.
    """

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            '[meta]\nversion = "0.8"\n[personality]\n'
            '[personality.orchestrator]\nmodules_path = "plugins"\n'
        )
        with patch(
            "personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False
        ):
            from personality.module_manager.module_manager import ModuleManager

            return ModuleManager(config_path=config_file)

    def test_memory_module_receives_the_four_protocol_keys(self, mm, tmp_path):
        captured = {}

        async def _init(context):
            captured["context"] = context
            return True

        memory_path = tmp_path / "memory"
        (memory_path / "embeddings").mkdir(parents=True)
        (memory_path / "embeddings" / "manifest.py").write_text("MODULE_ID = 'embeddings'\n")
        mm.path_discovery.base_path = tmp_path

        manifest = MagicMock()
        manifest.MODULE_ID = "embeddings"
        instance = MagicMock()
        instance.initialize = _init
        module_py = MagicMock()
        module_py.EmbeddingsModule = MagicMock(get_instance=lambda: instance)

        siblings = {"already": object()}
        with patch("importlib.import_module", side_effect=[manifest, module_py]):
            result = asyncio.run(
                mm._load_single_memory_module(
                    "embeddings", memory_path, {"core": {}}, siblings
                )
            )

        assert result is not None, "the happy path must load the module"
        ctx = captured["context"]
        assert set(ctx) == {"config", "services", "modules", "project_root"}, (
            f"memory got a different contract than plugins: {sorted(ctx)}"
        )
        assert ctx["config"] == {"core": {}}, "the full config travels, not a pre-sliced section"
        assert ctx["services"]["i18n"] is mm.i18n, "i18n must reach memory modules too"
        assert ctx["modules"] is siblings, "already-loaded memory modules must be visible"
        assert ctx["project_root"] == tmp_path
