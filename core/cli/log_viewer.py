"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/log_viewer.py
Description: Visualitzador de logs en temps real per a Nexe Server.

www.jgoy.net · https://server-nexe.org
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

def tail_file(filepath: Path, last: int = 50):
    """Simulate a tail -f on a file."""
    if not filepath.exists():
        click.echo(click.style(f"⚠️ Log file not found: {filepath}", fg="yellow"))
        return

    click.echo(click.style(f"👀 Following logs from: {filepath} (last {last} lines)", fg="cyan", bold=True))
    click.echo(click.style("--- Press Ctrl+C to exit ---\n", dim=True))

    try:
        # Try to use tail if available (more efficient)
        if shutil.which("tail"):
            subprocess.run(["tail", "-n", str(last), "-f", str(filepath)])
        else:
            # Manual fallback in Python
            with open(filepath, "r") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    print(line, end="")
    except KeyboardInterrupt:
        click.echo("\n👋 Stopping log viewer.")

@click.command()
@click.option('--module', '-m', help='Filter by module (log name)')
@click.option('--last', '-n', default=50, help='Number of initial lines to show')
def logs(module: Optional[str], last: int):
    """
    Show Nexe logs in real time.
    """
    project_root = Path(__file__).parent.parent.parent
    logs_dir = project_root / "storage" / "logs"
    
    if not logs_dir.exists():
        click.echo(click.style(f"❌ Logs directory not found: {logs_dir}", fg="red"))
        return

    # If a module is specified, look for its log
    if module:
        log_file = logs_dir / f"{module}.log"
    else:
        # Default to the main system log
        log_file = logs_dir / "nexe.log"
        if not log_file.exists():
            # If nexe.log doesn't exist, see what's available
            all_logs = list(logs_dir.glob("*.log"))
            if not all_logs:
                click.echo(click.style("📭 No log files found in storage/logs/", fg="yellow"))
                return
            log_file = all_logs[0]
            
    # SECURITY FIX: Ensure the log file is actually inside the logs directory
    from plugins.security.core.validators import validate_safe_path
    log_file = validate_safe_path(log_file, logs_dir)

    tail_file(log_file, last)

if __name__ == "__main__":
    logs()
