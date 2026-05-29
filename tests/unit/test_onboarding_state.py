"""Unit tests for core.onboarding_state (F5.3.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.onboarding_state import (
    SCHEMA_VERSION,
    OnboardingState,
)


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin NEXE_DATA_DIR to a tmp path so each test is isolated."""
    monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))
    return tmp_path


def test_save_and_load_roundtrip(tmp_data_dir: Path) -> None:
    """save() then load() returns an equivalent state."""
    saved = OnboardingState.save(
        engine="mlx",
        model_id="mlx-community/gemma-3-4b-it-4bit",
        model_path=str(tmp_data_dir / "models" / "gemma-3-4b-it-4bit"),
    )
    loaded = OnboardingState.load()
    assert loaded is not None
    assert loaded.engine == "mlx"
    assert loaded.model_id == "mlx-community/gemma-3-4b-it-4bit"
    assert loaded.version == SCHEMA_VERSION
    # model_path is normalized to absolute (resolve)
    assert loaded.model_path == saved.model_path
    assert Path(loaded.model_path).is_absolute()
    assert loaded.completed_at.endswith("+00:00")
    assert OnboardingState.is_completed() is True


def test_save_fsyncs_before_replace(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """save() calls os.fsync on the tmp file fd before os.replace — without it
    a power cut between rename and the OS flushing the file contents could
    leave a zero-byte onboarding.json that is_completed() would later parse
    as a completed state."""
    import core.onboarding_state as os_mod

    seen_fds: list[int] = []
    real_fsync = os.fsync

    def _spy(fd: int) -> None:
        seen_fds.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os_mod.os, "fsync", _spy)
    OnboardingState.save(
        engine="mlx",
        model_id="mlx-community/test-model",
        model_path=str(tmp_data_dir / "test-model"),
    )
    assert seen_fds, "save() must fsync the tmp file fd before os.replace"


def test_load_returns_none_when_missing(tmp_data_dir: Path) -> None:
    """load() returns None when no file exists yet."""
    assert OnboardingState.load() is None
    assert OnboardingState.is_completed() is False


def test_invalid_engine_raises(tmp_data_dir: Path) -> None:
    """save() rejects engines outside the allowlist."""
    with pytest.raises(ValueError, match="invalid engine"):
        OnboardingState.save(engine="bogus", model_id="x", model_path="/tmp/x")
    # Confirm nothing was written
    assert OnboardingState.load() is None


def test_schema_mismatch_returns_none(tmp_data_dir: Path) -> None:
    """load() returns None (with a warning) when the on-disk schema version mismatches."""
    path = tmp_data_dir / "onboarding.json"
    path.write_text(
        json.dumps(
            {
                "version": SCHEMA_VERSION + 999,
                "engine": "mlx",
                "model_id": "x",
                "model_path": "/x",
                "completed_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    assert OnboardingState.load() is None


def test_load_returns_none_when_payload_malformed(tmp_data_dir: Path) -> None:
    """load() returns None when the JSON is missing required fields."""
    path = tmp_data_dir / "onboarding.json"
    path.write_text(json.dumps({"version": SCHEMA_VERSION}), encoding="utf-8")
    assert OnboardingState.load() is None


def test_load_returns_none_when_corrupt_json(tmp_data_dir: Path) -> None:
    """load() returns None when the file is not valid JSON."""
    path = tmp_data_dir / "onboarding.json"
    path.write_text("not-a-valid-json", encoding="utf-8")
    assert OnboardingState.load() is None


def test_apply_to_env_mlx(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_to_env() sets MLX-specific env vars correctly."""
    monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    state = OnboardingState.save(
        engine="mlx",
        model_id="mlx-community/gemma-3-4b-it-4bit",
        model_path=str(tmp_data_dir / "models" / "gemma"),
    )
    state.apply_to_env()
    assert os.environ["NEXE_MLX_MODEL"].endswith("models/gemma")
    assert os.environ["NEXE_DEFAULT_MODEL"] == "mlx-community/gemma-3-4b-it-4bit"
    # routes_chat._resolve_engines accepts "mlx" (not "mlx_module")
    assert os.environ["NEXE_MODEL_ENGINE"] == "mlx"


def test_apply_to_env_ollama(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_to_env() does not set a path env for ollama, sets engine to 'ollama'."""
    monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
    monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    state = OnboardingState.save(
        engine="ollama",
        model_id="gemma3:4b",
        model_path="gemma3:4b",  # ollama: model_id IS the identifier
    )
    state.apply_to_env()
    assert "NEXE_MLX_MODEL" not in os.environ
    assert "NEXE_LLAMA_CPP_MODEL" not in os.environ
    assert os.environ["NEXE_DEFAULT_MODEL"] == "gemma3:4b"
    assert os.environ["NEXE_MODEL_ENGINE"] == "ollama"


def test_apply_to_env_gguf(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_to_env() maps gguf to llamacpp and NEXE_LLAMA_CPP_MODEL."""
    monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    state = OnboardingState.save(
        engine="gguf",
        model_id="some-org/model.gguf",
        model_path=str(tmp_data_dir / "models" / "model.gguf"),
    )
    state.apply_to_env()
    assert os.environ["NEXE_LLAMA_CPP_MODEL"].endswith("model.gguf")
    assert os.environ["NEXE_MODEL_ENGINE"] == "llamacpp"


def test_save_local_roundtrip(tmp_data_dir: Path) -> None:
    """save(engine='local') round-trips and marks onboarding complete."""
    folder = tmp_data_dir / "models-folder"
    folder.mkdir()
    OnboardingState.save(engine="local", model_id="local", model_path=str(folder))
    loaded = OnboardingState.load()
    assert loaded is not None
    assert loaded.engine == "local"
    assert OnboardingState.is_completed() is True


def test_apply_to_env_local(tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local-folder onboarding sets NEXE_STORAGE_PATH (container dir) + engine
    'auto', and does NOT set NEXE_DEFAULT_MODEL (an empty value would break the
    chat fallback) nor a per-engine model env. The chat UI selector picks the
    concrete model at runtime."""
    # apply_to_env() WRITES these directly to os.environ; seed them via
    # monkeypatch.setenv so they are guaranteed to be restored/removed at
    # teardown (delenv on a non-existent var would NOT register an undo, so
    # the value apply_to_env creates would leak and contaminate later tests
    # that read NEXE_STORAGE_PATH, e.g. _models_dir()).
    monkeypatch.setenv("NEXE_STORAGE_PATH", "__seed__")
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "__seed__")
    monkeypatch.setenv("NEXE_LANG", "__seed__")
    for var in ("NEXE_DEFAULT_MODEL", "NEXE_MLX_MODEL", "NEXE_LLAMA_CPP_MODEL"):
        monkeypatch.delenv(var, raising=False)
    folder = tmp_data_dir / "my-models"
    folder.mkdir()
    state = OnboardingState.save(
        engine="local", model_id="local", model_path=str(folder)
    )
    state.apply_to_env()
    assert os.environ["NEXE_STORAGE_PATH"] == state.model_path
    assert os.environ["NEXE_MODEL_ENGINE"] == "auto"
    assert "NEXE_DEFAULT_MODEL" not in os.environ
    assert "NEXE_MLX_MODEL" not in os.environ
    assert "NEXE_LLAMA_CPP_MODEL" not in os.environ


def test_atomic_write_no_partial_file(tmp_data_dir: Path) -> None:
    """save() leaves no stray .tmp files in the data directory."""
    OnboardingState.save(engine="ollama", model_id="gemma3:4b", model_path="gemma3:4b")
    leftovers = [p.name for p in tmp_data_dir.iterdir() if p.name != "onboarding.json"]
    assert leftovers == [], f"unexpected files left behind: {leftovers}"


def test_save_overwrites_previous_state(tmp_data_dir: Path) -> None:
    """A second save() replaces the previous state file."""
    OnboardingState.save(engine="ollama", model_id="gemma3:4b", model_path="gemma3:4b")
    OnboardingState.save(
        engine="mlx",
        model_id="mlx-community/qwen-3b",
        model_path=str(tmp_data_dir / "models" / "qwen-3b"),
    )
    loaded = OnboardingState.load()
    assert loaded is not None
    assert loaded.engine == "mlx"
    assert loaded.model_id == "mlx-community/qwen-3b"


def test_fallback_path_when_data_dir_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without NEXE_DATA_DIR, state file lives under ~/Library/Application Support."""
    monkeypatch.delenv("NEXE_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = (
        tmp_path
        / "Library"
        / "Application Support"
        / "com.nexe.app"
        / "sidecar"
        / "onboarding.json"
    )
    assert OnboardingState._state_file() == expected
