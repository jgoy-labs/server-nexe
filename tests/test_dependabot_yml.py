"""
────────────────────────────────────
Server Nexe
Location: tests/test_dependabot_yml.py
Description: Anti-regression for .github/dependabot.yml.

             Twice (PR #49 on 2026-07-30, PR #53 on 2026-08-19) Dependabot
             bundled two pins we cannot lift into a "safe-patches" PR:

             * transformers 5.12.1 → 5.15.0, which breaks mlx-lm 0.31.3
               at import (key.__module__ unconditional in 5.13+).
             * cryptography 46.0.3 → 50.0.0 on Windows ARM64, which has
               no win_arm64 wheel after 46.0.3. Dependabot treats every
               requirements*.txt in the directory as one manifest and
               copies the base pin onto Windows.

             An ignore for those deps was noted on 2026-07-30 and never
             applied to this file, so the PR came back. These tests lock
             the ignore/exclude entries so "fixed in theory" cannot happen
             a third time.

             Pure YAML parse — no network.
────────────────────────────────────
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
YML = REPO / ".github" / "dependabot.yml"


def _pip_update() -> dict:
    cfg = yaml.safe_load(YML.read_text(encoding="utf-8"))
    assert cfg and cfg.get("updates"), f"{YML} missing updates:"
    pip = next(
        (u for u in cfg["updates"] if u.get("package-ecosystem") == "pip"),
        None,
    )
    assert pip is not None, "pip ecosystem missing from dependabot.yml"
    return pip


def _ignored(name: str) -> dict | None:
    for entry in _pip_update().get("ignore") or []:
        if entry.get("dependency-name") == name:
            return entry
    return None


def _safe_patch_excludes() -> list[str]:
    groups = _pip_update().get("groups") or {}
    safe = groups.get("safe-patches") or {}
    return list(safe.get("exclude-patterns") or [])


def test_transformers_ignored_from_5_13() -> None:
    """transformers>=5.13 must not get a Dependabot PR.

    5.13+ breaks mlx-lm 0.31.3 at import. Pin is 5.12.1 in
    requirements-macos.txt (see test_transformers_pin_consistency.py).
    """
    entry = _ignored("transformers")
    assert entry is not None, (
        "dependabot.yml must ignore transformers>=5.13. Without this, "
        "safe-patches regenerates PR #49/#53 (5.12.1→5.15.0) every week. "
        "The CI tests catch the merge; they do not stop the PR."
    )
    versions = entry.get("versions") or []
    assert any("5.13" in v and ">" in v for v in versions), (
        f"transformers ignore must cover >=5.13, got {versions!r}"
    )


def test_cryptography_updates_are_ignored() -> None:
    """Dependabot must not bump cryptography at all.

    It cannot bump Windows independently: one directory, one PR, and it
    copies requirements.txt (50.0.0) onto requirements-windows.txt
    (must stay 46.0.3 — last win_arm64 wheel). Base bumps are manual
    when OSV/pip-audit go red. GitHub alerts stay on.
    """
    entry = _ignored("cryptography")
    assert entry is not None, (
        "dependabot.yml must ignore cryptography. Dependabot copies the "
        "base pin onto Windows ARM64 and there is no win_arm64 wheel "
        "after 46.0.3 (see test_base_cryptography_is_50_windows_stays_46)."
    )
    versions = entry.get("versions")
    assert not versions, (
        "cryptography ignore must be unconstrained (all updates). A "
        f"partial range still lets Dependabot retarget Windows: {versions!r}"
    )


def test_mlx_vlm_ignored_from_0_5() -> None:
    """mlx-vlm>=0.5 pulls transformers past 5.12.1 (PR #41)."""
    entry = _ignored("mlx-vlm")
    assert entry is not None, (
        "dependabot.yml must ignore mlx-vlm>=0.5. Bumping it alone "
        "reopens the transformers 5.13 crash on Apple Silicon."
    )
    versions = entry.get("versions") or []
    assert any("0.5" in v and ">" in v for v in versions), (
        f"mlx-vlm ignore must cover >=0.5, got {versions!r}"
    )


def test_safe_patches_does_not_swallow_web_frameworks() -> None:
    """FastAPI/Starlette minor jumps are not 'safe patches'.

    PR #53 bundled fastapi 0.136.3→0.141.1 and starlette 1.3.1→1.6.0.
    test_api_info_summary_does_not_promise_exhaustiveness then raised
    StopIteration. They stay as individual PRs.
    """
    excludes = _safe_patch_excludes()
    assert any(p.startswith("fastapi") for p in excludes), (
        "safe-patches must exclude fastapi* — 0.136→0.141 is not a patch"
    )
    assert any(p.startswith("starlette") for p in excludes), (
        "safe-patches must exclude starlette* — 1.3→1.6 is not a patch"
    )


def test_safe_patches_still_excludes_cryptography_and_transformers() -> None:
    """Belt: if the ignore is deleted, they still must not join the group."""
    excludes = _safe_patch_excludes()
    assert any(p.startswith("cryptography") for p in excludes), (
        "safe-patches must exclude cryptography even with the ignore in place"
    )
    assert any(p.startswith("transformers") for p in excludes), (
        "safe-patches must exclude transformers even with the ignore in place"
    )
