"""
Test fix B049: seccions mortes a personality/server.toml.

[core.timeouts], [storage.logging] i [storage.paths] no les llegeix ningú en
runtime (els timeouts venen d'env vars a core/lifespan*.py; logs_dir/audit_dir
venen de core/paths/helpers.py i NEXE_LOGS_DIR; el ConfigValidator que les
referencia NO s'executa al boot — el boot usa ModuleManager() directe). Són
config morta i s'esborren.

En canvi [plugins.models] (preferred_engine, llegit a chat_engines/routing.py i
endpoints/root.py) i [personality.orchestrator] (modules_path, llegit al boot a
module_manager/path_discovery.py) SÍ que són vives i han de quedar-se.
"""
import tomllib
from pathlib import Path

# personality/server.toml relative to this file: tests/fixos/ -> repo root.
_SERVER_TOML = Path(__file__).resolve().parents[2] / "personality" / "server.toml"


def _load_cfg() -> dict:
    with open(_SERVER_TOML, "rb") as f:
        return tomllib.load(f)


def test_dead_sections_removed():
    """Les 3 seccions mortes ja no han d'existir al server.toml real."""
    cfg = _load_cfg()

    assert "timeouts" not in cfg.get("core", {}), (
        "[core.timeouts] és config morta (timeouts via env vars) i s'ha d'haver esborrat"
    )
    storage = cfg.get("storage", {})
    assert "logging" not in storage, (
        "[storage.logging] és config morta (cap lector runtime) i s'ha d'haver esborrat"
    )
    assert "paths" not in storage, (
        "[storage.paths] és config morta (paths via core/paths/helpers.py + env) "
        "i s'ha d'haver esborrat"
    )


def test_live_sections_kept():
    """Les seccions vives no s'han de tocar."""
    cfg = _load_cfg()

    # [plugins.models].preferred_engine -> llegit a runtime (routing.py / root.py)
    assert "models" in cfg.get("plugins", {}), "[plugins.models] és viva, no s'ha de tocar"
    assert "preferred_engine" in cfg["plugins"]["models"], (
        "plugins.models.preferred_engine és viu (routing.py) i ha de continuar-hi"
    )

    # [personality.orchestrator].modules_path -> llegit al boot (path_discovery.py)
    assert "orchestrator" in cfg.get("personality", {}), (
        "[personality.orchestrator] és viva, no s'ha de tocar"
    )
    assert "modules_path" in cfg["personality"]["orchestrator"], (
        "personality.orchestrator.modules_path és viu (path_discovery.py) i ha de continuar-hi"
    )
