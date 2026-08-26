"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/manifest.py
Description: Manifest for the Embeddings module following server-nexe pattern.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.version import __version__

MODULE_ID = "embeddings"

MANIFEST = {
    "name": "embeddings",
    "version": __version__,
    "description": "Multilingual embedding and vectorization system",
    "author": "Jordi Goy",
    "type": "memory_core",
    "priority": 100,
    "capabilities": ["text_encoding", "batch_encoding", "chunking"],
    "dependencies": {
        "python": [
            "fastembed>=0.3.6",
            "numpy>=1.26.0"
        ]
    }
}
