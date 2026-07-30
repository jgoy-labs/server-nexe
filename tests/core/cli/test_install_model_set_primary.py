"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/cli/test_install_model_set_primary.py
Description: Teeth for the set-as-primary path of `nexe model install`
             (helper _maybe_set_primary extracted in the CCN refactor).
             Before this file the confirm+write path had ZERO direct
             coverage: breaking the config write would fail no test.
             Covers: (a) confirmed install writes plugins.models.primary
             atomically, (b) declining leaves the file byte-identical,
             (c) a failed pull never prompts (short-circuit).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import subprocess
import tomllib
from types import SimpleNamespace

import pytest
import tomli_w
from click.testing import CliRunner

from core.paths.constants import BASE_CONFIG_RELATIVE

_BASE_CONFIG = {
    "plugins": {
        "models": {"primary": "old-model:latest", "preferred_engine": "ollama"},
    },
}


@pytest.fixture()
def fake_repo(tmp_path, monkeypatch):
    """Repo root fals amb un server.toml mínim + registry/ollama mocks."""
    config_path = tmp_path / BASE_CONFIG_RELATIVE
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(tomli_w.dumps(_BASE_CONFIG).encode())

    import core.cli.cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_repo_root", lambda: tmp_path)
    # Registry: model ollama-only, petit
    entry = SimpleNamespace(
        short_name="fake-model",
        size_gb=1,
        ollama_tag="fake-model:latest",
        mlx_hf_id=None,
    )
    import personality.models.registry as registry_mod

    monkeypatch.setattr(registry_mod, "get_model_entry", lambda name: entry)
    # Gate #833: API llesta sense tocar cap daemon real
    monkeypatch.setattr(cli_mod, "_cli_ensure_ollama_ready", lambda: True)
    import plugins.ollama_module.core.client as client_mod

    monkeypatch.setattr(client_mod, "resolve_base_url", lambda: "http://127.0.0.1:11434")
    return tmp_path, config_path


def _invoke_install(monkeypatch, *, pull_ok=True, confirm=None):
    from core.cli.cli import install_model

    calls = {"pull": 0, "confirm": 0}

    def fake_run(cmd, check=False, env=None, **kwargs):
        calls["pull"] += 1
        if not pull_ok:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    if confirm is None:
        # El camí que es testeja NO hauria de preguntar mai
        def fail_confirm(*args, **kwargs):
            calls["confirm"] += 1
            raise AssertionError("click.confirm cridat quan no tocava")
    else:
        def fail_confirm(*args, **kwargs):
            calls["confirm"] += 1
            return confirm

    import click

    monkeypatch.setattr(click, "confirm", fail_confirm)
    result = CliRunner().invoke(install_model, ["fake-model"], standalone_mode=False)
    return result, calls


class TestMaybeSetPrimary:
    def test_confirmed_pull_writes_primary_atomically(self, fake_repo, monkeypatch):
        """Pull OK + confirm=True → primary reescrit via atomic_toml_write (.bak present)."""
        _, config_path = fake_repo
        result, calls = _invoke_install(monkeypatch, pull_ok=True, confirm=True)

        assert result.exception is None, result.output
        assert calls["pull"] == 1 and calls["confirm"] == 1
        config = tomllib.loads(config_path.read_text())
        assert config["plugins"]["models"]["primary"] == "fake-model:latest"
        # atomic_toml_write deixa el backup rotatiu al costat (#834)
        assert config_path.with_suffix(".toml.bak").exists()

    def test_declined_confirm_leaves_config_untouched(self, fake_repo, monkeypatch):
        """Pull OK + confirm=False → el fitxer queda byte-idèntic."""
        _, config_path = fake_repo
        before = config_path.read_bytes()
        result, calls = _invoke_install(monkeypatch, pull_ok=True, confirm=False)

        assert result.exception is None, result.output
        assert calls["confirm"] == 1
        assert config_path.read_bytes() == before

    def test_failed_pull_never_prompts(self, fake_repo, monkeypatch):
        """Pull KO → short-circuit: ni confirm ni escriptura (mutation control)."""
        _, config_path = fake_repo
        before = config_path.read_bytes()
        result, calls = _invoke_install(monkeypatch, pull_ok=False, confirm=None)

        assert result.exception is None, result.output
        assert calls["confirm"] == 0
        assert config_path.read_bytes() == before
