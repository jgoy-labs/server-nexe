"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_engine_table.py
Description: API providers, phase 3 — ONE table of engines. `ENGINE_CASCADE`,
    the module keys, the aliases, the web dropdown's ids and /status's
    availability used to be five hand-written copies that had to agree (phase 2
    added the API engine to three of them and kept it out of a fourth by hand).
    They are read off `routing.ENGINE_TABLE` now. What is pinned here: the
    table's own invariants (above all, the API engine is never a step of the
    automatic chain), that every consumer really reads the table (a consumer
    that keeps a copy makes a test red), and that no module of the engine
    plumbing writes a list of engine names again.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.endpoints.chat_engines import routing
from core.providers.cloud import CLOUD_ENGINE

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ["mlx", "llama_cpp", "ollama"]


# ------------------------------------------------------------- the table itself

def test_the_table_lists_the_three_local_engines_in_chain_order_and_the_api_apart():
    assert [e.name for e in routing.ENGINE_TABLE] == LOCAL + ["api"]
    assert routing.ENGINE_CASCADE == LOCAL
    assert routing.ENGINE_MODULE_KEYS == {
        "mlx": "mlx_module", "llama_cpp": "llama_cpp_module", "ollama": "ollama_module", "api": "api_module",
    }


def test_the_api_engine_is_in_the_table_and_never_a_step_of_the_chain():
    entry = routing.engine_entry(CLOUD_ENGINE)
    assert entry is not None and entry.cloud is True and entry.in_cascade is False
    assert CLOUD_ENGINE not in routing.ENGINE_CASCADE


def test_a_hosted_engine_can_never_be_declared_in_the_cascade():
    """A table-wide rule, so the day somebody adds a hosted engine the mistake is a red test here, not a
    fallback to the cloud in production."""
    for entry in routing.ENGINE_TABLE:
        assert not (entry.cloud and entry.in_cascade), entry.name
        assert not (entry.cloud and entry.in_process), entry.name
        assert not (entry.in_process and not entry.in_cascade), entry.name


def test_names_keys_and_dropdown_ids_are_unique():
    for field in ("name", "module_key", "ui_id"):
        values = [getattr(e, field) for e in routing.ENGINE_TABLE]
        assert len(values) == len(set(values)), field
    spellings = [s for e in routing.ENGINE_TABLE for s in (e.name, e.module_key, e.ui_id, *e.aliases)]
    owners: dict = {}
    for entry in routing.ENGINE_TABLE:
        for spelling in (entry.name, entry.module_key, entry.ui_id, *entry.aliases):
            assert owners.setdefault(spelling, entry.name) == entry.name, f"{spelling} names two engines"
    assert len(spellings) >= len(routing.ENGINE_TABLE) * 3


def test_who_runs_in_process_and_who_is_hosted_is_read_off_the_table():
    assert [e.name for e in routing.ENGINE_TABLE if e.in_process] == ["mlx", "llama_cpp"]
    assert [e.name for e in routing.ENGINE_TABLE if e.cloud] == ["api"]
    assert routing.engine_entry("nobody") is None and routing.engine_entry(None) is None


@pytest.mark.parametrize("spelling, canonical", [
    ("llama.cpp", "llama_cpp"), ("llama-cpp", "llama_cpp"), ("llamacpp", "llama_cpp"), (" LLAMA_CPP ", "llama_cpp"),
    ("MLX", "mlx"), ("Ollama", "ollama"), (" API ", "api"), ("auto", "auto"), ("mystery", "mystery"),
])
def test_the_spellings_a_request_may_use_are_read_off_the_table(spelling, canonical):
    assert routing._normalize_engine(spelling) == canonical


def test_the_status_endpoint_spells_names_the_same_way_but_says_empty_for_none():
    from core.endpoints.root import _normalize_engine
    assert _normalize_engine("llama.cpp") == "llama_cpp" and _normalize_engine(None) == "" and _normalize_engine("") == ""


@pytest.mark.parametrize("engine, expected", [
    ("api", True), ("API", True), (" Api ", True), ("mlx", False), ("llama_cpp", False), ("ollama", False),
    ("", False), (None, False), ("mystery", False),
])
def test_is_it_hosted_by_name(engine, expected):
    assert routing.engine_is_cloud(engine) is expected


def test_is_it_hosted_by_what_the_module_declares_exactly_true():
    assert routing.engine_is_cloud(SimpleNamespace(runs_in_the_cloud=True)) is True
    for not_hosted in (SimpleNamespace(), SimpleNamespace(runs_in_the_cloud=False), SimpleNamespace(runs_in_the_cloud="yes"),
                       SimpleNamespace(runs_in_the_cloud=1)):
        assert routing.engine_is_cloud(not_hosted) is False

    class AnswersAnything:  # a test double that has every attribute is not a provider
        def __getattr__(self, _name):
            return object()

    assert routing.engine_is_cloud(AnswersAnything()) is False


# ------------------------------------------------------- the API never joins the chain

@pytest.mark.parametrize("asked", LOCAL + ["llama.cpp", "auto", None, "", "mystery"])
@pytest.mark.parametrize("env_engine", ["api", "auto", "ollama"])
def test_nothing_but_an_explicit_request_for_the_api_ever_puts_it_in_a_cascade(monkeypatch, asked, env_engine):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", env_engine)
    modules = {entry.module_key: SimpleNamespace(_node=object(), chat=lambda *a, **k: None) for entry in routing.ENGINE_TABLE}
    state = SimpleNamespace(modules=modules, config={})
    for cloud_ok in (False, True):
        assert CLOUD_ENGINE not in routing.resolve_engine_cascade(asked, state, cloud_ok=cloud_ok)
    resolved, fallback_from = routing._resolve_engine(asked, state, cloud_ok=True)
    assert resolved in LOCAL and fallback_from != CLOUD_ENGINE


def test_an_environment_preference_for_the_api_is_not_reported_as_the_engine_that_was_asked(monkeypatch):
    """`NEXE_MODEL_ENGINE=api` is not a request: the chain is local and says nothing of a fallback FROM the API."""
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "api")
    state = SimpleNamespace(modules={"mlx_module": SimpleNamespace(_node=object(), chat=lambda *a, **k: None)}, config={})
    assert routing._resolve_engine(None, state) == ("mlx", None)
    assert routing._resolve_engine("auto", state) == ("mlx", None)


def test_the_resolver_answers_an_explicit_api_by_itself_or_not_at_all():
    state = SimpleNamespace(modules={"ollama_module": SimpleNamespace(chat=lambda *a, **k: None),
                                     "api_module": SimpleNamespace(chat=lambda *a, **k: None)}, config={})
    assert routing._resolve_engine("api", state, cloud_ok=True) == ("api", None)
    assert routing._resolve_engine(" API", state, cloud_ok=True) == ("api", None)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as no_gate:
        routing._resolve_engine("api", state)
    assert no_gate.value.status_code == 400
    unloaded = SimpleNamespace(modules={"ollama_module": SimpleNamespace(chat=lambda *a, **k: None)}, config={})
    with pytest.raises(HTTPException) as not_loaded:
        routing._resolve_engine("api", unloaded, cloud_ok=True)
    assert not_loaded.value.status_code == 503, "a gate that passed with no module is an error, not a local answer"


# ------------------------------------------------- every consumer reads the table

def test_the_availability_rule_comes_from_the_table():
    live_node = SimpleNamespace(_node=object())
    dead_node = SimpleNamespace(_node=None)
    state = SimpleNamespace(modules={"mlx_module": live_node, "llama_cpp_module": dead_node, "ollama_module": object(),
                                     "api_module": object()})
    assert [routing._engine_available(e.name, state) for e in routing.ENGINE_TABLE] == [True, False, True, True]
    assert routing._engine_available("mystery", state) is False
    assert routing._engine_available("mlx", SimpleNamespace(modules={})) is False


def test_status_requires_the_preferred_engine_and_only_it_for_every_engine_of_the_table():
    from core.endpoints.root import _required_modules_from_config
    everything = [e.module_key for e in routing.ENGINE_TABLE] + ["security", "web_ui_module"]
    for entry in routing.ENGINE_TABLE:
        config = {"plugins": {"modules": {"enabled": everything}, "models": {"preferred_engine": entry.name}}}
        required = _required_modules_from_config(config)
        assert entry.module_key in required
        assert {e.module_key for e in routing.ENGINE_TABLE} & required == {entry.module_key}
        assert {"security", "web_ui_module"} <= required
    nothing = {"plugins": {"modules": {"enabled": everything}, "models": {"preferred_engine": "auto"}}}
    assert {e.module_key for e in routing.ENGINE_TABLE} & _required_modules_from_config(nothing) == set()


def test_the_dropdown_ids_and_aliases_are_read_off_the_table():
    from plugins.web_ui_module.api import routes_auth
    ids = routes_auth._backend_ids()
    assert ids == {e.name: e.ui_id for e in routing.ENGINE_TABLE}
    assert ids["llama_cpp"] == "llamacpp", "the dropdown spells it differently from the chain"
    assert routes_auth._auto_backend_cascade() == ("mlx", "llamacpp", "ollama")
    aliases = routes_auth._backend_aliases()
    assert aliases.pop("auto") == "auto"
    for entry in routing.ENGINE_TABLE:
        for spelling in (entry.name, entry.module_key, entry.ui_id, *entry.aliases):
            assert aliases[spelling] == entry.ui_id
    assert set(aliases.values()) == {e.ui_id for e in routing.ENGINE_TABLE}


def test_the_status_lists_exactly_the_engines_of_the_chain(monkeypatch):
    import asyncio

    from core.endpoints import root

    state = SimpleNamespace(modules={"ollama_module": object()}, config={}, minimal_mode=False)
    request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(), headers={}, client=None)
    request.app.state = state
    data = asyncio.run(root.server_status.__wrapped__(request, "k")) if hasattr(root.server_status, "__wrapped__") else None
    if data is None:
        pytest.skip("status endpoint is wrapped by the rate limiter")
    assert list(data["engines_available"]) == routing.ENGINE_CASCADE
    assert CLOUD_ENGINE not in data["engines_available"]


# ------------------------------------------------- nobody keeps a copy

#: Where the engine plumbing lives. A list of engine names in any of these files, other than the
#: table, is a copy waiting to diverge. (The installer and the CLI name engines too, but as install
#: kinds and display labels: another vocabulary, not this one.)
_SCANNED = ("core/endpoints", "core/turn", "core/sessions", "plugins/web_ui_module/api")
_EXEMPT = {"core/endpoints/chat_engines/routing.py", "core/endpoints/installer.py"}
_NAMES = {"mlx", "llama_cpp", "ollama", "api"}
_KEYS = {e.module_key for e in routing.ENGINE_TABLE}


def _collections(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            yield node, [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        elif isinstance(node, ast.Dict):
            yield node, [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]


def _copies() -> list:
    found = []
    for folder in _SCANNED:
        for path in sorted((ROOT / folder).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if relative in _EXEMPT:
                continue
            for node, values in _collections(ast.parse(path.read_text(encoding="utf-8"))):
                if len(_NAMES & set(values)) >= 2 or len(_KEYS & set(values)) >= 2:
                    found.append(f"{relative}:{node.lineno} {values[:5]}")
    return found


def test_no_module_of_the_engine_plumbing_writes_a_list_of_engines_again():
    assert _copies() == []


def test_the_scan_that_says_so_can_actually_see_a_copy():
    """The guard is only worth something if it fires: a snippet with a hand-written chain is found."""
    tree = ast.parse('CHAIN = ("mlx", "llama_cpp")\nKEYS = {"mlx_module": 1, "ollama_module": 2}\nOK = ["mlx", "gguf"]')
    hits = [values for _node, values in _collections(tree) if len(_NAMES & set(values)) >= 2 or len(_KEYS & set(values)) >= 2]
    assert hits == [["mlx", "llama_cpp"], ["mlx_module", "ollama_module"]]


# --------------------------------------------- the request-level gate, and what binds a hosted engine

def test_a_body_that_does_not_ask_for_the_api_is_never_asked_the_gate_and_never_gets_it(monkeypatch):
    asked: list = []
    monkeypatch.setattr(routing, "cloud_gate", lambda body: asked.append(body))
    for engine in ("mlx", "llama_cpp", "ollama", "auto", None, "", "mystery", "llama.cpp"):
        assert routing.cloud_request_ok(SimpleNamespace(engine=engine)) is False, engine
    assert routing.cloud_request_ok(SimpleNamespace()) is False, "a body with no engine at all"
    assert asked == [], "the gate is for the API only"


def test_a_body_that_asks_for_the_api_gets_it_only_when_the_gate_lets_it(monkeypatch):
    from fastapi import HTTPException

    seen: list = []
    monkeypatch.setattr(routing, "cloud_gate", lambda body: seen.append(body))
    for spelling in ("api", "API", " Api "):
        body = SimpleNamespace(engine=spelling)
        assert routing.cloud_request_ok(body) is True
        assert seen[-1] is body, "the gate looks at THIS body"

    def refuse(body):
        raise HTTPException(status_code=403, detail="no")

    monkeypatch.setattr(routing, "cloud_gate", refuse)
    with pytest.raises(HTTPException):
        routing.cloud_request_ok(SimpleNamespace(engine="api"))


def test_a_module_is_bound_only_when_it_declares_it_is_hosted_and_can_bind():
    bound: list = []

    class CanBind:
        def for_model(self, model):
            bound.append(model)
            return ("view", model)

    hosted = CanBind()
    hosted.runs_in_the_cloud = True
    assert routing.bind_to_model(hosted, "gpt-4o") == ("view", "gpt-4o")
    # a double that can bind but does not say it is hosted: left as it is
    unflagged = CanBind()
    assert routing.bind_to_model(unflagged, "gpt-4o") is unflagged
    flagged_false = CanBind()
    flagged_false.runs_in_the_cloud = False
    assert routing.bind_to_model(flagged_false, "gpt-4o") is flagged_false
    # hosted, but with nothing to bind with: as it is, not a crash
    plain_hosted = SimpleNamespace(runs_in_the_cloud=True)
    assert routing.bind_to_model(plain_hosted, "m") is plain_hosted
    not_callable = SimpleNamespace(runs_in_the_cloud=True, for_model="no")
    assert routing.bind_to_model(not_callable, "m") is not_callable
    assert routing.bind_to_model(None, "m") is None
    assert bound == ["gpt-4o"]


def test_what_the_resolver_says_when_the_api_may_not_be_answered_is_exact():
    from fastapi import HTTPException

    state = SimpleNamespace(modules={"ollama_module": SimpleNamespace(chat=lambda *a, **k: None)}, config={})
    with pytest.raises(HTTPException) as no_gate:
        routing._resolve_engine("api", state)
    assert (no_gate.value.status_code, no_gate.value.detail) == (400, "The API engine needs the cloud gate on this endpoint")
    with pytest.raises(HTTPException) as not_loaded:
        routing._resolve_engine("api", state, cloud_ok=True)
    assert (not_loaded.value.status_code, not_loaded.value.detail) == (503, "The API engine is not loaded on this server")


@pytest.mark.parametrize("env", ["auto", "", "AUTO"])
def test_an_auto_preference_is_not_an_engine_that_failed_so_no_fallback_is_reported(monkeypatch, env):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", env)
    state = SimpleNamespace(modules={"ollama_module": SimpleNamespace(chat=lambda *a, **k: None)}, config={})
    assert routing._resolve_engine(None, state) == ("ollama", None)
    assert routing._resolve_engine("auto", state) == ("ollama", None)
    assert routing._resolve_engine("", state) == ("ollama", None)


def test_the_label_a_stream_chunk_carries_for_each_engine_of_the_table():
    from core.turn.adapters_api import _engine_prefix

    assert [_engine_prefix(e) for e in ("mlx", "llama_cpp", "llama.cpp", "ollama", "api", "API")] == [
        "mlx", "llamacpp", "llamacpp", "ollama", "api", "api"]
    assert _engine_prefix(None) == "ollama" and _engine_prefix("mystery") == "ollama", "the label default is unchanged"


def test_every_step_that_must_write_a_field_may_write_it():
    from core.turn.steps import TURN_STEPS

    for step in TURN_STEPS:
        assert step.writes_always <= step.writes, step.id
