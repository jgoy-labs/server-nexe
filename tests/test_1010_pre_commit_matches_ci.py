"""
────────────────────────────────────
Server Nexe
Location: tests/test_1010_pre_commit_matches_ci.py
Description: `.pre-commit-config.yaml` must not drift away from the CI (#1010).

             Before #1010 the repo had no local enforcement of any kind — no
             `.git/hooks/pre-commit`, no config file. ruff and bandit were
             configured in pyproject.toml and gated in `static-analysis`, so
             the first signal that a commit was red arrived from a GitHub run
             minutes later.

             Adding a hook file is the easy half. The half that decides whether
             it is worth having is that it runs THE SAME tool versions over THE
             SAME paths as CI: a pre-commit that is green where CI is red gets
             ignored within a week, and then it is enforcement in name only.

             So these tests parse BOTH files and compare them. No version
             number is written here: hardcoding them would mean a CI bump that
             forgets the hook file still reads green, which is the exact
             divergence the gate exists to catch.

             Pure YAML/shlex parse — pre-commit itself is NOT installed or run
             (it is not a dependency of this repo, and a gate that needs an
             uninstalled tool is a gate that silently skips).
────────────────────────────────────
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = REPO / ".pre-commit-config.yaml"

# hook id -> the distribution the CI installs for it
TOOLS = {"ruff": "ruff", "bandit": "bandit"}

PIN = re.compile(r"([A-Za-z0-9_.\-]+)==([0-9][^\s\]\"']*)")


def _pre_commit() -> dict[str, Any]:
    assert PRE_COMMIT.exists(), (
        f"{PRE_COMMIT.name} is missing: nothing enforces ruff/bandit before a "
        "push, which is what #1010 is about."
    )
    cfg = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    assert isinstance(cfg, dict) and cfg.get("repos"), (
        f"{PRE_COMMIT.name} parses to {cfg!r} — it declares no `repos`, so "
        "pre-commit would run nothing at all."
    )
    return cfg


def _hooks() -> dict[str, dict[str, Any]]:
    """Every hook of the config, keyed by id."""
    found: dict[str, dict[str, Any]] = {}
    for repo in _pre_commit()["repos"]:
        for hook in repo.get("hooks") or []:
            found[hook["id"]] = hook
    return found


def _ci_static_analysis_steps() -> list[dict[str, Any]]:
    cfg = yaml.safe_load(CI.read_text(encoding="utf-8"))
    job = ((cfg or {}).get("jobs") or {}).get("static-analysis") or {}
    steps = job.get("steps") or []
    assert steps, "ci.yml has no `static-analysis` job to compare against"
    return steps


def _ci_pins() -> dict[str, str]:
    """`pip install ruff==X bandit==Y ...` of the CI, as {name: version}."""
    for step in _ci_static_analysis_steps():
        run = str(step.get("run", ""))
        if "pip install" in run:
            pins = dict(PIN.findall(run))
            assert pins, f"the CI install step pins nothing: {run!r}"
            return pins
    raise AssertionError("no `pip install` step in the CI static-analysis job")


def _ci_command(tool: str) -> str:
    for step in _ci_static_analysis_steps():
        run = str(step.get("run", "")).strip()
        if run.startswith(tool + " "):
            return run
    raise AssertionError(f"the CI static-analysis job never invokes {tool!r}")


def _hook_pins(hook: dict[str, Any]) -> dict[str, str]:
    return dict(PIN.findall(" ".join(hook.get("additional_dependencies") or [])))


def _recursed_dirs(command: str) -> list[str]:
    """The paths a `bandit -r a b c -q` style command walks."""
    tokens = shlex.split(command)
    if "-r" not in tokens:
        return []
    dirs = []
    for token in tokens[tokens.index("-r") + 1:]:
        if token.startswith("-"):
            break
        dirs.append(token)
    return dirs


def test_every_gated_tool_has_a_hook() -> None:
    missing = sorted(set(TOOLS) - set(_hooks()))
    assert not missing, (
        f"{PRE_COMMIT.name} has no hook for {missing}. Those gates block in CI "
        "but nothing runs them before the push (#1010)."
    )


def test_hook_versions_are_the_ones_the_ci_installs() -> None:
    """The load-bearing assertion. A hook on a different version is worse than
    no hook: it goes green locally and red on the remote."""
    ci_pins = _ci_pins()
    hooks = _hooks()
    for hook_id, dist in TOOLS.items():
        assert dist in ci_pins, f"the CI install step does not pin {dist!r}"
        pinned = _hook_pins(hooks[hook_id])
        assert pinned.get(dist) == ci_pins[dist], (
            f"hook {hook_id!r} pins {dist}=={pinned.get(dist)} while CI installs "
            f"{dist}=={ci_pins[dist]}. Bump both, or the local run stops meaning "
            "anything about the remote one."
        )


def test_the_bandit_hook_reads_the_repo_config_like_the_ci_does() -> None:
    """Without `-c pyproject.toml` bandit runs on its defaults and floods the
    developer with B101 from every test file — the noise the config removes."""
    entry = str(_hooks()["bandit"].get("entry", ""))
    tokens = shlex.split(entry)
    assert "-c" in tokens and tokens[tokens.index("-c") + 1] == "pyproject.toml", (
        f"the bandit hook runs {entry!r}, which ignores the repo config that "
        "the CI passes with `-c pyproject.toml`."
    )


def test_the_bandit_hook_scans_the_same_tree_as_the_ci() -> None:
    """Same versions over a smaller set of paths is the same divergence with
    extra steps: the hook would pass on code the CI still rejects."""
    hook_dirs = _recursed_dirs(str(_hooks()["bandit"].get("entry", "")))
    ci_dirs = _recursed_dirs(_ci_command("bandit"))
    assert ci_dirs, "the CI bandit command recurses into no directory"
    assert set(hook_dirs) >= set(ci_dirs), (
        f"the bandit hook scans {sorted(hook_dirs)} but CI scans "
        f"{sorted(ci_dirs)}; {sorted(set(ci_dirs) - set(hook_dirs))} would only "
        "ever be checked on the remote."
    )


def test_the_ruff_hook_checks_and_does_not_reformat() -> None:
    """`ruff format` is deliberately out of scope: the repo does not use it,
    and enabling it would rewrite the whole tree on the next commit. This
    records the decision instead of leaving it to be re-litigated."""
    entries = {hook_id: str(hook.get("entry", "")) for hook_id, hook in _hooks().items()}
    assert "check" in shlex.split(entries["ruff"]), (
        f"the ruff hook runs {entries['ruff']!r}, not `ruff check`."
    )
    formatting = sorted(
        hook_id for hook_id, entry in entries.items() if "format" in shlex.split(entry)
    )
    assert not formatting, (
        f"hook(s) {formatting} run `ruff format`. The repo has never been "
        "formatted with it, so the next commit would carry a tree-wide diff. "
        "If that is now wanted, it is its own change — not a side effect of a "
        "pre-commit config."
    )
