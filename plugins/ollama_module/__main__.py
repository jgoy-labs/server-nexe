"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/__main__.py
Description: Entry point CLI per al modul Ollama.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .cli.main import app

if __name__ == "__main__":
    app()
