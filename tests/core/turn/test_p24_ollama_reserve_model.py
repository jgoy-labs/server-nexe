"""P2-4 (C4.8 B2/D1-x): the model Ollama answers with as a fallback is its own,
said in words — never a default meant for another engine, never one picked
from its tag list. Without one, Ollama is no fallback: the doors skip it.

Outside the turn lab on purpose: its conftest makes Ollama the configured
engine with an Ollama default model, the one case where that default counts.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import runtime_state
from core.endpoints.chat_engines._common import no_model_of_its_own
from core.endpoints.chat_engines.ollama import ollama_reserve_model

STATE = SimpleNamespace(config={})


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    """What the selector left in `runtime_state` by another test is not this one's."""
    monkeypatch.setattr(runtime_state, "get_override", lambda key: None)
    for key in ("NEXE_OLLAMA_MODEL", "NEXE_MODEL_ENGINE", "NEXE_DEFAULT_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_its_own_model_said_in_words(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "Qwen3.5-9B-MLX-4bit")
    assert ollama_reserve_model(STATE) == "qwen3.5:4b"
    assert not no_model_of_its_own("ollama", STATE)


def test_a_default_model_meant_for_another_engine_is_not_ollamas(monkeypatch):
    """The DEV case of 07/10: MLX configured, its model as the default, no
    NEXE_OLLAMA_MODEL — Ollama used to be asked for the MLX id and pass over."""
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "mlx")
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "Qwen3.5-9B-MLX-4bit")
    assert ollama_reserve_model(STATE) is None
    assert no_model_of_its_own("ollama", STATE)


def test_the_default_model_counts_when_ollama_is_the_configured_engine(monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "ollama")
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
    assert ollama_reserve_model(STATE) == "llama3.2:3b"
    monkeypatch.setenv("NEXE_DEFAULT_MODEL", "https://huggingface.co/some/repo")
    assert ollama_reserve_model(STATE) is None, "a URL is not an Ollama tag"


def test_nothing_said_is_no_model_and_no_fallback():
    assert ollama_reserve_model(STATE) is None
    assert no_model_of_its_own("ollama", STATE)
    assert not no_model_of_its_own("mlx", STATE) and not no_model_of_its_own("llama_cpp", STATE)
