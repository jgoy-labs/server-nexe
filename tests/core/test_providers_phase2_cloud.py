"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_providers_phase2_cloud.py
Description: API providers, phase 2 — the pieces that decide WHETHER a turn
    may leave the machine, apart from the web door: the registry's per-model
    answers, the global switch (fail-closed), the consent per session and the
    routing tables, with the one rule Jordi fixed (06/10): the API is chosen,
    never fallen back to. No network; the key is obviously fake.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import core.endpoints.chat  # noqa: F401  (breaks a circular import when this file runs alone)
from core.endpoints.chat_engines import routing
from core.providers import PROVIDERS, Provider
from core.providers.cloud import (
    ALLOW_CLOUD_ENV, CLOUD_ENGINE, CloudRefusal, cloud_engines_allowed,
    require_cloud_selection, require_cloud_turn,
)
from core.providers.registry import (
    get_provider, model_can_see_images, model_context_window, provider_for_model,
)

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from core import runtime_state
    runtime_state.reset()
    monkeypatch.delenv(ALLOW_CLOUD_ENV, raising=False)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)  # other tests leave a preference behind
    for p in PROVIDERS:
        monkeypatch.delenv(p.env_var, raising=False)
    yield
    runtime_state.reset()


# --------------------------------------------------------------------- registry

class TestRegistryPerModel:
    @pytest.mark.parametrize("model,key", [
        ("deepseek-chat", "deepseek"), ("deepseek-reasoner", "deepseek"),
        ("gpt-4o", "openai"), ("gpt-5-mini", "openai"),
    ])
    def test_a_model_belongs_to_the_provider_whose_allowlist_names_it(self, model, key):
        assert provider_for_model(model).key == key

    @pytest.mark.parametrize("model", ["", None, "llama3.2:3b", "deepseek-chat-evil-extra", "DeepSeek-Chat", 7, "gpt"])
    def test_anything_else_belongs_to_nobody(self, model):
        assert provider_for_model(model) is None

    def test_the_chat_path_is_declared_per_entry_not_guessed(self):
        assert get_provider("deepseek").chat_path == "/v1/chat/completions"
        assert get_provider("openai").chat_path == "/v1/chat/completions"
        assert Provider(key="k", name="K", endpoint="https://x", env_var="E", models=("m",)).chat_path == "/v1/chat/completions"
        custom = Provider(key="k", name="K", endpoint="https://x", env_var="E", models=("m",), chat_path="/chat/completions")
        assert custom.chat_path == "/chat/completions"

    def test_vision_is_declared_per_model(self):
        openai, deepseek = get_provider("openai"), get_provider("deepseek")
        assert model_can_see_images(openai, "gpt-4o") and model_can_see_images(openai, "gpt-4o-mini")
        assert model_can_see_images(openai, "gpt-4.1-mini") and model_can_see_images(openai, "gpt-5-mini")
        assert not model_can_see_images(openai, "gpt-3.5-turbo")
        assert not model_can_see_images(deepseek, "deepseek-chat")
        assert not model_can_see_images(openai, "") and not model_can_see_images(openai, None)

    def test_the_window_is_per_model_pattern_then_the_entrys_default(self):
        tiered = Provider(key="k", name="K", endpoint="https://x", env_var="E", models=("m-*",),
                          context_window=1000, model_windows=(("m-big*", 9000), ("m-*", 2000)))
        assert model_context_window(tiered, "m-big-1") == 9000, "the first matching pattern wins"
        assert model_context_window(tiered, "m-small") == 2000
        assert model_context_window(tiered, "other") == 1000
        assert model_context_window(tiered, None) == 1000
        assert model_context_window(get_provider("deepseek"), "deepseek-chat") == 64000
        assert model_context_window(get_provider("openai"), "gpt-4o") == 128000

    def test_a_models_own_window_beats_the_entrys_default_through_the_engine(self, monkeypatch):
        from core.providers import registry
        tiered = Provider(key="t", name="T", endpoint="https://x", env_var="T_KEY", models=("t-*",),
                          context_window=1000, model_windows=(("t-big", 9000),))
        monkeypatch.setattr(registry, "PROVIDERS", (tiered,))
        from plugins.api_module.module import ApiModule
        module = ApiModule()
        assert module.for_model("t-big").get_context_window() == 9000
        assert module.for_model("t-small").get_context_window() == 1000

    def test_the_selector_offers_only_concrete_names_the_entry_owns(self):
        for p in PROVIDERS:
            assert p.suggested_models, p.key
            assert all("*" not in m and provider_for_model(m) is p for m in p.suggested_models)


# ------------------------------------------------------------------ the switch

class TestGlobalSwitch:
    def test_off_by_default(self):
        assert cloud_engines_allowed() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " on ", "Yes"])
    def test_only_an_explicit_yes_turns_it_on(self, monkeypatch, value):
        monkeypatch.setenv(ALLOW_CLOUD_ENV, value)
        assert cloud_engines_allowed() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "2", "enable", "tru", "None"])
    def test_anything_else_is_off_a_typo_never_opens_the_machine(self, monkeypatch, value):
        monkeypatch.setenv(ALLOW_CLOUD_ENV, value)
        assert cloud_engines_allowed() is False

    def test_the_runtime_override_wins_over_the_environment_both_ways(self, monkeypatch):
        from core.runtime_state import set_override
        monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
        set_override(ALLOW_CLOUD_ENV, "0")
        assert cloud_engines_allowed() is False
        monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")
        set_override(ALLOW_CLOUD_ENV, "1")
        assert cloud_engines_allowed() is True


# ------------------------------------------------------------ the gate, in order

def _open(monkeypatch, provider="deepseek"):
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv(get_provider(provider).env_var, FAKE_KEY)


def _refusal(**kwargs) -> CloudRefusal:
    with pytest.raises(CloudRefusal) as exc:
        require_cloud_turn(**kwargs)
    return exc.value


class TestTheGate:
    def test_the_switch_is_judged_first_whatever_else_is_true(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
        refusal = _refusal(model="deepseek-chat", requested_consent="deepseek", session_consent="deepseek")
        assert (refusal.status, refusal.code) == (403, "cloud_engines_disabled")
        refusal = _refusal(model="nope", requested_consent=None, session_consent=None)
        assert refusal.code == "cloud_engines_disabled", "even a bad model says the switch first"

    def test_a_model_no_provider_owns_is_a_400(self, monkeypatch):
        monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
        for model in (None, "", "llama3.2:3b"):
            refusal = _refusal(model=model, requested_consent="deepseek", session_consent="deepseek")
            assert (refusal.status, refusal.code, refusal.provider) == (400, "cloud_model_not_allowed", None)

    def test_a_provider_without_its_key_is_a_400_that_names_it(self, monkeypatch):
        monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
        refusal = _refusal(model="deepseek-chat", requested_consent="deepseek", session_consent="deepseek")
        assert (refusal.status, refusal.code) == (400, "cloud_provider_not_configured")
        assert refusal.provider.key == "deepseek" and "DeepSeek" in refusal.message

    def test_without_consent_it_is_a_403_that_asks_for_it_by_provider(self, monkeypatch):
        _open(monkeypatch)
        refusal = _refusal(model="deepseek-chat", requested_consent=None, session_consent=None)
        assert (refusal.status, refusal.code) == (403, "cloud_consent_required")
        assert refusal.detail() == {
            "code": "cloud_consent_required", "message": refusal.message,
            "provider": "deepseek", "provider_name": "DeepSeek",
        }

    @pytest.mark.parametrize("requested,session", [("deepseek", None), (None, "deepseek"), ("deepseek", "deepseek")])
    def test_consent_from_the_request_or_from_the_session_lets_it_through(self, monkeypatch, requested, session):
        _open(monkeypatch)
        provider = require_cloud_turn("deepseek-chat", requested_consent=requested, session_consent=session)
        assert provider.key == "deepseek"

    @pytest.mark.parametrize("given", ["openai", "", "DEEPSEEK", ["deepseek"], {"deepseek": 1}, True, 1])
    def test_consent_is_for_that_provider_only_and_only_by_its_exact_key(self, monkeypatch, given):
        _open(monkeypatch)
        assert _refusal(model="deepseek-chat", requested_consent=given, session_consent=None).code == "cloud_consent_required"
        assert _refusal(model="deepseek-chat", requested_consent=None, session_consent=given).code == "cloud_consent_required"

    def test_selection_needs_no_consent_but_everything_else(self, monkeypatch):
        with pytest.raises(CloudRefusal) as exc:
            require_cloud_selection("deepseek-chat")
        assert exc.value.code == "cloud_engines_disabled"
        _open(monkeypatch)
        assert require_cloud_selection("deepseek-chat").key == "deepseek"

    def test_nothing_a_refusal_says_carries_the_key(self, monkeypatch):
        _open(monkeypatch)
        for model in ("deepseek-chat", "nope"):
            try:
                require_cloud_turn(model, requested_consent=None, session_consent=None)
            except CloudRefusal as refusal:
                dump = json.dumps(refusal.detail()) + str(refusal) + repr(refusal.__dict__)
                assert FAKE_KEY not in dump


# ----------------------------------------------------------------- the routing

def _state(*module_keys):
    modules = {}
    for key in module_keys:
        modules[key] = SimpleNamespace(_node=object(), chat=lambda *a, **k: None) if key in ("mlx_module", "llama_cpp_module") \
            else SimpleNamespace(chat=lambda *a, **k: None)
    return SimpleNamespace(modules=modules, config={})


class TestTheApiIsNeverInTheCascade:
    def test_the_cascade_constant_names_only_local_engines(self):
        assert routing.ENGINE_CASCADE == ["mlx", "llama_cpp", "ollama"]
        assert CLOUD_ENGINE not in routing.ENGINE_CASCADE

    def test_the_name_is_known_to_the_module_table_so_it_can_be_found(self):
        assert routing.ENGINE_MODULE_KEYS[CLOUD_ENGINE] == "api_module"
        assert routing.get_engine_module("api", _state("api_module")) is not None

    @pytest.mark.parametrize("asked", ["ollama", "mlx", "llama_cpp", "llama.cpp", None, "", "auto", "unknown"])
    def test_a_local_or_unspecified_request_never_lists_the_api_even_when_it_is_loaded(self, asked):
        state = _state("mlx_module", "llama_cpp_module", "ollama_module", "api_module")
        for cloud_ok in (False, True):
            cascade = routing.resolve_engine_cascade(asked, state, cloud_ok=cloud_ok)
            assert "api" not in cascade
            assert "api" not in [name for name, _ in routing.iter_live_engines(cascade, state)]

    def test_when_every_local_engine_is_down_the_api_does_not_take_over(self):
        state = _state("api_module")
        assert routing.resolve_engine_cascade("ollama", state, cloud_ok=True) == []
        assert routing.resolve_engine_cascade(None, state, cloud_ok=True) == []
        assert routing._resolve_engine(None, state) == ("ollama", None), "the terminal answer stays the local one"

    def test_a_preference_read_from_the_environment_is_not_a_request_for_the_api(self, monkeypatch):
        from core import runtime_state
        state = _state("ollama_module", "api_module")
        monkeypatch.setenv("NEXE_MODEL_ENGINE", "api")
        assert routing.resolve_engine_cascade(None, state, cloud_ok=True) == ["ollama"]
        runtime_state.set_override("NEXE_MODEL_ENGINE", "api")
        assert routing.resolve_engine_cascade("auto", state, cloud_ok=True) == ["ollama"]
        assert routing._resolve_engine(None, state)[0] == "ollama"

    def test_an_explicit_request_without_the_gate_gets_nothing_not_a_local_engine(self):
        state = _state("ollama_module", "api_module")
        assert routing.resolve_engine_cascade("api", state) == []
        assert routing.resolve_engine_cascade("api", state, cloud_ok=False) == []
        assert routing.resolve_engine_cascade(" API ", state) == []

    def test_an_explicit_request_past_the_gate_gets_the_api_alone_no_local_fallback(self):
        state = _state("mlx_module", "llama_cpp_module", "ollama_module", "api_module")
        assert routing.resolve_engine_cascade("api", state, cloud_ok=True) == ["api"]
        assert routing.resolve_engine_cascade("API ", state, cloud_ok=True) == ["api"]

    def test_the_api_is_not_a_candidate_when_its_module_is_not_loaded(self):
        assert routing.resolve_engine_cascade("api", _state("ollama_module"), cloud_ok=True) == []

    def test_live_candidates_never_returns_the_api_without_the_gate(self):
        from core.turn.engine_claim import live_candidates
        state = _state("ollama_module", "api_module")
        assert [n for n, _ in live_candidates("ollama", state)] == ["ollama"]
        with pytest.raises(HTTPException) as exc:
            live_candidates("api", state)
        assert exc.value.status_code == 503
        assert [n for n, _ in live_candidates("api", state, cloud_ok=True)] == ["api"]

    def test_a_resolver_that_was_not_told_the_gate_passed_refuses_the_api_instead_of_answering_with_another_engine(self):
        state = _state("ollama_module", "api_module")
        for asked in ("api", "API", " api"):
            with pytest.raises(HTTPException) as exc:
                routing._resolve_engine(asked, state)
            assert exc.value.status_code == 400 and "cloud gate" in exc.value.detail

    def test_status_requires_the_module_only_when_it_is_the_configured_engine(self):
        from core.endpoints.root import _required_modules_from_config
        enabled = {"plugins": {"modules": {"enabled": ["security", "ollama_module", "api_module"]}}}
        assert "api_module" not in _required_modules_from_config(enabled)
        chosen = {"plugins": {"modules": {"enabled": ["security"]}, "models": {"preferred_engine": "api"}}}
        assert "api_module" in _required_modules_from_config(chosen)


# -------------------------------------------------------------- the curated text

class TestCuratedErrorText:
    def test_an_error_with_its_own_sentence_says_it_in_the_users_language(self):
        from core.turn.errors import curated_error_text

        class Own(Exception):
            def curated_text(self, lang):
                return f"own-{lang}"
        assert curated_error_text(Own("secret path /x"), "es") == "own-es"
        assert curated_error_text(Own(), None) == "own-ca"

    def test_every_other_error_keeps_the_generic_sentence_and_never_its_own_words(self):
        from core.turn.errors import curated_error_text
        text = curated_error_text(RuntimeError("secret path /x"), "en")
        assert "secret" not in text and "error occurred" in text
