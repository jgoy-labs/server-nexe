"""pla-comportament-segons-mida-model, B: the cut between accompanied and autonomous."""
from types import SimpleNamespace

import pytest

from core.turn import model_tier as mt
from core.turn.model_size import API, UNKNOWN, ModelSize


def _size(params, active=None, source="ollama"):
    return ModelSize(params, active, source)


class TestTierOf:
    @pytest.mark.parametrize("params,expected", [
        (4.7, mt.ASSISTED), (9.65, mt.ASSISTED), (27.8, mt.ASSISTED),
        (30.0, mt.AUTONOMOUS), (31.0, mt.AUTONOMOUS), (79.7, mt.AUTONOMOUS),
    ])
    def test_the_cut_is_in_billions(self, params, expected):
        assert mt.tier_of(_size(params), below_b=30.0) == expected

    @pytest.mark.parametrize("size", [_size(4.7), _size(79.7), _size(400.0), API, UNKNOWN])
    def test_by_default_every_model_is_accompanied(self, size):
        # Live matrix 17-18/10: no model, local or API, asks reliably on its own.
        assert mt.tier_of(size) == mt.ASSISTED

    def test_an_api_is_autonomous_only_when_a_cut_is_set(self):
        assert mt.tier_of(API, below_b=30.0) == mt.AUTONOMOUS

    def test_unreadable_is_accompanied(self):
        assert mt.tier_of(UNKNOWN) == mt.ASSISTED

    def test_a_mixture_weighs_by_its_active_parameters(self):
        assert mt.tier_of(_size(35.0, active=3.0, source="name")) == mt.ASSISTED

    def test_the_cut_is_a_parameter(self):
        assert mt.tier_of(_size(9.65), below_b=8.0) == mt.AUTONOMOUS


class TestThreshold:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("NEXE_ASSISTED_BELOW_B", raising=False)
        assert mt.threshold_b({}) == mt.DEFAULT_BELOW_B

    def test_server_toml_first(self, monkeypatch):
        monkeypatch.setenv("NEXE_ASSISTED_BELOW_B", "12")
        assert mt.threshold_b({"models": {"acompanyat_per_sota_de_b": 8}}) == 8.0

    def test_environment_second(self, monkeypatch):
        monkeypatch.setenv("NEXE_ASSISTED_BELOW_B", "12")
        assert mt.threshold_b({}) == 12.0

    @pytest.mark.parametrize("bad", ["x", "0", "-5", ""])
    def test_nonsense_falls_to_the_default(self, monkeypatch, bad):
        monkeypatch.setenv("NEXE_ASSISTED_BELOW_B", bad)
        assert mt.threshold_b({"models": {"acompanyat_per_sota_de_b": "nope"}}) == mt.DEFAULT_BELOW_B


class TestResolve:
    async def test_it_is_kept_on_the_turn_for_the_log_and_the_trace(self, monkeypatch):
        async def fake(engine, model):
            return _size(9.65, source="estimated")
        monkeypatch.setattr(mt, "model_size", fake)
        monkeypatch.delenv("NEXE_ASSISTED_BELOW_B", raising=False)
        ctx = SimpleNamespace(usage={})
        assert await mt.resolve(ctx, "mlx", "Qwen3.5-9B-MLX-4bit") == mt.ASSISTED
        assert ctx.usage["model_tier"] == {
            "tier": mt.ASSISTED, "params_b": 9.65, "active_b": None, "source": "estimated", "below_b": mt.DEFAULT_BELOW_B,
        }

    async def test_worked_out_once_per_turn(self, monkeypatch):
        calls = []

        async def fake(engine, model):
            calls.append(model)
            return _size(9.65)
        monkeypatch.setattr(mt, "model_size", fake)
        ctx = SimpleNamespace(usage={})
        await mt.resolve(ctx, "ollama", "m")
        await mt.resolve(ctx, "ollama", "other")
        assert calls == ["m"]
