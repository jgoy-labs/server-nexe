"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/__main__.py
Description: Entry point per executar mòdul Ollama (opció local LLM) directament

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .module import main
import sys
import asyncio

if __name__ == "__main__":
  sys.exit(asyncio.run(main()))