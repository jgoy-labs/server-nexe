"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/log_viewer.py
Description: Real-time log viewer for Nexe Server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import shutil
import subprocess  # nosec B404: subprocess required to invoke system `tail` for log following; usage validated below
import time
from pathlib import Path
from typing import Optional

import click

from .i18n import t


def tail_file(filepath: Path, last: int = 50):
    """Simulates `tail -f` on a log file."""
    if not filepath.exists():
        click.echo(click.style(t("cli.logs.file_not_found", path=str(filepath)), fg="yellow"))
        return

    click.echo(click.style(
        t("cli.logs.following", path=str(filepath), last=last),
        fg="cyan", bold=True,
    ))
    click.echo(click.style(t("cli.logs.press_ctrl_c") + "\n", dim=True))

    try:
        # Prioritize system `tail` if available (more efficient).
        if shutil.which("tail"):
            subprocess.run(["tail", "-n", str(last), "-f", str(filepath)])  # nosec B603 B607: filepath validated via validate_safe_path against logs_dir; last is int CLI option; tail via PATH
        else:
            # Pure Python fallback.
            with open(filepath, "r") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    print(line, end="")
    except KeyboardInterrupt:
        click.echo(t("cli.logs.stopping_viewer"))


@click.command()
@click.option('--module', '-m', help='Filter by module (log name)')
@click.option('--last', '-n', default=50, help='Number of initial lines to show')
def logs(module: Optional[str], last: int):
    """Show Nexe logs in real time."""
    project_root = Path(__file__).parent.parent.parent
    logs_dir = project_root / "storage" / "logs"

    if not logs_dir.exists():
        click.echo(click.style(t("cli.logs.dir_not_found", path=str(logs_dir)), fg="red"))
        return

    # If a module is specified, look for its specific log.
    if module:
        log_file = logs_dir / f"{module}.log"
    else:
        # By default use the main system log.
        log_file = logs_dir / "nexe.log"
        if not log_file.exists():
            # If nexe.log does not exist, see what logs are available.
            all_logs = list(logs_dir.glob("*.log"))
            if not all_logs:
                click.echo(click.style(t("cli.logs.no_files"), fg="yellow"))
                return
            log_file = all_logs[0]

    # SECURITY FIX: ensure the log file is within the logs directory.
    from plugins.security.core.validators import validate_safe_path
    log_file = validate_safe_path(log_file, logs_dir)

    tail_file(log_file, last)


if __name__ == "__main__":
    logs()
