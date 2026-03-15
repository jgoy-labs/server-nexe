"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/__init__.py
Description: Mòdul Embeddings - Sistema d'embeddings i vectorització multilingüe amb cache multi-nivell.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .module import EmbeddingsModule
from .constants import MANIFEST

__all__ = ["EmbeddingsModule", "MANIFEST"]