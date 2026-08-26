"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_g8_uvicorn_limits.py
Description: G8 gate (#918) — the uvicorn limits must hold on BOTH start-up
    paths, measured on the LIVE uvicorn.Config that each path produces, never
    by reading the sidecar script or grepping the source.

    Path A (CLI, ./nexe): core.server.runner._run_uvicorn_server() -> uvicorn.run(**kw)
    Path B (product, sidecar/lib.rs): python -m uvicorn core.app:app --host --port
                                      --workers 1 --lifespan on --no-access-log --app-dir

    Both paths resolve the very same app string ("core.app:app"), so core/app.py
    is the one place where they cannot diverge: it applies UVICORN_LIMITS onto
    the live Config while uvicorn is loading the app.

    Mutation target: drop the limits from core/app.py -> the two path tests
    turn RED (documented in resultats/dev1_result.md).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import sys
import types

import pytest
import uvicorn
from fastapi import FastAPI

# The exact flags the product passes (nexe-app sidecar and src-tauri/lib.rs use
# an identical argv). Declared here as data, on purpose: the gate must measure
# the live Config, not read the launcher script.
PRODUCT_FLAGS = {
    "host": "127.0.0.1",
    "port": 8765,
    "workers": 1,
    "lifespan": "on",
    "access_log": False,
}

# Decision of 23/08/2026 (finding #918, option b): the real delta between the
# two paths is these two parameters, and only these two.
EXPECTED_LIMITS = {
    "timeout_graceful_shutdown": 10,
    "limit_concurrency": 100,
}


@pytest.fixture
def light_app(monkeypatch):
    """Replace the FastAPI factory with an empty app — GLOBAL mock, no per-argument branching.

    Config.load() resolves "core.app:app", which would otherwise build the whole
    server (plugins, models, disk). The limits under test live on the Config
    object, not on the app, so an empty app measures exactly the same thing at a
    fraction of the cost. No conditional mocking: every caller gets the stub.
    """
    import core.server.factory as factory
    monkeypatch.setattr(factory, "create_app", lambda *a, **k: FastAPI())


def _live_config(**kwargs) -> uvicorn.Config:
    """Build and LOAD a real uvicorn.Config for "core.app:app" and return it.

    load() is what imports the app module, which is the moment core/app.py gets
    to apply the limits — so the returned object is the live config, the same
    one Server.shutdown() and the HTTP protocols read at runtime.
    """
    sys.modules.pop("core.app", None)
    config = uvicorn.Config("core.app:app", **kwargs)
    config.load()
    return config


def _cli_kwargs(monkeypatch) -> dict:
    """Capture the kwargs the CLI path really hands to uvicorn.run().

    GLOBAL double: run() is replaced for every call, with no branching on the
    arguments, so no start-up path can slip past unmocked.
    """
    captured: dict = {}

    def _capture(app, **kw):
        captured["app"] = app
        captured.update(kw)

    import core.server.runner as runner
    monkeypatch.setattr(runner, "uvicorn", types.SimpleNamespace(run=_capture))
    runner._run_uvicorn_server("127.0.0.1", 8765, 1, False, None)

    assert captured.get("app") == "core.app:app", (
        f"the CLI path must start the same app string as the product; got {captured.get('app')!r}"
    )
    return {k: v for k, v in captured.items() if k != "app"}


def _discovered_limit_params() -> set:
    """Discover every limit/timeout knob uvicorn.Config accepts — do not enumerate.

    Rule §1.7: a gate that lists cases can be walked around by the side door.
    The list comes from uvicorn's own signature, so a knob added by an upgrade
    is covered the day it appears.
    """
    params = inspect.signature(uvicorn.Config.__init__).parameters
    return {n for n in params if n.startswith(("limit_", "timeout_"))}


def test_discovery_covers_the_known_limits():
    """Scope control: if the discovery above ever shrinks, this fails on its own."""
    discovered = _discovered_limit_params()
    known = {"timeout_keep_alive", "timeout_graceful_shutdown",
             "limit_concurrency", "limit_max_requests"}
    missing = known - discovered
    assert not missing, (
        f"the limit discovery no longer covers {sorted(missing)}; a narrowed "
        f"discovery would let a divergence pass unseen. Discovered: {sorted(discovered)}"
    )


def test_product_path_carries_the_limits(light_app):
    """#918: the path the user actually runs must carry the limits."""
    config = _live_config(**PRODUCT_FLAGS)
    actual = {k: getattr(config, k) for k in EXPECTED_LIMITS}
    assert actual == EXPECTED_LIMITS, (
        f"the product start-up path runs without the limits: {actual} != {EXPECTED_LIMITS}"
    )


def test_cli_path_carries_the_limits(light_app, monkeypatch):
    """The ./nexe path must end up with the same live values, whoever sets them."""
    config = _live_config(**_cli_kwargs(monkeypatch))
    actual = {k: getattr(config, k) for k in EXPECTED_LIMITS}
    assert actual == EXPECTED_LIMITS, (
        f"the CLI start-up path lost the limits: {actual} != {EXPECTED_LIMITS}"
    )


def test_both_paths_agree_on_every_limit(light_app, monkeypatch):
    """No limit/timeout knob may differ between the two paths.

    This is the anti-divergence guard: it compares every knob discovered from
    uvicorn's signature, so re-introducing a hand-synchronised value on one path
    only (the #918 shape) turns it red without anyone updating this test.

    #943: this only sees UN-governed knobs (e.g. timeout_keep_alive) diverge.
    For the two EXPECTED_LIMITS, core/app.py's setattr in _apply_uvicorn_limits
    runs during config.load() and overwrites BOTH paths' Config with the same
    values regardless of what each path handed uvicorn.Config — so a
    hand-synced copy on the CLI side (commit 74bed86d's shape) still ends up
    equal here. See test_cli_path_does_not_duplicate_the_governed_limits below,
    which compares the raw kwargs instead of the post-load Config for exactly
    those two.
    """
    cli_kwargs = _cli_kwargs(monkeypatch)
    cli = _live_config(**cli_kwargs)
    product = _live_config(**PRODUCT_FLAGS)

    divergent = {
        name: (getattr(cli, name), getattr(product, name))
        for name in sorted(_discovered_limit_params())
        if getattr(cli, name) != getattr(product, name)
    }
    assert not divergent, (
        "CLI and product start-up paths diverge on (cli, product): "
        f"{divergent}. Limits belong in core/app.py, the only place the two paths share."
    )


def test_cli_path_does_not_duplicate_the_governed_limits(monkeypatch):
    """#943: EXPECTED_LIMITS must come from ONE place — core/app.py — never
    from a hand-synced copy in core/server/runner.py (commit 74bed86d).

    Compares the RAW kwargs the CLI path hands to uvicorn.run(), not the
    loaded Config: core/app.py's setattr always overwrites the governed knobs
    on both paths, so a hand-synced copy on the CLI side — right or wrong —
    is invisible to test_both_paths_agree_on_every_limit above. Reproduced
    (MUT2): re-adding timeout_graceful_shutdown=99, limit_concurrency=7 to
    the CLI kwargs left that test at 6 passed, green.
    """
    cli_kwargs = _cli_kwargs(monkeypatch)
    duplicated = set(cli_kwargs) & set(EXPECTED_LIMITS)
    assert not duplicated, (
        f"the CLI path hands {sorted(duplicated)} to uvicorn.run() directly — "
        "a hand-synced copy of what core/app.py already applies. "
        "core/app.py's setattr would mask any drift here silently."
    )


def test_limits_helper_is_inert_without_uvicorn(monkeypatch, caplog):
    """Importing core.app must not require uvicorn.

    The module is also imported by CLI commands and tooling that never start a
    server. With no uvicorn around, the helper reports "nothing applied" instead
    of raising — which is also the honest answer: there is no live config. This
    case is unremarkable (uvicorn is not even here to run a server), so it logs
    at debug, not warning — see the sibling test below for the case that must
    be loud.
    """
    import core.app as app_module

    monkeypatch.setitem(sys.modules, "uvicorn.config", None)
    with caplog.at_level("DEBUG", logger="core.app"):
        assert app_module._apply_uvicorn_limits() is False
    assert not any(r.levelname == "WARNING" for r in caplog.records)


def test_limits_helper_is_inert_outside_a_server(caplog):
    """#950: called with no uvicorn.Config on the stack, it must report False —
    and, unlike the no-uvicorn case, warn about it. limit_concurrency is a
    protection, not a preference: a silent False here is exactly how a real
    server could end up running without its concurrency ceiling and nobody
    finding out.
    """
    import core.app as app_module

    with caplog.at_level("WARNING", logger="core.app"):
        assert app_module._apply_uvicorn_limits() is False
    assert any(
        r.levelname == "WARNING" and "were NOT applied" in r.message
        for r in caplog.records
    ), f"expected a WARNING naming the unapplied limits, got: {[r.message for r in caplog.records]}"
