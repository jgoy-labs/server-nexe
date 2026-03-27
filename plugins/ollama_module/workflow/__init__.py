"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/workflow/__init__.py
Description: Workflow Engine nodes package for the Ollama module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .nodes.ollama_node import OllamaNode

__all__ = ["OllamaNode"]