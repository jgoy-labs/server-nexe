"""
────────────────────────────────────
Server Nexe
Location: tests/test_unpinned_consent.py
Description: ADR B046b — the explicit-consent gate that replaces the silent
             fail-open for MLX/GGUF artefacts with no integrity pin. Never
             installs an unpinned weight silently: env opt-in, interactive
             prompt, or abort.
────────────────────────────────────
"""

from __future__ import annotations

import pytest

from installer.download_verify import (
    UnpinnedModelError,
    consent_for_unpinned,
)


def test_env_opt_in_allows(monkeypatch):
    monkeypatch.setenv("NEXE_ALLOW_UNPINNED", "1")
    assert consent_for_unpinned("mlx", "x/y", isatty=False) is True


@pytest.mark.parametrize("val", ["true", "YES", "1"])
def test_env_opt_in_truthy_variants(monkeypatch, val):
    monkeypatch.setenv("NEXE_ALLOW_UNPINNED", val)
    assert consent_for_unpinned("gguf", "x", isatty=False) is True


def test_interactive_yes_allows(monkeypatch):
    monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
    assert consent_for_unpinned(
        "mlx", "x/y", isatty=True, prompt=lambda _: "y") is True


def test_interactive_no_aborts(monkeypatch):
    monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
    with pytest.raises(UnpinnedModelError, match="declined"):
        consent_for_unpinned("mlx", "x/y", isatty=True, prompt=lambda _: "n")


def test_interactive_empty_default_aborts(monkeypatch):
    """Default (just Enter) is No — fail-closed."""
    monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
    with pytest.raises(UnpinnedModelError):
        consent_for_unpinned("gguf", "x", isatty=True, prompt=lambda _: "")


def test_non_interactive_without_optin_aborts(monkeypatch):
    """Headless without the env opt-in must abort, never install silently."""
    monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
    with pytest.raises(UnpinnedModelError, match="no interactive"):
        consent_for_unpinned("mlx", "x/y", isatty=False)
