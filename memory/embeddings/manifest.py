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
    "version": "0.9.0",
    "description": "Multilingual embedding and vectorization system",
    "author": "Jordi Goy",
    "type": "memory_core",
    "priority": 100,
    "capabilities": ["text_encoding", "batch_encoding", "chunking"],
    "dependencies": {
        "python": [
            "sentence-transformers>=2.3.1",
            "numpy>=1.26.0",
            "torch>=2.0.0"
        ]
    }
}
