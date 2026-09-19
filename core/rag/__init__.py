"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag/__init__.py
Description: Retrieval sources — the port the turn asks for context through.

ADR-008: the core defines the port, the source implements it (ADR-007 §5).
`source.py` holds the contract and nothing else; `collections.py` holds the
three sources server-nexe ships with, one per Qdrant collection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
