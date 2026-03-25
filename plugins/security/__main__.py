"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/__main__.py
Description: Entry point CLI per al modul security.
             Permet executar: python -m plugins.security [command]

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli.main import app

if __name__ == "__main__":
    app()
