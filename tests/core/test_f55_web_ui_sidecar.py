"""F5.5 — Tests TDD per a web_ui_module enabled in sidecar (JSON only).

Substitueix `test_f25_stubs_sidecar.py` (eliminat). La decisió F2.5 era massa
agressiva: desactivava web_ui_module sencer en sidecar, però la UI Tauri
necessita els endpoints JSON (/ui/info, /ui/backends, /ui/sessions, etc.).

F5.5 corregeix:
  1. manifest `disabled_in_sidecar=false` — el plugin viu en sidecar mode
  2. `routes.py` salta condicionalment `register_static_routes()` (HTML/CSS/JS)
     quan `get_sidecar_config().is_sidecar=True` — la UI HTML la serveix Tauri
  3. JSON endpoints (/ui/info, /ui/backends, ...) sempre registrats

Run: pytest tests/core/test_f55_web_ui_sidecar.py --no-cov -q -p no:randomly
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────
# Fixtures — entorn aïllat (patró extret de test_factory_fail_fast_sidecar)
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_sidecar_env(monkeypatch):
    """Neteja NEXE_* + reseteja singleton SidecarConfig."""
    for var in [
        "NEXE_SIDECAR",
        "NEXE_PRIMARY_API_KEY",
        "NEXE_PORT",
        "NEXE_SERVER_PORT",
        "NEXE_SIDECAR_DIR",
        "NEXE_AUTH_TOKEN",
        "NEXE_ENV",
    ]:
        monkeypatch.delenv(var, raising=False)
    from core.sidecar_config import reset_sidecar_config
    reset_sidecar_config()
    yield
    reset_sidecar_config()


@pytest.fixture
def sidecar_env(monkeypatch, clean_sidecar_env, tmp_path):
    """Activa NEXE_SIDECAR=1 i mínim env vars per a SidecarConfig.from_env()."""
    monkeypatch.setenv("NEXE_SIDECAR", "1")
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-key-f55-web-ui")
    monkeypatch.setenv("NEXE_PORT", "9119")
    monkeypatch.setenv("NEXE_SIDECAR_DIR", str(tmp_path))
    monkeypatch.setenv("NEXE_ENV", "production")
    yield


# ─────────────────────────────────────────────────────────────────────
# Manifest contract — F5.5
# ─────────────────────────────────────────────────────────────────────


def test_manifest_disabled_in_sidecar_is_false():
    """F5.5 — manifest ha de tenir `disabled_in_sidecar=false`.

    Contrari a F2.5 (que era true). El plugin viu en sidecar mode i exposa
    els JSON endpoints; només les rutes HTML/static es salten al register.
    """
    import tomllib

    manifest_path = Path(__file__).parent.parent.parent / "plugins/web_ui_module/manifest.toml"
    with manifest_path.open("rb") as f:
        data = tomllib.load(f)
    assert data["module"]["disabled_in_sidecar"] is False, (
        "F5.5: web_ui_module ha d'estar enabled in sidecar (només se salten "
        "les rutes HTML/static a routes.py)"
    )


# ─────────────────────────────────────────────────────────────────────
# initialize() — F5.5: retorna True en sidecar (perquè manifest disabled=false)
# ─────────────────────────────────────────────────────────────────────


def test_web_ui_module_is_disabled_in_sidecar_returns_false(sidecar_env):
    """F5.5 — `_is_disabled_in_sidecar()` retorna False quan manifest=false.

    Anti-regressió de la decisió F2.5 — el helper continua existint per si
    en el futur volem tornar a desactivar el plugin en sidecar mode.
    """
    from plugins.web_ui_module.module import WebUIModule

    mod = WebUIModule()
    assert mod._is_disabled_in_sidecar() is False


# ─────────────────────────────────────────────────────────────────────
# Router composition — F5.5: static routes skipped in sidecar
# ─────────────────────────────────────────────────────────────────────


def _collect_router_paths(router) -> list[str]:
    """Return list of route paths registered on the router (with /ui prefix)."""
    return [r.path for r in router.routes if hasattr(r, "path")]


def test_router_excludes_html_routes_in_sidecar(sidecar_env, monkeypatch):
    """F5.5 — en sidecar mode, `create_router()` NO ha de registrar `/ui/` (HTML)
    ni `/ui/static/{path}`. Sí ha de registrar els JSON endpoints.
    """
    # Bypass del `disabled_in_sidecar` check (que retornaria False ja per
    # manifest, però la inicialització necessita context complet — saltem-la).
    from plugins.web_ui_module.module import WebUIModule
    from plugins.web_ui_module.api.routes import create_router

    mod = WebUIModule()
    # Crida directa a create_router (no calen initialize completes — el
    # _SessionManagerProxy es resol on-demand).
    router = create_router(mod)
    paths = _collect_router_paths(router)
    # HTML/static routes no han de ser registrades en sidecar mode.
    assert "/ui/" not in paths, (
        f"F5.5: ruta HTML /ui/ no hauria de registrar-se en sidecar. paths={paths}"
    )
    assert not any(p.startswith("/ui/static") for p in paths), (
        f"F5.5: rutes /ui/static/* no haurien de registrar-se en sidecar. paths={paths}"
    )
    # JSON endpoints clau SÍ han d'estar (la UI Tauri els consumeix).
    assert "/ui/info" in paths, f"F5.5: /ui/info absent en sidecar. paths={paths}"
    assert "/ui/backends" in paths, f"F5.5: /ui/backends absent en sidecar. paths={paths}"


def test_router_includes_html_routes_in_standalone(clean_sidecar_env, monkeypatch):
    """F5.5 — en mode standalone (no sidecar), HTML/static SÍ es registren.

    Garantia que el split és condicional, no destructiu — el comportament
    històric (servir la UI completa) es preserva en standalone.
    """
    from plugins.web_ui_module.module import WebUIModule
    from plugins.web_ui_module.api.routes import create_router

    mod = WebUIModule()
    router = create_router(mod)
    paths = _collect_router_paths(router)
    # En standalone mode HTML/static SÍ es registren (`/` amb prefix `/ui` = `/ui/`).
    assert "/ui/" in paths, (
        f"F5.5: ruta HTML /ui/ (root index.html) ha de registrar-se en standalone. paths={paths}"
    )
    assert any(p.startswith("/ui/static") for p in paths), (
        f"F5.5: rutes /ui/static/* haurien d'estar en standalone. paths={paths}"
    )
    # JSON endpoints també.
    assert "/ui/info" in paths
    assert "/ui/backends" in paths
