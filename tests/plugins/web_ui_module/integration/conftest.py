"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/integration/conftest.py
Description: Test isolation for the web_ui integration endpoints.
             Boots the lifespan in FULL mode deterministically by providing
             a completed OnboardingState inside an isolated NEXE_DATA_DIR,
             and restores every env var that startup mutates.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import os

import pytest

# Env vars mutated either by this fixture (NEXE_DATA_DIR) or by
# OnboardingState.apply_to_env() during lifespan startup
# (core/lifespan.py::_startup_init). All of them are saved before the test
# module runs and restored afterwards, so this module cannot leak state into
# the rest of the suite.
_MUTATED_ENV_VARS = (
    "NEXE_DATA_DIR",
    "NEXE_MODEL_ENGINE",
    "NEXE_DEFAULT_MODEL",
    "NEXE_LANG",
    "NEXE_MLX_MODEL",
    "NEXE_LLAMA_CPP_MODEL",
    "NEXE_STORAGE_PATH",
    "HF_TOKEN",
)


@pytest.fixture(scope="module", autouse=True)
def completed_onboarding_env(tmp_path_factory):
    """Provide a completed OnboardingState in an isolated NEXE_DATA_DIR.

    Root cause of the historical flakiness in this module: these integration
    tests boot the real lifespan via TestClient(app). Without a persisted
    onboarding.json the server enters MINIMAL MODE
    (core/lifespan.py::_startup) and never calls WebUIModule.initialize(),
    so every /ui route touching the SessionManager raises
    "SessionManager accessed before WebUIModule.initialize() completed".

    Whether onboarding.json existed depended on machine state
    (~/Library/Application Support/com.nexe.app/sidecar/onboarding.json) or
    on a NEXE_DATA_DIR / NEXE_MODEL_ENGINE left behind by earlier tests —
    i.e. order- and environment-dependent. This fixture pins it:
    - full-mode startup, always (deterministic);
    - isolated data dir, so chat sessions are written under tmp instead of
      the repo working tree;
    - engine pinned to "ollama", so the GPU-marked TestChatMLX/TestChatOllama
      classes skip or run based solely on their own resource guards.
    """
    saved = {key: os.environ.get(key) for key in _MUTATED_ENV_VARS}

    data_dir = tmp_path_factory.mktemp("web-ui-data")
    default_model = os.environ.get("NEXE_DEFAULT_MODEL", "gemma3:4b")
    state = {
        "version": 2,
        "engine": "ollama",
        "model_id": default_model,
        "model_path": default_model,
        "completed_at": "2026-01-01T00:00:00+00:00",
        "has_token": False,
        "lang": "en",
    }
    (data_dir / "onboarding.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    os.environ["NEXE_DATA_DIR"] = str(data_dir)

    yield

    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _iter_route_limiters(app):
    """Yield every slowapi Limiter captured in the app's route closures.

    The web_ui router is a cached lazy singleton (core/loader/manifest_base),
    while the suite's session ``app`` fixture calls
    create_app(force_reload=True) which re-imports core.dependencies. After a
    reload, ``app.state.limiter`` / ``core.dependencies.limiter`` point to a
    NEW Limiter, but the cached router's ``@limiter.limit(...)`` wrappers
    still hold the OLD instance in their closures — and that is the one that
    actually enforces the per-minute windows at request time. Resetting only
    the module attribute (as the root-conftest F56 fixture does) therefore
    misses it, and its counters accumulate across the whole suite.
    """
    from slowapi.extension import Limiter

    seen: set = set()
    for route in app.routes:
        fn = getattr(route, "endpoint", None)
        depth = 0
        while fn is not None and depth < 5:
            for cell in (getattr(fn, "__closure__", None) or ()):
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, Limiter) and id(value) not in seen:
                    seen.add(id(value))
                    yield value
            fn = getattr(fn, "__wrapped__", None)
            depth += 1


@pytest.fixture(autouse=True)
def _reset_ui_rate_limits(request):
    """Reset rate-limit state on the exact app instance these tests use.

    Mid-suite, earlier files hitting /ui endpoints within the same minute
    consumed the per-IP windows ("20 per 1 minute" on /ui/chat) of the
    limiter serving these routes, producing spurious 429s here.

    Crucially we must NOT do ``from core.app import app`` at fixture runtime:
    the root-conftest session ``app`` fixture calls
    create_app(force_reload=True), which re-imports core.app mid-suite. The
    test module captured the PRE-reload app object at collection time, while
    a runtime import returns the POST-reload one — resetting the latter (as
    the root F56 fixture effectively does) leaves the limiter that actually
    serves these requests untouched. We therefore take the app object from
    the requesting test module itself and reset every Limiter reachable from
    it (app.state plus route closures).
    """
    app = getattr(request.module, "app", None)
    if app is not None:
        limiters = {id(lim): lim for lim in _iter_route_limiters(app)}
        state_limiter = getattr(app.state, "limiter", None)
        if state_limiter is not None:
            limiters.setdefault(id(state_limiter), state_limiter)
        for lim in limiters.values():
            try:
                if hasattr(lim, "reset"):
                    lim.reset()
                _dedupe_route_limits(lim)
            except Exception:  # nosec B110 — best-effort isolation, never block the test
                pass
    try:
        from plugins.web_ui_module.api.routes_auth import _ui_auth_failures
        _ui_auth_failures.clear()
    except Exception:  # nosec B110 — best-effort isolation, never block the test
        pass
    yield


def _dedupe_route_limits(lim) -> None:
    """Collapse duplicate slowapi limit registrations per endpoint name.

    slowapi's ``@limiter.limit(...)`` EXTENDS ``_route_limits[func_name]`` on
    every decoration. In production create_router() runs once per process, but
    across the suite each test that instantiates WebUIModule re-runs
    create_router() against the same shared limiter, so e.g. "20/minute" for
    the chat endpoint accumulates N duplicate entries — and one real request
    then consumes N counter hits at once, tripping the window on the FIRST
    call (observed: 21 hits for a single POST /ui/chat mid-suite). Test-env
    artifact only; deduping here restores the declared semantics.
    """
    route_limits = getattr(lim, "_route_limits", None)
    if not isinstance(route_limits, dict):
        return
    for name, registered in route_limits.items():
        seen: set = set()
        unique = []
        for entry in registered:
            key = (
                str(getattr(entry, "limit", None)),
                getattr(entry, "scope", None),
                getattr(entry, "per_method", None),
                str(getattr(entry, "methods", None)),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        route_limits[name] = unique
