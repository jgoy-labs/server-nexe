"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/log_viewer.py
Description: Visualitzador de logs en temps real per a Nexe Server.

www.jgoy.net
────────────────────────────────────
"""

import sys
import os
import time
import subprocess
import shutil
from pathlib import Path
import click
from typing import Optional

from .i18n import t

def tail_file(filepath: Path, last: int = 50):
    """Simula un tail -f en un fitxer."""
    if not filepath.exists():
        click.echo(click.style(
            t("cli.logs.file_not_found", "⚠️ Log file not found: {path}", path=filepath),
            fg="yellow"
        ))
        return

    click.echo(click.style(
        t("cli.logs.following", "👀 Following logs: {path} (last {lines} lines)", path=filepath, lines=last),
        fg="cyan",
        bold=True
    ))
    click.echo(click.style(t("cli.logs.exit_hint", "--- Press Ctrl+C to exit ---\n"), dim=True))

    try:
        # Intentem usar tail si està disponible (més eficient)
        if shutil.which("tail"):
            subprocess.run(["tail", "-n", str(last), "-f", str(filepath)])
        else:
            # Fallback manual en python
            with open(filepath, "r") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    print(line, end="")
    except KeyboardInterrupt:
        click.echo(t("cli.logs.stopping", "\n👋 Stopping log viewer."))

@click.command()
@click.option('--module', '-m', help=t("cli.logs.option.module", "Filter by module (log name)"))
@click.option('--last', '-n', default=50, help=t("cli.logs.option.last", "Number of initial lines to show"))
def logs(module: Optional[str], last: int):
    """
    Mostra els logs de Nexe en temps real.
    """
    project_root = Path(__file__).parent.parent.parent
    logs_dir = project_root / "storage" / "logs"
    
    if not logs_dir.exists():
        click.echo(click.style(
            t("cli.logs.dir_not_found", "❌ Logs directory not found: {path}", path=logs_dir),
            fg="red"
        ))
        return

    # Si s'especifica mòdul, busquem el seu log
    if module:
        log_file = logs_dir / f"{module}.log"
    else:
        # Per defecte busquem el log principal del sistema
        log_file = logs_dir / "nexe.log"
        if not log_file.exists():
            # Si no existeix nexe.log, mirem què hi ha
            all_logs = list(logs_dir.glob("*.log"))
            if not all_logs:
                click.echo(click.style(
                    t("cli.logs.no_logs_found", "📭 No log files found in storage/logs/"),
                    fg="yellow"
                ))
                return
            log_file = all_logs[0]
            
    # SECURITY FIX: Ensure the log file is actually inside the logs directory
    from plugins.security.core.validators import validate_safe_path
    log_file = validate_safe_path(log_file, logs_dir)

    tail_file(log_file, last)

if __name__ == "__main__":
    import shutil
    logs()
