"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/shared/cache.py
Description: Implementació de MultiLevelCache (L1 Memory + L2 SQLite).

www.jgoy.net
────────────────────────────────────
"""

import logging
import sqlite3
import json
import time
from pathlib import Path
from typing import Optional, Any, Dict, List
import hashlib
import asyncio
from personality.i18n.resolve import t_modular

# Constants de colors per logs
RED = "\033[1;31m"
RESET = "\033[0m"

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"memory.cache.{key}", fallback, **kwargs)

class MultiLevelCache:
    """
    Cache multi-nivell (L1: RAM, L2: SQLite).
    Dissenyat per emmagatzemar embeddings i reduir latència.
    """

    def __init__(
        self,
        l1_max_size: int = 1000,
        l2_max_size_gb: float = 5.0,
        l2_ttl_hours: int = 72,
        cache_dir: str = "storage/cache/embeddings"
    ):
        """
        Inicialitza el cache.
        
        Args:
            l1_max_size: Nombre màxim d'elements en RAM
            l2_max_size_gb: Tamany màxim aproximat en disc (GB)
            l2_ttl_hours: Temps de vida dels elements en disc
            cache_dir: Directori per la BBDD SQLite
        """
        self.l1_max_size = l1_max_size
        self.l2_max_size_bytes = int(l2_max_size_gb * 1024 * 1024 * 1024)
        self.l2_ttl_seconds = l2_ttl_hours * 3600
        self._lock = asyncio.Lock()
        
        # L1 Cache (Diccionari Python amb LRU simple via OrderedDict seria millor, 
        # però usarem dict + neteja simple per simplicitat)
        self.l1_cache: Dict[str, Any] = {}
        
        # L2 Cache Configuration
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "embeddings_l2.db"
        
        self._init_l2()

    def _init_l2(self):
        """Inicialitza la connexió i esquema de SQLite."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA busy_timeout = 5000")
            # Crear taula si no existeix
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data BLOB,
                    created_at REAL,
                    last_accessed REAL
                )
            """)
            
            # Índex per neteja eficient
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_accessed ON cache(last_accessed)
            """)
            
            self.conn.commit()
            cursor.close()
            
        except Exception as e:
            logger.error(
                _t(
                    "l2_init_failed",
                    "Failed to initialize L2 cache: {error}",
                    error=str(e),
                )
            )
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
        """Genera una clau única hash del contingut."""
        content = f"{text}|{model}|{version}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def get(self, text: str, model: str, version: str) -> Optional[Any]:
        """
        Obté un valor del cache (L1 -> L2).
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

                        # Comprovar TTL
                        if time.time() - created_at > self.l2_ttl_seconds:
                            # Expirat
                            cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                            self.conn.commit()
                            return None

                        # Deserialitzar
                        try:
                            data = self._deserialize_embedding(data_blob)
                        except Exception as e:
                            cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                            self.conn.commit()
                            logger.warning(
                                _t(
                                    "l2_decode_error",
                                    "L2 cache decode error: {error}",
                                    error=str(e),
                                )
                            )
                            return None

                        # Promocionar a L1
                        self._add_to_l1(key, data)

                        # Actualitzar last_accessed async (o sync ràpid)
                        cursor.execute(
                            "UPDATE cache SET last_accessed = ? WHERE key = ?",
                            (time.time(), key)
                        )
                        self.conn.commit()

                        return data

                except Exception as e:
                    logger.warning(
                        _t(
                            "l2_read_error",
                            "L2 cache read error: {error}",
                            error=str(e),
                        )
                    )
                finally:
                    cursor.close()
                
        return None

    async def put(self, text: str, model: str, embedding: Any, version: str):
        """
        Guarda un valor al cache (L1 + L2).
        """
        key = self._generate_key(text, model, version)
        
        # Guardar a L1
        self._add_to_l1(key, embedding)
        
        # Guardar a L2
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

                    # Check cleanup (probabilitat baixa o per size)
                    # Implementació simplificada: No fem cleanup a cada write per rendiment

                except Exception as e:
                    logger.warning(
                        _t(
                            "l2_write_error",
                            "L2 cache write error: {error}",
                            error=str(e),
                        )
                    )
                finally:
                    cursor.close()

    def _add_to_l1(self, key: str, data: Any):
        """Afegeix a L1 gestionant capacitat."""
        if len(self.l1_cache) >= self.l1_max_size:
            # Eliminar el primer (FIFO simple per ara)
            # En Python 3.7+ diccionaris són ordenats per inserció
            try:
                first_key = next(iter(self.l1_cache))
                del self.l1_cache[first_key]
            except StopIteration:
                pass
        
        self.l1_cache[key] = data

    async def clear(self):
        """Neteja tots els nivells de cache."""
        self.l1_cache.clear()
        if self.conn:
            async with self._lock:
                cursor = self.conn.cursor()
                try:
                    cursor.execute("DELETE FROM cache")
                    self.conn.commit()
                    cursor.execute("VACUUM")
                except Exception as e:
                    logger.error(
                        _t(
                            "l2_clear_error",
                            "L2 cache clear error: {error}",
                            error=str(e),
                        )
                    )
                finally:
                    cursor.close()

    async def shutdown(self):
        """Tanca recursos."""
        if self.conn:
            self.conn.close()
