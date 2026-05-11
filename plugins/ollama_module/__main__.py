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
    if app is None:
        import sys
        print("Error: Requires 'typer' and 'rich'. Install with: pip install typer rich", file=sys.stderr)
        sys.exit(1)
    app()
