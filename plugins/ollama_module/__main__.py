"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/__main__.py
Description: Entry point CLI for the Ollama module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli.main import app

if __name__ == "__main__":
    app()
