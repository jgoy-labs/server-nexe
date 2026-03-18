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
    """Simula un tail -f en un fitxer."""
    if not filepath.exists():
        click.echo(click.style(f"⚠️ Fitxer de log no trobat: {filepath}", fg="yellow"))
        return

    click.echo(click.style(f"👀 Seguint logs de: {filepath} (últimes {last} línies)", fg="cyan", bold=True))
    click.echo(click.style("--- Prem Ctrl+C per sortir ---\n", dim=True))

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
        click.echo("\n👋 Aturant visualitzador de logs.")

@click.command()
@click.option('--module', '-m', help='Filtrar per mòdul (nom del log)')
@click.option('--last', '-n', default=50, help='Nombre de línies inicials a mostrar')
def logs(module: Optional[str], last: int):
    """
    Mostra els logs de Nexe en temps real.
    """
    project_root = Path(__file__).parent.parent.parent
    logs_dir = project_root / "storage" / "logs"
    
    if not logs_dir.exists():
        click.echo(click.style(f"❌ Directori de logs no trobat: {logs_dir}", fg="red"))
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
                click.echo(click.style("📭 No s'han trobat fitxers de log a storage/logs/", fg="yellow"))
                return
            log_file = all_logs[0]
            
    # SECURITY FIX: Ensure the log file is actually inside the logs directory
    from plugins.security.core.validators import validate_safe_path
    log_file = validate_safe_path(log_file, logs_dir)

    tail_file(log_file, last)

if __name__ == "__main__":
    import shutil
    logs()
