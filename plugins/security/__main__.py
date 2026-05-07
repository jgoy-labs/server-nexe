"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/__main__.py
Description: CLI entry point for the security module.
             Allows running: python -m plugins.security [command]

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli.main import app

if __name__ == "__main__":
    app()
