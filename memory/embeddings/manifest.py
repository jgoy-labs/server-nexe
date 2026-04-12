"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/manifest.py
Description: Manifest for the Embeddings module following Nexe 0.9 pattern.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

MODULE_ID = "embeddings"

MANIFEST = {
    "name": "embeddings",
    "version": "0.9.1",
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
