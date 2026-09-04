"""
────────────────────────────────────
Server Nexe
Location: tests/test_1002_dead_model_config_keys.py
Description: #1002 — `[plugins.models].max_tokens` and `.context_window` were
             shipped in server.toml, written back by the model selector, and
             read by nobody.

             The window has come from the live engine since #965
             (`get_context_window()`, resolved by
             `core/context_window.py::resolve_context_window`), and the answer
             ceiling from the engine's own configuration. Someone who edited
             either key got exactly nothing, in silence — with a validator that
             type-checked `max_tokens`, which stated the opposite.

             Decision (Jordi): delete them, with the warning that
             `[security.encryption]` already carries for the same kind of dead
             key. Not wire them up.

             What is NOT deleted: `ModelProfile.max_tokens` and
             `.context_window`. They describe a hardware tier and the CLI
             prints them (`core/cli/cli.py:371` reads the profile object, never
             the TOML). Only the write-back into server.toml is gone.

             Inherited files are tolerated, never rejected: the keys shipped as
             defaults, so every installation made before this has them on disk.
             They now produce a validation WARNING that names them.
────────────────────────────────────
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.modules.config_validator import ConfigValidator

ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = ROOT / "personality" / "server.toml"

DEAD_KEYS = ("max_tokens", "context_window")

BASE_CONFIG = """
[meta]
version = "0.8"
environment = "development"

[core]
[core.server]
host = "127.0.0.1"
port = 9119

[personality]
[personality.orchestrator]
modules_path = "plugins"

[plugins]
[plugins.models]
primary = "llama3.2"
{extra}
[storage]
[storage.logging]
level = "INFO"
"""


def _write(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "server.toml"
    path.write_text(BASE_CONFIG.format(extra=extra), encoding="utf-8")
    return path


class TestShippedConfig:

    def test_the_shipped_toml_no_longer_carries_the_dead_keys(self):
        """Parsed, not grepped — a commented-out key must still count as gone."""
        config = tomllib.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        models = config["plugins"]["models"]
        for key in DEAD_KEYS:
            assert key not in models, (
                f"[plugins.models].{key} is back in the shipped server.toml. "
                "Nothing reads it; the window comes from the engine (#965)."
            )

    def test_the_keys_that_do_govern_something_are_still_there(self):
        """Mutation control: deleting the whole section would pass the test
        above and break the product."""
        config = tomllib.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        models = config["plugins"]["models"]
        for key in ("preferred_engine", "primary", "secondary", "embedding", "temperature"):
            assert key in models, f"[plugins.models].{key} is read and must stay"

    def test_the_shipped_config_says_nothing_about_the_removed_keys(self):
        """Neither an error nor a warning: they are gone, so there is nothing
        to report.

        Deliberately NOT `assert result.valid`. The shipped server.toml has no
        `[storage]` section while `ConfigValidator.REQUIRED_SECTIONS` demands
        one, so `validate()` has always called the product's own config
        invalid — true at af66d10e too, unrelated to this finding, and filed
        rather than fixed under cover of it.
        """
        result = ConfigValidator().validate(SHIPPED_CONFIG)
        for key in DEAD_KEYS:
            assert not any(key in e for e in result.errors), result.errors
            assert not any(key in w for w in result.warnings), result.warnings

    def test_the_only_complaints_about_the_shipped_config_are_the_old_ones(self):
        """Pins the pre-existing gap so it cannot grow silently while nobody
        is asserting `valid` on this file."""
        result = ConfigValidator().validate(SHIPPED_CONFIG)
        assert result.errors == [
            "Missing required section: [storage]",
            "Missing required key: storage.logging.level",
        ], (
            "the shipped server.toml gained or lost a validation error — if it "
            f"is now clean, tighten this test: {result.errors}"
        )


class TestInheritedConfigsAreTolerated:
    """Every installation made before this has the keys on disk."""

    def test_an_inherited_key_is_a_warning_and_not_an_error(self, tmp_path):
        result = ConfigValidator().validate(
            _write(tmp_path, "max_tokens = 8192\ncontext_window = 32768\n")
        )
        assert result.valid, f"an old server.toml must keep loading: {result.errors}"
        assert not result.errors
        warnings = " | ".join(result.warnings)
        for key in DEAD_KEYS:
            assert key in warnings, f"{key} was tolerated in silence — that is the finding"

    def test_a_nonsense_inherited_value_is_still_only_a_warning(self, tmp_path):
        """`max_tokens = -1` used to be an error. Type-checking a key states
        that the key is read; this one never was."""
        result = ConfigValidator().validate(_write(tmp_path, "max_tokens = -1\n"))
        assert result.valid, result.errors
        assert any("max_tokens" in w for w in result.warnings)

    def test_a_clean_config_warns_about_neither(self, tmp_path):
        result = ConfigValidator().validate(_write(tmp_path))
        assert not any("max_tokens" in w or "context_window" in w for w in result.warnings)

    def test_validate_section_reports_it_too(self, tmp_path):
        """`validate_section('plugins')` is a separate path through the same
        rules and used to skip every warning."""
        path = _write(tmp_path, "context_window = 32768\n")
        result = ConfigValidator().validate_section(path, "plugins")
        assert result.valid
        assert any("context_window" in w for w in result.warnings)

    @pytest.mark.parametrize("broken", ["plugins = 3", None])
    def test_a_malformed_plugins_section_does_not_crash_the_check(self, broken):
        """The warning path runs on whatever tomllib produced, including shapes
        the rest of the validator has already rejected."""
        config = {"plugins": broken} if broken is None else {"plugins": 3}
        assert ConfigValidator()._validate_deprecated_keys(config) == []
        assert ConfigValidator()._validate_deprecated_keys({"plugins": {"models": 7}}) == []


class TestSelectorStopsWritingThem:

    def _applied(self):
        from personality.models.profiles import PROFILES, HardwareTier
        from personality.models.selector import ModelSelector
        selector = ModelSelector()
        profile = PROFILES[HardwareTier.CONSUMER]
        return selector.apply_to_config({}, profile), profile

    def test_apply_to_config_writes_neither_key(self):
        config, _ = self._applied()
        models = config["plugins"]["models"]
        for key in DEAD_KEYS:
            assert key not in models, (
                f"apply_to_config put {key} back into server.toml — `nexe models "
                "--apply` would re-create the dead key on every run"
            )

    def test_apply_to_config_still_writes_everything_that_is_read(self):
        """Mutation control for the deletion above."""
        config, profile = self._applied()
        models = config["plugins"]["models"]
        assert models["primary"] == profile.primary_model
        assert models["secondary"] == profile.secondary_model
        assert models["embedding"] == profile.embedding_model
        assert models["preferred_engine"] == profile.preferred_engine.value

    def test_the_profile_still_carries_them_for_the_cli(self):
        """`core/cli/cli.py:371` prints `profile.context_window` — the hardware
        recommendation object, not the TOML. Untouched on purpose."""
        _, profile = self._applied()
        assert isinstance(profile.context_window, int) and profile.context_window > 0
        assert isinstance(profile.max_tokens, int) and profile.max_tokens > 0


class TestNothingEverReadThem:
    """Why deleting is safe: the number the product uses comes from the engine."""

    def _state(self, window, config):
        module = SimpleNamespace(get_context_window=lambda: window)
        return SimpleNamespace(modules={"mlx_module": module}, config=config)

    def test_the_window_comes_from_the_engine_not_from_the_toml(self):
        from core.endpoints.chat import get_effective_context_window
        state = self._state(4096, {"plugins": {"models": {"context_window": 999999}}})
        assert get_effective_context_window("mlx", state) == 4096

    def test_with_no_engine_it_falls_back_to_the_env_default_not_the_toml(self):
        from core.endpoints.chat_sanitization import DEFAULT_CONTEXT_WINDOW
        from core.endpoints.chat import get_effective_context_window
        state = SimpleNamespace(
            modules={}, config={"plugins": {"models": {"context_window": 999999}}},
        )
        assert get_effective_context_window("mlx", state) == DEFAULT_CONTEXT_WINDOW
        assert get_effective_context_window("mlx", state) != 999999
