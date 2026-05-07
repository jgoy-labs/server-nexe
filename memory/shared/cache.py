"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/shared/cache.py
Description: MultiLevelCache implementation (L1 Memory + L2 SQLite).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import sqlite3
import json
import time
from pathlib import Path
from typing import Optional, Any, Dict
import hashlib
import asyncio

# Color constants for logs
RED = "\033[1;31m"
RESET = "\033[0m"

logger = logging.getLogger(__name__)

class MultiLevelCache:
    """
    Multi-level cache (L1: RAM, L2: SQLite).
    Designed to store embeddings and reduce latency.
    """

    def __init__(
        self,
        l1_max_size: int = 1000,
        l2_max_size_gb: float = 5.0,
        l2_ttl_hours: int = 72,
        cache_dir: str = "storage/cache/embeddings"
    ):
        """
        Initialize the cache.

        Args:
            l1_max_size: Maximum number of elements in RAM
            l2_max_size_gb: Approximate maximum size on disk (GB)
            l2_ttl_hours: Time-to-live for elements on disk
            cache_dir: Directory for the SQLite database
        """
        self.l1_max_size = l1_max_size
        self.l2_max_size_bytes = int(l2_max_size_gb * 1024 * 1024 * 1024)
        self.l2_ttl_seconds = l2_ttl_hours * 3600
        self._lock = asyncio.Lock()
        
        # L1 Cache (Python dict; OrderedDict with LRU would be better,
        # but using plain dict + simple eviction for simplicity)
        self.l1_cache: Dict[str, Any] = {}
        
        # L2 Cache Configuration
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "embeddings_l2.db"

        self.conn: Optional[sqlite3.Connection] = None
        self._init_l2()

    # Backward-compatible alias used by some tests/legacy code
    @property
    def l2_cache_dir(self) -> Path:
        return self.cache_dir

    @l2_cache_dir.setter
    def l2_cache_dir(self, value: Any) -> None:
        """
        Set L2 cache directory (alias for cache_dir).

        Supports test isolation by redirecting SQLite DB to a temp folder.
        """
        new_dir = Path(value)
        new_dir.mkdir(parents=True, exist_ok=True)

        # Close existing connection to avoid locks on old path
        existing_conn = getattr(self, "conn", None)
        if existing_conn is not None:
            try:
                existing_conn.close()
            except Exception as e:
                logger.debug("Cache close failed: %s", e)
            finally:
                self.conn = None

        self.cache_dir = new_dir
        self.db_path = self.cache_dir / "embeddings_l2.db"
        self._init_l2()

    def _init_l2(self) -> None:
        """Initialize the SQLite connection and schema."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA busy_timeout = 5000")
            # Create table if it does not exist
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data BLOB,
                    created_at REAL,
                    last_accessed REAL
                )
            """)
            
            # Index for efficient cleanup
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_accessed ON cache(last_accessed)
            """)
            
            self.conn.commit()
            cursor.close()
            
        except Exception as e:
            logger.error(f"Failed to initialize L2 cache: {e}")
            self.conn = None

    def _serialize_embedding(self, embedding: Any) -> str:
        """Serialize embedding to JSON for safe storage."""
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        return json.dumps(embedding)

    def _deserialize_embedding(self, raw: Any) -> Any:
        """Deserialize embedding from JSON."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def _generate_key(self, text: str, model: str, version: str) -> str:
        """Generate a unique hash key from the content."""
        content = f"{text}|{model}|{version}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def get(self, text: str, model: str, version: str) -> Optional[Any]:
        """
        Get a value from the cache (L1 -> L2).
        """
        key = self._generate_key(text, model, version)
        
        # 1. Check L1 (RAM)
        if key in self.l1_cache:
            # Move to end conceptually (simple LRU logic omitted for speed)
            return self.l1_cache[key]
            
        # 2. Check L2 (Disk)
        if self.conn:
            async with self._lock:
                cursor = self.conn.cursor()
                try:
                    cursor.execute(
                        "SELECT data, created_at FROM cache WHERE key = ?",
                        (key,)
                    )
                    row = cursor.fetchone()
                
                    if row:
                        data_blob, created_at = row

                        # Check TTL
                        if time.time() - created_at > self.l2_ttl_seconds:
                            # Expired
                            cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                            self.conn.commit()
                            return None

                        # Deserialize
                        try:
                            data = self._deserialize_embedding(data_blob)
                        except Exception as e:
                            cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                            self.conn.commit()
                            logger.warning(f"L2 cache decode error: {e}")
                            return None

                        # Promote to L1
                        self._add_to_l1(key, data)

                        # Update last_accessed (async or fast sync)
                        cursor.execute(
                            "UPDATE cache SET last_accessed = ? WHERE key = ?",
                            (time.time(), key)
                        )
                        self.conn.commit()

                        return data

                except Exception as e:
                    logger.warning(f"L2 cache read error: {e}")
                finally:
                    cursor.close()
                
        return None

    async def put(self, text: str, model: str, embedding: Any, version: str):
        """
        Store a value in the cache (L1 + L2).
        """
        key = self._generate_key(text, model, version)

        # Store in L1
        self._add_to_l1(key, embedding)

        # Store in L2
        if self.conn:
            async with self._lock:
                cursor = self.conn.cursor()
                try:
                    data_blob = self._serialize_embedding(embedding)
                    now = time.time()

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO cache (key, data, created_at, last_accessed)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, data_blob, now, now)
                    )
                    self.conn.commit()

                    # Check cleanup (low probability or by size)
                    # Simplified: skip cleanup on every write for performance

                except Exception as e:
                    logger.warning(f"L2 cache write error: {e}")
                finally:
                    cursor.close()

    def _add_to_l1(self, key: str, data: Any):
        """Add to L1 managing capacity."""
        if len(self.l1_cache) >= self.l1_max_size:
            # Remove the first entry (simple FIFO for now)
            # In Python 3.7+ dicts are ordered by insertion
            try:
                first_key = next(iter(self.l1_cache))
                del self.l1_cache[first_key]
            except StopIteration:
                pass
        
        self.l1_cache[key] = data

    async def clear(self):
        """Clear all cache levels."""
        self.l1_cache.clear()
        if self.conn:
            async with self._lock:
                cursor = self.conn.cursor()
                try:
                    cursor.execute("DELETE FROM cache")
                    self.conn.commit()
                    cursor.execute("VACUUM")
                except Exception as e:
                    logger.error(f"L2 cache clear error: {e}")
                finally:
                    cursor.close()

    async def shutdown(self):
        """Close resources."""
        if self.conn:
            try:
                self.conn.close()
            finally:
                self.conn = None
