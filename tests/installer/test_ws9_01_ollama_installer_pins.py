"""
WS9-01 — Ollama installer binaries are integrity-pinned by default.

Resolution order: operator env override → embedded versioned pin from
installer/provider_pins.json (section ollama_installer) → fail closed
(NEXE_ALLOW_UNPINNED is the explicit escape). Never a silent fail-open.
"""

import json
from pathlib import Path

import pytest

from installer.installer_ollama_install import (
    _resolve_ollama_pin,
    _unpinned_ollama_allowed,
)

PINS_PATH = Path(__file__).resolve().parents[2] / "installer" / "provider_pins.json"


class TestResolveOllamaPin:
    def test_env_override_wins_and_keeps_default_url(self, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_MACOS_SHA256", "AB" * 32)
        sha, url, version = _resolve_ollama_pin("darwin")
        assert sha == "ab" * 32  # normalized lowercase
        assert url is None       # operator pin applies to the default URL
        assert version is None

    @pytest.mark.parametrize("key", ["darwin", "windows_arm64", "windows_amd64", "linux_install_sh"])
    def test_embedded_pin_carries_versioned_url(self, monkeypatch, key):
        monkeypatch.delenv("NEXE_OLLAMA_MACOS_SHA256", raising=False)
        monkeypatch.delenv("NEXE_OLLAMA_WINDOWS_SHA256", raising=False)
        monkeypatch.delenv("NEXE_OLLAMA_INSTALL_SHA256", raising=False)
        sha, url, version = _resolve_ollama_pin(key)
        assert sha and len(sha) == 64, f"missing embedded pin for {key}"
        assert url and ("github.com/ollama/ollama" in url or "githubusercontent.com/ollama" in url)
        assert version and version.startswith("v")
        # the URL must be VERSIONED (no mutable 'latest'), so upstream
        # releases cannot drift under the pin
        assert version in url

    def test_pins_file_consistency(self):
        """The embedded pins actually live in provider_pins.json."""
        section = json.loads(PINS_PATH.read_text())["ollama_installer"]
        for key in ("darwin", "windows_arm64", "windows_amd64", "linux_install_sh"):
            assert len(section[key]["sha256"]) == 64
            assert section["version"] in section[key]["url"]

    def test_missing_pin_returns_none_triplet(self, monkeypatch, tmp_path):
        monkeypatch.delenv("NEXE_OLLAMA_MACOS_SHA256", raising=False)
        # point the module at a pins file without the section
        import installer.installer_ollama_install as mod
        fake = tmp_path / "provider_pins.json"
        fake.write_text("{}")
        monkeypatch.setattr(mod, "__file__", str(tmp_path / "installer_ollama_install.py"))
        sha, url, version = _resolve_ollama_pin("darwin")
        assert (sha, url, version) == (None, None, None)


class TestUnpinnedGate:
    def test_refuses_without_opt_in(self, monkeypatch):
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        assert _unpinned_ollama_allowed("Ollama-darwin.zip") is False

    def test_allows_with_explicit_opt_in(self, monkeypatch):
        monkeypatch.setenv("NEXE_ALLOW_UNPINNED", "1")
        assert _unpinned_ollama_allowed("Ollama-darwin.zip") is True

    @pytest.mark.parametrize("value", ["0", "", "no", "false"])
    def test_non_truthy_opt_in_refuses(self, monkeypatch, value):
        monkeypatch.setenv("NEXE_ALLOW_UNPINNED", value)
        assert _unpinned_ollama_allowed("x") is False
