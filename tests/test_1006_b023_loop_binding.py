"""
────────────────────────────────────
Server Nexe
Location: tests/test_1006_b023_loop_binding.py
Description: Anti-regression for #1006 — closures defined inside a loop must
             bind the loop variable they read.

             Twelve of them did not: eleven in
             `plugins/web_ui_module/api/routes_chat.py` (`stream_cb` and
             `queue_generator`, over `_stream_chunk_count`, `queue` and
             `ml_task`) and one in `plugins/ollama_module/cli/main.py`
             (`get_response` over `messages`). A free name inside such a
             closure is read when the closure RUNS, not when it is defined —
             so an engine task that outlives its cascade iteration writes its
             tokens into the NEXT engine's queue, and the CLI's `clear` branch
             rebinds `messages` under a coroutine that already exists.

             `ruff check .` did not see any of it: `[tool.ruff.lint]` had no
             `select`, so ruff ran on its defaults (E4, E7, E9, F) and the
             whole bugbear family was off. The fix arms exactly B023 on top of
             those defaults — nothing else, the definitive `select` is #1008's
             open decision.

             The CI gate for this is the `ruff check .` step of the
             `static-analysis` job. These tests are the local net: the config
             assertion and the two Ollama CLI ones run everywhere, the four
             subprocess ones need the ruff binary and are skipped where it is
             absent (the `tests` CI job does not install it —
             `static-analysis` is the job that does).
────────────────────────────────────
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

# Ruff's own defaults, plus the single bugbear rule this finding buys.
EXPECTED_SELECT = ["E4", "E7", "E9", "F", "B023"]

# The shape of the bug: `g` reads `i` when it runs, and by then the loop moved on.
UNBOUND_SNIPPET = (
    "def f():\n"
    "    out = []\n"
    "    for i in range(3):\n"
    "        def g():\n"
    "            return i\n"
    "        out.append(g)\n"
    "    return out\n"
)

# The shape of the fix used in both production files: a parameter default,
# evaluated at def time, pins the closure to this iteration's object.
BOUND_SNIPPET = UNBOUND_SNIPPET.replace("def g():", "def g(*, i=i):")


def _ruff_binary() -> str | None:
    """The venv's ruff first (that is the pinned one), then whatever is on PATH."""
    candidate = Path(sys.executable).parent / "ruff"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("ruff")


RUFF = _ruff_binary()
needs_ruff = pytest.mark.skipif(
    RUFF is None,
    reason="ruff binary not installed in this environment — the CI gate for "
           "this is the `ruff check .` step of the static-analysis job",
)


def _ruff(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run ruff from the repo root so it reads pyproject.toml, as CI does."""
    assert RUFF is not None
    return subprocess.run(  # nosec B603 — fixed argv, no shell
        [RUFF, *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


class TestGateIsArmed:
    """Without `select`, ruff never reports B023 no matter how broken the code."""

    def test_lint_select_is_the_defaults_plus_b023(self) -> None:
        cfg = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        select = cfg["tool"]["ruff"]["lint"]["select"]
        assert select == EXPECTED_SELECT, (
            "[tool.ruff.lint].select must stay ruff's defaults plus B023. "
            "Widening it (or dropping a default) is finding #1008's decision, "
            f"not a drive-by edit. Found: {select!r}"
        )

    @needs_ruff
    def test_bare_ruff_check_reports_an_unbound_closure(self) -> None:
        """The CI command is `ruff check .` with no `--select`. This proves the
        config — not a flag — is what makes B023 visible."""
        result = _ruff(
            "check", "--no-cache", "--stdin-filename", "plugins/_b023_probe.py",
            "-", "--output-format", "concise",
            stdin=UNBOUND_SNIPPET,
        )
        assert result.returncode != 0, (
            "bare `ruff check` accepted a textbook B023 — the gate is off:\n"
            f"{result.stdout}{result.stderr}"
        )
        assert "B023" in result.stdout, result.stdout

    @needs_ruff
    def test_bare_ruff_check_accepts_a_parameter_bound_closure(self) -> None:
        """The fix shape applied to both production files, checked against the
        same config — so the gate is not just noisy but satisfiable."""
        result = _ruff(
            "check", "--no-cache", "--stdin-filename", "plugins/_b023_probe.py",
            "-", "--output-format", "concise",
            stdin=BOUND_SNIPPET,
        )
        assert result.returncode == 0, (
            "a loop variable bound as a parameter default is the fix and must "
            f"pass:\n{result.stdout}{result.stderr}"
        )


class TestRepoIsClean:
    @needs_ruff
    def test_no_closure_in_the_repo_leaves_a_loop_variable_free(self) -> None:
        """The 12 sites of #1006. Explicit `--select` so this keeps working
        even if someone loosens the pyproject config."""
        result = _ruff("check", "--no-cache", "--select", "B023", ".",
                       "--output-format", "concise")
        assert result.returncode == 0, (
            "B023 is back — a closure inside a loop reads a name the loop "
            f"rebinds:\n{result.stdout}{result.stderr}"
        )

    @needs_ruff
    def test_the_ci_command_itself_is_green(self) -> None:
        """`ruff check .`, byte for byte what `static-analysis` runs. Guards
        against the new `select` lighting up rules the repo does not satisfy."""
        result = _ruff("check", "--no-cache", ".", "--output-format", "concise")
        assert result.returncode == 0, (
            f"the CI ruff gate would be red:\n{result.stdout}{result.stderr}"
        )


class TestOllamaCliTurnBindsThisTurnsHistory:
    """The twelfth site, exercised rather than linted.

    `plugins/ollama_module/cli/main.py`'s chat loop had no test that ran a
    turn: the only one that reached `get_response` replaced `_run_async` with a
    counter that returned for the connection probe and raised for everything
    after it, so the coroutine was built and never awaited and its body stayed
    uncovered. These drive real turns through the real loop.
    """

    def _fake_ollama(self, reply: str, seen: list):
        from unittest.mock import AsyncMock, MagicMock

        ollama = MagicMock()
        ollama.check_connection = AsyncMock(return_value=True)

        def _chat(model, messages, stream=False):
            # Copy: the loop appends to this same list right after the await.
            seen.append([dict(m) for m in messages])

            async def _stream():
                for piece in reply:
                    yield {"message": {"content": piece}}

            return _stream()

        ollama.chat = _chat
        return ollama

    def _run(self, inputs: list[str], reply: str, system=None):
        from unittest.mock import MagicMock, patch

        from plugins.ollama_module.cli import chat

        seen: list = []
        ollama = self._fake_ollama(reply, seen)
        with patch("plugins.ollama_module.cli.main.OllamaModule", return_value=ollama), \
             patch("plugins.ollama_module.cli.main.Panel"), \
             patch("plugins.ollama_module.cli.main.console") as console:
            console.status.return_value.__enter__ = MagicMock()
            console.status.return_value.__exit__ = MagicMock(return_value=False)
            console.input.side_effect = inputs
            chat(model="mistral", system=system)
        return seen

    def test_a_second_turn_carries_the_first_answer(self):
        """The turn's own history: the coroutine must read the list that was
        current when it was built, and the reply it streamed must land in it."""
        seen = self._run(["hola", "adeu", "exit"], reply="OK")

        assert len(seen) == 2, "both turns must reach the engine"
        assert seen[0] == [{"role": "user", "content": "hola"}]
        assert seen[1] == [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "OK"},
            {"role": "user", "content": "adeu"},
        ]

    def test_clear_rebinds_the_history_and_the_next_turn_uses_the_new_one(self):
        """`clear` REBINDS `messages` — the exact move B023 warns about. The
        turn after it must see the fresh list, system prompt and all."""
        seen = self._run(["hola", "clear", "adeu", "exit"], reply="OK",
                         system="ets un assistent")

        assert len(seen) == 2
        assert seen[0] == [
            {"role": "system", "content": "ets un assistent"},
            {"role": "user", "content": "hola"},
        ]
        assert seen[1] == [
            {"role": "system", "content": "ets un assistent"},
            {"role": "user", "content": "adeu"},
        ], "the cleared history is the one the next turn must send"


class TestTheCommentsAgreeWithTheConfig:
    """#1006 armed `select` and left a comment in the same file saying ruff had
    none.

    `pyproject.toml` explains why the complexity gate's `func_params_warn` is 9
    and ends by comparing it to ruff's PLR0913. Until #1006 that sentence
    justified PLR0913 being off with "ruff has no `select`, so only E4/E7/E9/F
    run" — true when it was written, false the moment the `[tool.ruff.lint]`
    block above it landed. The fact survived (PLR0913 is still not enabled);
    the reason did not.

    It is not cosmetic: the next person to weigh PLR0913 would have read that
    the 9/12 calibration was made in a world where ruff selected nothing, and
    decided on a false premise.

    So the note is tied to the configuration instead of restating it. These
    tests fail if the sentence goes stale again, whichever end moves.

    The note lives in a section of `pyproject.toml` that belongs to internal
    tooling, and the published tree does not carry that section. So the one
    test that reads the note is tied to `func_params_warn`, the setting the
    note exists to explain: where the setting is configured the note MUST be
    there and MUST agree, and where the section is absent there is nothing to
    disagree with. The skip is bound to that key and nothing else — the two
    tests below it check `[tool.ruff.lint].select`, which every tree carries,
    and they run everywhere.
    """

    #: The setting the PLR0913 note exists to justify. Present wherever the
    #: internal tooling section is; absent from trees that do not ship it.
    ANNOTATED_SETTING = "func_params_warn"

    def _note_is_shipped_here(self) -> bool:
        return self.ANNOTATED_SETTING in PYPROJECT.read_text(encoding="utf-8")

    def _plr0913_note(self) -> str:
        """The comment line in pyproject.toml that talks about PLR0913."""
        lines = [
            line for line in PYPROJECT.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("#") and "PLR0913" in line
        ]
        assert len(lines) == 1, (
            f"expected exactly one PLR0913 note in pyproject.toml, found {len(lines)}"
        )
        return lines[0]

    def test_the_note_lists_the_select_that_is_actually_configured(self) -> None:
        """Parsed from both ends and compared — not a third copy of the list."""
        import re

        if not self._note_is_shipped_here():
            pytest.skip(
                f"{self.ANNOTATED_SETTING} is not configured in this tree, so the "
                "note it annotates is not here either — nothing to disagree with"
            )

        note = self._plr0913_note()
        quoted = re.search(r"\[([^\]]*)\]", note)
        assert quoted, (
            "the PLR0913 note must name the rules ruff actually selects, as a "
            f"list, so this can check it: {note!r}"
        )
        claimed = re.findall(r'"([^"]+)"', quoted.group(1))

        cfg = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        configured = cfg["tool"]["ruff"]["lint"]["select"]

        assert claimed == configured, (
            "the PLR0913 note and [tool.ruff.lint].select disagree — one of the "
            f"two was edited and the other left behind. Note says {claimed}, "
            f"config says {configured}."
        )

    def test_the_substantive_claim_is_still_true(self) -> None:
        """The note says PLR0913 is not enabled. Correcting a stale reason must
        not quietly turn the fact into a lie either."""
        cfg = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        select = cfg["tool"]["ruff"]["lint"]["select"]
        assert not any(rule.startswith("PLR") for rule in select), (
            "PLR0913 (or another PLR rule) is enabled now — the note next to "
            "func_params_warn says it is not"
        )

    def test_nothing_in_the_file_still_says_ruff_has_no_select(self) -> None:
        """The exact sentence that went stale, so re-introducing it is red.

        Grepped over the whole repo when this was fixed: pyproject.toml was the
        only place that said it.
        """
        import re

        stale = [
            line for line in PYPROJECT.read_text(encoding="utf-8").splitlines()
            if re.search(r"has no\s+`?select`?", line, re.IGNORECASE)
        ]
        assert stale == [], (
            f"ruff has had a `select` since #1006; these lines say otherwise: {stale}"
        )
