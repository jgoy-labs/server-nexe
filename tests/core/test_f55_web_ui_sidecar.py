"""F5.5 (revertit 2026-05-21) — web_ui_module sempre serveix UI completa.

Substitueix `test_f25_stubs_sidecar.py` (eliminat). La decisió F2.5 era massa
agressiva: desactivava web_ui_module sencer en sidecar. F5.5 va corregir
això mantenint els JSON endpoints en sidecar, però va saltar les rutes
HTML/static i va delegar el servei UI a una còpia local a Tauri
(`nexe-app/public/ui/`). Aquella còpia va quedar stale ràpidament
(fix S5 21/05 mai va arribar al bundle) — DMG mostrava `{{NEXE_VERSION}}`
literal i selector d'idioma desincronitzat.

Aquesta reversió (2026-05-21 vespre) restableix el comportament històric:
  1. manifest `disabled_in_sidecar=false` — sense canvi
  2. `routes.py` registra `register_static_routes()` SEMPRE — la UI Tauri
     navega a `http://127.0.0.1:{port}/` un cop el sidecar està ready
  3. JSON endpoints continuen sempre registrats

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


def test_router_includes_html_routes_in_sidecar(sidecar_env, monkeypatch):
    """F5.5 revertit — en sidecar mode, `create_router()` SÍ ha de registrar
    `/ui/` (HTML) i `/ui/static/{path}`, igual que en standalone.

    El DMG navega el webview Tauri a http://127.0.0.1:{port}/ un cop el
    sidecar està ready, i `serve_ui` aplica les substitucions server-side
    (NEXE_VERSION, data-nexe-lang). Sentinel anti-regressió: si algú torna
    a saltar `register_static_routes` en sidecar, el bundle DMG tornarà a
    mostrar `{{NEXE_VERSION}}` literal i strings stale.
    """
    from plugins.web_ui_module.module import WebUIModule
    from plugins.web_ui_module.api.routes import create_router

    mod = WebUIModule()
    router = create_router(mod)
    paths = _collect_router_paths(router)
    assert "/ui/" in paths, (
        f"F5.5 revertit: ruta HTML /ui/ ha de registrar-se en sidecar. paths={paths}"
    )
    assert any(p.startswith("/ui/static") for p in paths), (
        f"F5.5 revertit: rutes /ui/static/* han de registrar-se en sidecar. paths={paths}"
    )
    assert "/ui/info" in paths, f"/ui/info absent en sidecar. paths={paths}"
    assert "/ui/backends" in paths, f"/ui/backends absent en sidecar. paths={paths}"


def test_router_includes_html_routes_in_standalone(clean_sidecar_env, monkeypatch):
    """Standalone mode (no sidecar) — HTML/static + JSON endpoints registrats.

    El comportament és idèntic al de sidecar: la UI sencera disponible al
    sidecar HTTP. La diferència entre modes ja no afecta el router.
    """
    from plugins.web_ui_module.module import WebUIModule
    from plugins.web_ui_module.api.routes import create_router

    mod = WebUIModule()
    router = create_router(mod)
    paths = _collect_router_paths(router)
    assert "/ui/" in paths, (
        f"ruta HTML /ui/ (root index.html) ha de registrar-se en standalone. paths={paths}"
    )
    assert any(p.startswith("/ui/static") for p in paths), (
        f"rutes /ui/static/* haurien d'estar en standalone. paths={paths}"
    )
    assert "/ui/info" in paths
    assert "/ui/backends" in paths
