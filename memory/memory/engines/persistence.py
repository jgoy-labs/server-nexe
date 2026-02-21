"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/engines/persistence.py
Description: PersistenceManager - SQLite (metadata) + Qdrant (vectors) with rollback.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from ..models.memory_entry import MemoryEntry

logger = logging.getLogger(__name__)

# Configurable timeouts via environment variables
# SECURITY: Capped to MAX_TIMEOUT to prevent resource exhaustion
MAX_TIMEOUT = 60.0  # Maximum allowed timeout in seconds

def _safe_timeout(env_var: str, default: float) -> float:
    """Get timeout from environment with safety cap."""
    try:
        value = float(os.getenv(env_var, str(default)))
        if value <= 0:
            return default
        return min(value, MAX_TIMEOUT)
    except (ValueError, TypeError):
        return default

QDRANT_TIMEOUT = _safe_timeout('NEXE_QDRANT_TIMEOUT', 5.0)
SQLITE_PRELOAD_TIMEOUT = _safe_timeout('NEXE_SQLITE_PRELOAD_TIMEOUT', 10.0)

class StorageError(Exception):
  """Error in persistence operations"""

class PersistenceManager:
  """
  Dual persistence manager: SQLite + Qdrant.

  Features:
  - SQLite (WAL): metadata + text
  - Qdrant: embedding vectors (via HTTP client to server)
  - Rollback: delete SQLite if Qdrant fails
  - run_in_executor for blocking operations
  """

  DEFAULT_QDRANT_URL = "http://localhost:6333"

  def __init__(
    self,
    db_path: Path,
    qdrant_path: Path = None,
    collection_name: str = "nexe_memory",
    vector_size: int = 768,
    qdrant_url: str = None
  ):
    self.db_path = db_path
    self.qdrant_path = qdrant_path
    self.qdrant_url = qdrant_url or self.DEFAULT_QDRANT_URL
    self.collection_name = collection_name
    self.vector_size = vector_size

    self.executor = ThreadPoolExecutor(max_workers=4)

    self._init_sqlite()

    self._init_qdrant()

    logger.info("PersistenceManager initialized (db=%s, qdrant=%s)", db_path, self.qdrant_url or "Embedded")

  def _init_sqlite(self):
    """Initialize SQLite database with WAL mode"""
    self.db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = self._connect_sqlite()
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL")

    cursor.execute("""
      CREATE TABLE IF NOT EXISTS memory_entries (
        id TEXT PRIMARY KEY,
        entry_type TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT NOT NULL,
        timestamp REAL NOT NULL,
        ttl_seconds INTEGER,
        metadata_json TEXT,
        created_at REAL DEFAULT (julianday('now'))
      )
    """)

    cursor.execute("""
      CREATE INDEX IF NOT EXISTS idx_entry_type
      ON memory_entries(entry_type)
    """)

    cursor.execute("""
      CREATE INDEX IF NOT EXISTS idx_timestamp
      ON memory_entries(timestamp DESC)
    """)

    conn.commit()
    conn.close()

    logger.info("SQLite initialized with WAL mode")

  def _connect_sqlite(self) -> sqlite3.Connection:
    """Open SQLite connection with busy timeout to reduce writer contention."""
    conn = sqlite3.connect(str(self.db_path))
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn

  def _init_qdrant(self):
    """
    Initialize Qdrant client.
    
    Priority:
    1. Local Path (Embedded mode): If qdrant_path is provided.
    2. URL (Server mode): If qdrant_url is configured.

    ✅ FIX: Real support for embedded mode without external server.
    """
    self.qdrant = None
    self._qdrant_available = False

    try:
      if self.qdrant_path:
        # Mode Embedded (Local files)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self.qdrant = QdrantClient(path=str(self.qdrant_path))
        logger.info("Qdrant initialized in EMBEDDED mode at %s", self.qdrant_path)
      else:
        # Mode Server (HTTP)
        qdrant_api_key = os.getenv("QDRANT_API_KEY")  # None = no auth (local)
        self.qdrant = QdrantClient(
          url=self.qdrant_url,
          api_key=qdrant_api_key,
          prefer_grpc=False,
          timeout=QDRANT_TIMEOUT
        )
        logger.info("Qdrant initialized in SERVER mode at %s", self.qdrant_url)

      collections = self.qdrant.get_collections().collections
      collection_names = [c.name for c in collections]

      if self.collection_name not in collection_names:
        self.qdrant.create_collection(
          collection_name=self.collection_name,
          vectors_config=VectorParams(
            size=self.vector_size,
            distance=Distance.COSINE
          )
        )
        logger.info("Created Qdrant collection '%s'", self.collection_name)
      else:
        logger.debug("Qdrant collection '%s' already exists", self.collection_name)

      self._qdrant_available = True

    except Exception as e:
      mode = "Embedded" if self.qdrant_path else "Server"
      logger.warning(
        "Qdrant %s mode failed: %s. Memory will use SQLite only (degraded mode).",
        mode, e
      )
      self.qdrant = None
      self._qdrant_available = False

  async def store(
    self,
    entry: MemoryEntry,
    embedding: Optional[List[float]] = None,
    strict: bool = True
  ) -> str:
    """
    Store entry with dual consistency management (SQLite + Qdrant).

    Improved robustness in synchronization failures.

    Args:
      entry: MemoryEntry to save
      embedding: Embedding vector (optional)
      strict: If True, rollbacks SQLite if Qdrant fails. If False, allows "degraded mode".

    Returns:
      str: Entry ID

    Raises:
      StorageError: If persistence fails in strict mode
    """
    await self._store_sqlite(entry)

    if embedding and self._qdrant_available:
      try:
        payload_with_content = {
          **(entry.metadata or {}),
          "content": entry.content,
          "entry_type": entry.entry_type,
          "source": entry.source,
        }
        await self._store_qdrant(entry.id, embedding, payload_with_content)
      except Exception as e:
        if strict:
          logger.error(
            "CRITICAL: Qdrant storage failed for %s: %s. Performing ROLLBACK on SQLite to prevent divergence.",
            entry.id, e
          )
          await self._delete_sqlite(entry.id)
          raise StorageError(f"Storage failed (Strict mode: Rollback performed): {e}")
        else:
          logger.warning(
            "DEGRADED: Qdrant storage failed for %s: %s. Entry kept in SQLite only.",
            entry.id, e
          )
    elif embedding and not self._qdrant_available:
      logger.debug("Entry %s stored only in SQLite (Qdrant service is unavailable/degraded).", entry.id)

    return entry.id

  async def _store_sqlite(self, entry: MemoryEntry):
    """Store entry to SQLite (run_in_executor)"""
    loop = asyncio.get_running_loop()

    def _sync_store():
      conn = self._connect_sqlite()
      cursor = conn.cursor()


      metadata_json = json.dumps(entry.metadata) if entry.metadata else None

      # Use UNIX timestamp (seconds since epoch) - industry standard
      unix_timestamp = entry.timestamp.timestamp()

      cursor.execute("""
        INSERT OR REPLACE INTO memory_entries
        (id, entry_type, content, source, timestamp, ttl_seconds, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      """, (
        entry.id,
        entry.entry_type,
        entry.content,
        entry.source,
        unix_timestamp,
        entry.ttl_seconds,
        metadata_json
      ))

      conn.commit()
      conn.close()

    await loop.run_in_executor(self.executor, _sync_store)
    logger.debug("Stored entry %s to SQLite", entry.id)

  @staticmethod
  def _hex_to_uuid(hex_id: str) -> str:
    """
    Convert SHA256 hex ID to UUID format for Qdrant.

    Args:
      hex_id: 16-character hex string (from SHA256[:16])

    Returns:
      UUID string in format 8-4-4-4-12
    """
    padded = hex_id.ljust(32, '0')
    return str(uuid.UUID(padded))

  async def _store_qdrant(self, entry_id: str, embedding: List[float], metadata: Dict[str, Any]):
    """Store vector a Qdrant"""
    uuid_id = PersistenceManager._hex_to_uuid(entry_id)

    def _sync_upsert():
      point = PointStruct(
        id=uuid_id,
        vector=embedding,
        payload={
          **(metadata or {}),
          "original_id": entry_id
        }
      )
      self.qdrant.upsert(
        collection_name=self.collection_name,
        points=[point]
      )

    if self.qdrant_path:
      # In embedded mode (SQLite/Local), it is better not to use executor 
      # to avoid sqlite3 "created in different thread" errors
      _sync_upsert()
    else:
      # In server mode (HTTP), the executor allows not blocking the main thread
      loop = asyncio.get_running_loop()
      await loop.run_in_executor(self.executor, _sync_upsert)
      
    logger.debug("Stored vector for %s to Qdrant", entry_id)

  async def _delete_sqlite(self, entry_id: str):
    """Delete entry from SQLite (rollback helper)"""
    loop = asyncio.get_running_loop()

    def _sync_delete():
      conn = self._connect_sqlite()
      cursor = conn.cursor()
      cursor.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
      conn.commit()
      conn.close()

    await loop.run_in_executor(self.executor, _sync_delete)
    logger.debug("Deleted entry %s from SQLite (rollback)", entry_id)

  async def get(self, entry_id: str) -> Optional[MemoryEntry]:
    """Retrieve entry by ID"""
    loop = asyncio.get_running_loop()

    def _sync_get():
      conn = self._connect_sqlite()
      cursor = conn.cursor()

      cursor.execute("""
        SELECT id, entry_type, content, source, timestamp, ttl_seconds, metadata_json
        FROM memory_entries
        WHERE id = ?
      """, (entry_id,))

      row = cursor.fetchone()
      conn.close()

      if not row:
        return None

      return self._row_to_entry(row)

    entry = await loop.run_in_executor(self.executor, _sync_get)
    return entry

  async def search(
    self,
    query_vector: List[float],
    limit: int = 10,
    filter_type: Optional[str] = None
  ) -> List[tuple]:
    """
    Semantic search with Qdrant.

    Args:
      query_vector: Search vector
      limit: Max results
      filter_type: Filter by entry_type

    Returns:
      List[(entry_id, score)]
    """
    loop = asyncio.get_running_loop()

    def _sync_search():
      if hasattr(self.qdrant, "search"):
        results = self.qdrant.search(
          collection_name=self.collection_name,
          query_vector=query_vector,
          limit=limit
        )
      else:
        # Fallback for modern qdrant-client versions (1.11+)
        res = self.qdrant.query_points(
          collection_name=self.collection_name,
          query=query_vector,
          limit=limit
        )
        results = res.points

      # Convert Qdrant UUID string back to original_id if possible, 
      # or simply return the UUID format that Qdrant uses.
      # LocalClient returns IDs as strings or integers.
      return [(r.id, r.score) for r in results]

    if self.qdrant_path:
      results = _sync_search()
    else:
      loop = asyncio.get_running_loop()
      results = await loop.run_in_executor(self.executor, _sync_search)

    logger.debug("Qdrant search returned %s results", len(results))
    return results

  def _row_to_entry(self, row: tuple) -> MemoryEntry:
    """Convert SQLite row to MemoryEntry"""
    from datetime import datetime, timezone

    entry_id, entry_type, content, source, timestamp, ttl_seconds, metadata_json = row

    metadata = json.loads(metadata_json) if metadata_json else {}


    return MemoryEntry(
      id=entry_id,
      entry_type=entry_type,
      content=content,
      source=source,
      timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
      ttl_seconds=ttl_seconds,
      metadata=metadata
    )

  async def get_stats(self) -> Dict[str, int]:
    """Get persistence statistics"""
    loop = asyncio.get_running_loop()

    def _sync_stats():
      conn = self._connect_sqlite()
      cursor = conn.cursor()

      cursor.execute("SELECT COUNT(*) FROM memory_entries")
      total = cursor.fetchone()[0]

      cursor.execute("SELECT COUNT(*) FROM memory_entries WHERE entry_type = 'episodic'")
      episodic = cursor.fetchone()[0]

      cursor.execute("SELECT COUNT(*) FROM memory_entries WHERE entry_type = 'semantic'")
      semantic = cursor.fetchone()[0]

      conn.close()

      return {
        "total_entries": total,
        "episodic_count": episodic,
        "semantic_count": semantic
      }

    stats = await loop.run_in_executor(self.executor, _sync_stats)
    return stats

  async def get_recent(
    self,
    limit: int = 50,
    entry_types: Optional[List[str]] = None,
    exclude_expired: bool = True
  ) -> List[MemoryEntry]:
    """
    Retrieve the N most recent entries from SQLite.

    Used for preload to RAMContext on boot.

    Args:
      limit: Max entries to return (default: 50)
      entry_types: Filter by type (default: ["episodic"])
      exclude_expired: Exclude expired entries by TTL (default: True)

    Returns:
      List[MemoryEntry] ordered by timestamp DESC
    """
    loop = asyncio.get_running_loop()
    types_filter = entry_types or ["episodic"]

    def _sync_get_recent():
      from datetime import datetime, timezone

      conn = self._connect_sqlite()
      cursor = conn.cursor()

      placeholders = ",".join(["?" for _ in types_filter])
      query = f"""
        SELECT id, entry_type, content, source, timestamp, ttl_seconds, metadata_json
        FROM memory_entries
        WHERE entry_type IN ({placeholders})
        ORDER BY timestamp DESC
        LIMIT ?
      """

      cursor.execute(query, (*types_filter, limit * 2))
      rows = cursor.fetchall()
      conn.close()

      entries = []
      # Use UNIX timestamp for TTL comparison
      now_ts = datetime.now(timezone.utc).timestamp()

      for row in rows:
        if len(entries) >= limit:
          break

        entry_id, entry_type, content, source, timestamp, ttl_seconds, metadata_json = row

        # TTL check using UNIX timestamps (seconds)
        if exclude_expired and ttl_seconds:
          expiry_ts = timestamp + ttl_seconds
          if expiry_ts < now_ts:
            continue

        metadata = json.loads(metadata_json) if metadata_json else {}

        # Convert UNIX timestamp back to datetime
        try:
          entry_datetime = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, OSError):
          entry_datetime = datetime.now(timezone.utc)

        entries.append(MemoryEntry(
          id=entry_id,
          entry_type=entry_type,
          content=content,
          source=source,
          timestamp=entry_datetime,
          ttl_seconds=ttl_seconds,
          metadata=metadata
        ))

      return entries

    try:
      entries = await asyncio.wait_for(
        loop.run_in_executor(self.executor, _sync_get_recent),
        timeout=SQLITE_PRELOAD_TIMEOUT
      )
      logger.info("Loaded %d recent entries from SQLite", len(entries))
      return entries
    except asyncio.TimeoutError:
      logger.warning("SQLite preload timeout (%.1fs), continuing with empty RAM", SQLITE_PRELOAD_TIMEOUT)
      return []
    except Exception as e:
      logger.warning("SQLite preload failed: %s, continuing with empty RAM", e)
      return []

  def close(self):
    """Close resources"""
    self.executor.shutdown(wait=True)
    if self.qdrant:
      try:
        self.qdrant.close()
      except Exception as e:
        logger.debug("PersistenceManager close failed: %s", e)
      finally:
        if hasattr(self.qdrant, "_client"):
          delattr(self.qdrant, "_client")
    logger.info("PersistenceManager closed")

__all__ = ["PersistenceManager", "StorageError"]
