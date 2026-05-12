"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: dev-tools/run_live.py
Description: Orchestrator for live server tests.
             Runs tests/test_live/ and generates a detailed markdown report.

Usage:
  python dev-tools/run_live.py
  python dev-tools/run_live.py --server-url http://localhost:9119
  python dev-tools/run_live.py --output /tmp/report.md

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_DIR = PROJECT_ROOT / "dev-tools" / "reports"
TMP_JSON = Path("/tmp/nexe_live_result.json")

# ─── ANSI colours (terminal only) ─────────────────────────────────────────────

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
RESET = "\033[0m"


def _c(text: str, colour: str) -> str:
    """Apply ANSI colour if stdout is a TTY."""
    if sys.stdout.isatty():
        return f"{colour}{text}{RESET}"
    return text


# ─── Pytest runner ────────────────────────────────────────────────────────────

def _run_pytest(server_url: str | None) -> int:
    """Invoke pytest and return the exit code."""
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_live/",
        "-m", "test_live",
        "-v", "--tb=short",
        "--json-report",
        f"--json-report-file={TMP_JSON}",
        "--no-header",
        "--no-cov",   # coverage not relevant for live tests
    ]
    env_extra: dict[str, str] = {}
    if server_url:
        env_extra["NEXE_TEST_URL"] = server_url

    import os
    env = {**os.environ, **env_extra}

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    return result.returncode


# ─── Report generation ────────────────────────────────────────────────────────

def _status_icon(outcome: str) -> str:
    return {"passed": "✅", "failed": "❌", "error": "❌", "skipped": "⏭️", "xfailed": "〰️", "xpassed": "⚠️"}.get(
        outcome, "❓"
    )


def _duration_str(duration: float) -> str:
    if duration < 1:
        return f"{duration * 1000:.0f}ms"
    return f"{duration:.1f}s"


def _build_report(json_path: Path, server_url: str) -> str:
    """Parse pytest JSON report and return a markdown report string."""
    if not json_path.exists():
        return "# nexe-live report\n\n❌ No JSON report found — pytest may have crashed.\n"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    tests   = data.get("tests", [])

    total    = summary.get("total", len(tests))
    passed   = summary.get("passed", 0)
    failed   = summary.get("failed", 0)
    errors   = summary.get("error", 0)
    skipped  = summary.get("skipped", 0)
    xfailed  = summary.get("xfailed", 0)
    duration = data.get("duration", 0.0)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = [
        f"# nexe-live report — {now}",
        "",
        f"**Servidor:** `{server_url}`",
        "",
        "## Resum",
        "",
        (
            f"{'✅' if failed == 0 and errors == 0 else '❌'} "
            f"**{passed} passed** · "
            f"{'❌ ' + str(failed + errors) + ' failed · ' if failed + errors else ''}"
            f"{'〰️ ' + str(xfailed) + ' xfail · ' if xfailed else ''}"
            f"{'⏭️ ' + str(skipped) + ' skipped · ' if skipped else ''}"
            f"⏱ {_duration_str(duration)}"
        ).strip(),
        "",
        "---",
        "",
        "## Per àrea",
        "",
    ]

    # Group by module (test file)
    from collections import defaultdict
    by_module: dict[str, list[dict]] = defaultdict(list)
    for t in tests:
        node = t.get("nodeid", "unknown")
        module = node.split("::")[0].split("/")[-1].replace(".py", "")
        by_module[module].append(t)

    for module, module_tests in sorted(by_module.items()):
        mod_passed  = sum(1 for t in module_tests if t.get("outcome") == "passed")
        mod_xfailed = sum(1 for t in module_tests if t.get("outcome") == "xfailed")
        mod_total   = len(module_tests)
        mod_ok      = (mod_passed + mod_xfailed) == mod_total
        xfail_note = f"+{mod_xfailed}xfail " if mod_xfailed else ""
        lines.append(f"### {module} ({mod_passed}/{mod_total} {xfail_note}{'✅' if mod_ok else '❌'})")
        lines.append("")

        for t in module_tests:
            outcome  = t.get("outcome", "unknown")
            node     = t.get("nodeid", "?")
            test_name = node.split("::")[-1] if "::" in node else node
            dur      = _duration_str(t.get("duration", 0.0))
            icon     = _status_icon(outcome)

            lines.append(f"{icon} `{test_name}` — {dur}")

            if outcome in ("failed", "error"):
                call = t.get("call", {})
                longrepr = call.get("longrepr", "") or t.get("longrepr", "")
                if longrepr:
                    # Truncate very long tracebacks
                    trimmed = longrepr[:1200]
                    if len(longrepr) > 1200:
                        trimmed += f"\n… (truncat, {len(longrepr)} chars total)"
                    indented = textwrap.indent(trimmed, "    ")
                    lines.append(f"```")
                    lines.append(indented)
                    lines.append(f"```")

            if outcome == "skipped":
                call = t.get("setup", {})
                skip_reason = call.get("longrepr", "")
                if skip_reason:
                    lines.append(f"   ↳ *{skip_reason[:200]}*")

        lines.append("")

    # Footer with raw counts
    xfail_footer = f" · {xfailed} 〰️xfail" if xfailed else ""
    lines += [
        "---",
        "",
        f"*Total: {total} tests · {passed} ✅ · {failed + errors} ❌{xfail_footer} · {skipped} ⏭️ · {_duration_str(duration)}*",
    ]

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run nexe live server tests and generate a markdown report."
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="Override server URL (default: NEXE_TEST_URL env or http://localhost:9119)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path for the markdown report (default: dev-tools/reports/live_TIMESTAMP.md)",
    )
    args = parser.parse_args()

    server_url = args.server_url or "http://localhost:9119"
    timestamp  = datetime.now().strftime("%Y%m%d%H%M%S")
    output     = Path(args.output) if args.output else REPORTS_DIR / f"live_{timestamp}.md"

    print(_c(f"\n🧪 nexe-live — {datetime.now().strftime('%H:%M:%S')}", BOLD + CYAN))
    print(_c(f"   Servidor: {server_url}", CYAN))
    print(_c(f"   Report:   {output}\n", CYAN))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TMP_JSON.unlink(missing_ok=True)

    exit_code = _run_pytest(args.server_url)

    report = _build_report(TMP_JSON, server_url)
    output.write_text(report, encoding="utf-8")

    print("\n" + "─" * 60)
    print(report)
    print("─" * 60)
    print(_c(f"\nReport desat a: {output}", CYAN))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
