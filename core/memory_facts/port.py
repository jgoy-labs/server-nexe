"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/port.py
Description: What the turn column needs from memory, as a Protocol.

The names are the ones MemoryHelper already exposes: the port describes the
door that exists, so the helper satisfies it without a single wrapper. The
underlying store is reached through core.memory_access.MemoryView (D-M: the
plugin never builds a private API), so this port has an adapter already.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MemoryPort(Protocol):
    """The memory operations a turn can ask for, whatever implements them."""

    async def save_to_memory(
        self,
        content: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ...

    async def recall_from_memory(
        self,
        query: str,
        limit: int = 5,
        collections: Optional[list] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ...

    async def delete_from_memory(
        self,
        content: str,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ...

    async def preview_delete_from_memory(
        self,
        content: str,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ...

    async def list_memories(
        self,
        limit: int = 20,
        collections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ...
