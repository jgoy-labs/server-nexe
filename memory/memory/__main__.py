"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/__main__.py
Description: Entry point per executar Memory module com a CLI.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli import main  # type: ignore[attr-defined]  # FP: main() definida a cli.py:396, mypy no la detecta per import cycle

if __name__ == "__main__":
  main()