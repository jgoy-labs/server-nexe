"""F5.4 Fase 4b — tests for the optional Hugging Face token persisted to
the macOS Keychain via the ``keyring`` package.

Contract:
- The token is NEVER written to onboarding.json (only ``has_token: bool``).
- ``apply_to_env`` injects ``HF_TOKEN`` from the Keychain at startup.
- v1 onboarding files (pre-has_token) still load: ``has_token`` defaults False.
- Failures in keyring (not installed, backend down, sandbox denial) DO NOT
  block the wizard or the sidecar startup — they fall back silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def isolated_state_file(tmp_path, monkeypatch):
    """Redirect OnboardingState file to a tmp dir to avoid touching real state."""
    monkeypatch.setenv("NEXE_DATA_DIR", str(tmp_path))
    yield tmp_path / "onboarding.json"


# ──────────────────────────────────────────────────────────────────────────────
# save() stores token in keychain, not on disk
# ──────────────────────────────────────────────────────────────────────────────


class TestOnboardingStateSaveWithToken:
    def test_save_with_token_writes_keychain_not_disk(self, isolated_state_file):
        from core.onboarding_state import OnboardingState, _KEYCHAIN_SERVICE, _KEYCHAIN_USER

        fake_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            state = OnboardingState.save(
                engine="mlx",
                model_id="ns/m",
                model_path=str(isolated_state_file.parent / "m"),
                hf_token="hf_secret_123",
            )

        # has_token=True at the state object
        assert state.has_token is True
        # Token stored in keychain via keyring.set_password
        fake_keyring.set_password.assert_called_once_with(
            _KEYCHAIN_SERVICE, _KEYCHAIN_USER, "hf_secret_123"
        )
        # And NOT on disk
        on_disk = json.loads(isolated_state_file.read_text())
        assert "hf_token" not in on_disk
        assert on_disk.get("has_token") is True

    def test_save_without_token_marks_has_token_false(self, isolated_state_file):
        from core.onboarding_state import OnboardingState
        state = OnboardingState.save(
            engine="mlx",
            model_id="ns/m",
            model_path=str(isolated_state_file.parent / "m"),
        )
        assert state.has_token is False
        on_disk = json.loads(isolated_state_file.read_text())
        assert on_disk.get("has_token") is False

    def test_save_when_keyring_unavailable_falls_back_gracefully(
        self, isolated_state_file
    ):
        """ImportError or backend failure must NOT block wizard finalize."""
        from core.onboarding_state import OnboardingState

        # Simulate keyring.set_password raising (e.g. user denies prompt)
        fake_keyring = MagicMock()
        fake_keyring.set_password.side_effect = RuntimeError("user denied keychain access")
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            state = OnboardingState.save(
                engine="mlx",
                model_id="ns/m",
                model_path=str(isolated_state_file.parent / "m"),
                hf_token="hf_secret_123",
            )

        # has_token must be False because the keyring write failed
        assert state.has_token is False
        on_disk = json.loads(isolated_state_file.read_text())
        assert on_disk.get("has_token") is False


# ──────────────────────────────────────────────────────────────────────────────
# apply_to_env reads token from keychain when has_token=True
# ──────────────────────────────────────────────────────────────────────────────


class TestOnboardingStateApplyToEnvHfToken:
    def test_apply_to_env_with_has_token_sets_HF_TOKEN(
        self, isolated_state_file, monkeypatch
    ):
        from core.onboarding_state import OnboardingState

        monkeypatch.delenv("HF_TOKEN", raising=False)

        fake_keyring = MagicMock()
        fake_keyring.get_password.return_value = "hf_from_keychain_xyz"
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            state = OnboardingState(
                version=2,
                engine="mlx",
                model_id="ns/m",
                model_path="/tmp/m",
                completed_at="2026-05-19T22:00:00+00:00",
                has_token=True,
            )
            state.apply_to_env()

        import os
        assert os.environ.get("HF_TOKEN") == "hf_from_keychain_xyz"
        monkeypatch.delenv("HF_TOKEN", raising=False)

    def test_apply_to_env_with_has_token_false_does_not_set_HF_TOKEN(
        self, isolated_state_file, monkeypatch
    ):
        from core.onboarding_state import OnboardingState

        monkeypatch.delenv("HF_TOKEN", raising=False)
        # keyring must NOT be queried when has_token=False
        fake_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            state = OnboardingState(
                version=2,
                engine="mlx",
                model_id="ns/m",
                model_path="/tmp/m",
                completed_at="2026-05-19T22:00:00+00:00",
                has_token=False,
            )
            state.apply_to_env()

        import os
        assert "HF_TOKEN" not in os.environ
        fake_keyring.get_password.assert_not_called()

    def test_apply_to_env_has_token_but_keychain_empty_does_not_crash(
        self, isolated_state_file, monkeypatch
    ):
        """If the user deleted the keychain entry manually, apply_to_env
        must log a warning and continue without HF_TOKEN."""
        from core.onboarding_state import OnboardingState

        monkeypatch.delenv("HF_TOKEN", raising=False)
        fake_keyring = MagicMock()
        fake_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            state = OnboardingState(
                version=2,
                engine="mlx",
                model_id="ns/m",
                model_path="/tmp/m",
                completed_at="2026-05-19T22:00:00+00:00",
                has_token=True,
            )
            state.apply_to_env()

        import os
        assert "HF_TOKEN" not in os.environ


# ──────────────────────────────────────────────────────────────────────────────
# Backwards compatibility: v1 schema (pre-has_token) still loads
# ──────────────────────────────────────────────────────────────────────────────


class TestOnboardingStateV1Compatibility:
    def test_v1_schema_file_loads_with_has_token_false(self, isolated_state_file):
        from core.onboarding_state import OnboardingState
        # Write a v1-shape file (no has_token, version=1)
        isolated_state_file.parent.mkdir(parents=True, exist_ok=True)
        isolated_state_file.write_text(json.dumps({
            "version": 1,
            "engine": "mlx",
            "model_id": "ns/legacy",
            "model_path": "/tmp/legacy",
            "completed_at": "2026-05-18T10:00:00+00:00",
        }))
        state = OnboardingState.load()
        assert state is not None
        assert state.engine == "mlx"
        assert state.has_token is False
        # The in-memory state is promoted to v2 schema
        assert state.version == 2

    def test_unknown_schema_version_still_returns_none(self, isolated_state_file):
        from core.onboarding_state import OnboardingState
        isolated_state_file.parent.mkdir(parents=True, exist_ok=True)
        isolated_state_file.write_text(json.dumps({
            "version": 999,
            "engine": "mlx",
            "model_id": "ns/m",
            "model_path": "/tmp/m",
            "completed_at": "2026-05-18T10:00:00+00:00",
        }))
        assert OnboardingState.load() is None


# ──────────────────────────────────────────────────────────────────────────────
# clear_hf_token_from_keychain helper
# ──────────────────────────────────────────────────────────────────────────────


class TestSaveSentinelPreservesHasToken:
    """save() without hf_token must preserve the existing
    has_token flag (read from previous state). Only explicit hf_token=None
    clears the token; hf_token="" is treated as the sentinel for safety."""

    def test_save_without_hf_token_preserves_has_token_true(self, isolated_state_file):
        from core.onboarding_state import OnboardingState

        # First save with a token → has_token=True
        fake_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            OnboardingState.save(
                engine="mlx",
                model_id="ns/m1",
                model_path=str(isolated_state_file.parent / "m1"),
                hf_token="hf_secret_a",
            )
        # Second save WITHOUT hf_token (e.g. user just re-ran wizard for
        # model selection) → must preserve has_token=True
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            state = OnboardingState.save(
                engine="ollama",
                model_id="gemma3:4b",
                model_path="gemma3:4b",
                # hf_token not provided — sentinel kicks in
            )
        assert state.has_token is True, (
            "save() without hf_token argument must preserve previous "
            "has_token flag. Otherwise re-running the wizard for model "
            "change silently breaks the HF Token integration."
        )
        on_disk = json.loads(isolated_state_file.read_text())
        assert on_disk.get("has_token") is True

    def test_save_with_empty_string_token_preserves_has_token(self, isolated_state_file):
        """Empty string is a wizard form artefact (user did not type
        anything in the optional field), NOT a deliberate clear."""
        from core.onboarding_state import OnboardingState
        fake_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            OnboardingState.save(
                engine="mlx", model_id="ns/m", model_path="/tmp/m",
                hf_token="hf_secret_a",
            )
            state = OnboardingState.save(
                engine="mlx", model_id="ns/m", model_path="/tmp/m",
                hf_token="",  # empty string from form
            )
        assert state.has_token is True

    def test_save_with_explicit_none_clears_keychain(self, isolated_state_file):
        """Passing hf_token=None explicitly DOES clear the token (delete
        keychain entry + has_token=False) so a future "Disconnect HF"
        button has a backend hook."""
        from core.onboarding_state import OnboardingState
        fake_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            OnboardingState.save(
                engine="mlx", model_id="ns/m", model_path="/tmp/m",
                hf_token="hf_secret_a",
            )
            state = OnboardingState.save(
                engine="mlx", model_id="ns/m", model_path="/tmp/m",
                hf_token=None,  # explicit clear
            )
        assert state.has_token is False
        fake_keyring.delete_password.assert_called_once()


class TestClearHfTokenFromKeychain:
    def test_clear_calls_delete_password(self):
        from core.onboarding_state import (
            clear_hf_token_from_keychain,
            _KEYCHAIN_SERVICE,
            _KEYCHAIN_USER,
        )
        fake_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            ok = clear_hf_token_from_keychain()
        assert ok is True
        fake_keyring.delete_password.assert_called_once_with(
            _KEYCHAIN_SERVICE, _KEYCHAIN_USER
        )

    def test_clear_returns_false_on_failure(self):
        from core.onboarding_state import clear_hf_token_from_keychain
        fake_keyring = MagicMock()
        fake_keyring.delete_password.side_effect = RuntimeError("not found")
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            assert clear_hf_token_from_keychain() is False
