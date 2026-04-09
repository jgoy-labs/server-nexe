"""
────────────────────────────────────
Server Nexe
Location: memory/memory/engines/qdrant_types.py
Description: Punt únic d'importació dels tipus de qdrant_client.models.

Centralitza la dependència a qdrant_client en un sol fitxer dins memory/memory/.
Si en el futur es canvia el vector store, només cal modificar aquest fitxer.
────────────────────────────────────
"""

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

__all__ = [
    "Distance",
    "FieldCondition",
    "Filter",
    "MatchValue",
    "PointIdsList",
    "PointStruct",
    "VectorParams",
]
