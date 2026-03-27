"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/__init__.py
Description: Embeddings module - Multilingual embeddings and vectorisation system with multi-level cache.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .module import EmbeddingsModule
from .constants import MANIFEST

__all__ = ["EmbeddingsModule", "MANIFEST"]