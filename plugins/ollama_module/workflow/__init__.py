"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/workflow/__init__.py
Description: Paquet de nodes del Workflow Engine per al mòdul Ollama.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .nodes.ollama_node import OllamaNode

__all__ = ["OllamaNode"]