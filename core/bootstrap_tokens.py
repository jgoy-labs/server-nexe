"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/bootstrap_tokens.py
Description: Nexe Server Component

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import secrets
import threading
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)

class BootstrapTokenManager:
  """
  Manage ephemeral post-bootstrap session tokens with SQLite persistence.

  Supports multiple workers (multiprocess) via persistent DB.
  The client receives a temporary session_token that can be used to:
  1. Complete initial configuration
  2. Generate its own permanent API key
  """

  _instance: Optional['BootstrapTokenManager'] = None
  _lock = threading.Lock()
  _db_path: Optional[Path] = None
  _initialized: bool = False

  def __new__(cls) -> 'BootstrapTokenManager':
    """Return the singleton instance, creating it on first call."""
    with cls._lock:
      if cls._instance is None:
        cls._instance = super().__new__(cls)
        cls._instance._db_path = None
        cls._instance._initialized = False
    return cls._instance

  def initialize_on_startup(self, project_root: Path):
    """Initialize the persistent token database."""
    if self._initialized:
      return

    storage_dir = project_root / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    self._db_path = storage_dir / "system_core.db"

    conn = sqlite3.connect(str(self._db_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS session_tokens (
        token TEXT PRIMARY KEY,
        expires REAL NOT NULL
      )
    """)
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS bootstrap_config (
        key TEXT PRIMARY KEY,
        value TEXT,
        expires REAL
      )
    """)
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS bootstrap_attempts (
        ip TEXT NOT NULL,
        ts REAL NOT NULL
      )
    """)
    conn.commit()
    conn.close()
    
    self._initialized = True
    logger.info("BootstrapTokenManager initialized with persistent storage: %s", self._db_path)  # nosemgrep: python-logger-credential-disclosure

  def _get_conn(self):
    """Open a SQLite connection to the token database, auto-initializing if needed."""
    if not self._initialized:
      # prefer SidecarConfig.data_dir / get_repo_root() over the
      # arbitrary cwd when initialize_on_startup() was skipped. The cwd
      # of a Tauri-spawned sidecar is the user's home (or `/`), which
      # would write the token DB to a random place.
      fallback_root = None
      try:
        from core.sidecar_config import get_sidecar_config
        cfg = get_sidecar_config()
        if cfg.is_sidecar and getattr(cfg, "data_dir", None):
          fallback_root = Path(cfg.data_dir)
      except Exception as exc:
        logger.debug(  # nosemgrep: python-logger-credential-disclosure
          "F2.6: SidecarConfig unavailable in BootstrapTokenManager._get_conn: %s",
          exc,
        )
      if fallback_root is None:
        try:
          from core.paths.detection import get_repo_root
          fallback_root = get_repo_root()
        except Exception as exc:
          logger.debug(
            "F2.6: get_repo_root() unavailable in BootstrapTokenManager._get_conn, "
            "falling back to Path.cwd(): %s",
            exc,
          )
          fallback_root = Path.cwd()
      self.initialize_on_startup(fallback_root)
    return sqlite3.connect(str(self._db_path))

  def create_session_token(self, ttl_seconds: int = 900) -> str:
    """Create an ephemeral session token and store it in the DB."""
    token = secrets.token_urlsafe(32)
    expires_dt = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    expires_ts = expires_dt.timestamp()

    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute("INSERT INTO session_tokens (token, expires) VALUES (?, ?)", (token, expires_ts))
      conn.commit()
      self._cleanup_expired(conn)
    finally:
      conn.close()

    logger.info("Session token created (persistent), expires in %d seconds", ttl_seconds)
    return token

  def validate_session_token(self, token: str) -> bool:
    """Validate whether the session token exists in the DB and has not expired."""
    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute("SELECT expires FROM session_tokens WHERE token = ?", (token,))
      row = cursor.fetchone()
      
      if row is None:
        logger.warning("Session token not found in DB")
        return False
        
      expires_ts = row[0]
      if datetime.now(timezone.utc).timestamp() > expires_ts:
        cursor.execute("DELETE FROM session_tokens WHERE token = ?", (token,))
        conn.commit()
        logger.warning("Session token expired in DB")
        return False
        
      return True
    finally:
      conn.close()

  def invalidate_token(self, token: str) -> None:
    """Invalidate a token by removing it from the DB."""
    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute("DELETE FROM session_tokens WHERE token = ?", (token,))
      conn.commit()
      logger.info("Session token invalidated in DB")
    finally:
      conn.close()

  def _cleanup_expired(self, conn: sqlite3.Connection) -> None:
    """Remove expired tokens from the DB."""
    now_ts = datetime.now(timezone.utc).timestamp()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM session_tokens WHERE expires < ?", (now_ts,))
    if cursor.rowcount > 0:
      logger.debug("Cleaned up %d expired session tokens from DB", cursor.rowcount)

  # --- Master Bootstrap Token Methods ---

  def set_bootstrap_token(self, token: str, ttl_minutes: int = 30) -> None:
    """Store the initial bootstrap token in the DB."""
    expires_ts = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).timestamp()
    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute(
        "INSERT OR REPLACE INTO bootstrap_config (key, value, expires) VALUES (?, ?, ?)",
        ("master_token", token, expires_ts)
      )
      # Reset used status
      cursor.execute(
        "INSERT OR REPLACE INTO bootstrap_config (key, value) VALUES (?, ?)",
        ("token_used", "0")
      )
      conn.commit()
    finally:
      conn.close()
    logger.info("Master bootstrap token stored in DB (expires in %d min)", ttl_minutes)

  def get_bootstrap_token(self) -> Optional[Dict[str, Any]]:
    """Retrieve the active bootstrap token."""
    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute("SELECT value, expires FROM bootstrap_config WHERE key = 'master_token'")
      row = cursor.fetchone()
      if not row:
        return None
      
      cursor.execute("SELECT value FROM bootstrap_config WHERE key = 'token_used'")
      used_row = cursor.fetchone()
      used = (used_row[0] == "1") if used_row else False
      
      return {"token": row[0], "expires": row[1], "used": used}
    finally:
      conn.close()

  def validate_master_bootstrap(self, token: str) -> bool:
    """Validate the bootstrap token against the DB."""
    now_ts = datetime.now(timezone.utc).timestamp()

    # Atomic single-use update guarded by token + expiry.
    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute(
        """
        UPDATE bootstrap_config
        SET value = '1'
        WHERE key = 'token_used'
          AND value = '0'
          AND EXISTS (
            SELECT 1 FROM bootstrap_config
            WHERE key = 'master_token'
              AND value = ?
              AND expires > ?
          )
        """,
        (token, now_ts)
      )
      conn.commit()
      if cursor.rowcount > 0:
        return True
    finally:
      conn.close()

    info = self.get_bootstrap_token()
    if not info:
      return False

    if info["used"]:
      logger.warning("Master bootstrap token already used (persistent check)")
      return False

    if now_ts > info["expires"]:
      logger.warning("Master bootstrap token expired (persistent check)")
      return False

    if token == info["token"]:
      logger.warning("Master bootstrap token already used (atomic check)")
      return False

    return False

  def check_bootstrap_rate_limit(
    self,
    client_ip: str,
    window_seconds: int = 300,
    global_limit: int = 10,
    ip_limit: int = 3
  ) -> str:
    """
    Check shared bootstrap rate limits.

    Returns:
      "ok" if allowed, "global" if global limit hit, "ip" if IP limit hit.
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - window_seconds

    conn = self._get_conn()
    try:
      cursor = conn.cursor()
      cursor.execute("DELETE FROM bootstrap_attempts WHERE ts < ?", (cutoff,))

      cursor.execute("SELECT COUNT(*) FROM bootstrap_attempts")
      global_count = cursor.fetchone()[0]
      if global_count >= global_limit:
        conn.commit()
        return "global"

      cursor.execute("SELECT COUNT(*) FROM bootstrap_attempts WHERE ip = ?", (client_ip,))
      ip_count = cursor.fetchone()[0]
      if ip_count >= ip_limit:
        conn.commit()
        return "ip"

      cursor.execute(
        "INSERT INTO bootstrap_attempts (ip, ts) VALUES (?, ?)",
        (client_ip, now_ts)
      )
      conn.commit()
      return "ok"
    finally:
      conn.close()

_manager = BootstrapTokenManager()

def initialize_tokens(project_root: Path):
  """External initialization of the manager."""
  _manager.initialize_on_startup(project_root)

def set_bootstrap_token(token: str, ttl_minutes: int = 30):
  """Store a bootstrap token with the given TTL (default 30 min)."""
  _manager.set_bootstrap_token(token, ttl_minutes)

def get_bootstrap_token() -> Optional[Dict[str, Any]]:
  """Retrieve the current bootstrap token record, or ``None`` if expired/absent."""
  return _manager.get_bootstrap_token()

def validate_master_bootstrap(token: str) -> bool:
  """Validate a master bootstrap token against the stored value."""
  return _manager.validate_master_bootstrap(token)

def check_bootstrap_rate_limit(
  client_ip: str,
  window_seconds: int = 300,
  global_limit: int = 10,
  ip_limit: int = 3
) -> str:
  """Check bootstrap rate limits and return 'allowed', 'global_exceeded', or 'ip_exceeded'."""
  return _manager.check_bootstrap_rate_limit(client_ip, window_seconds, global_limit, ip_limit)

def create_session_token(ttl_seconds: int = 900) -> str:
  """Create an ephemeral session token valid for *ttl_seconds*."""
  return _manager.create_session_token(ttl_seconds)

def validate_session_token(token: str) -> bool:
  """Return ``True`` if the session token exists and has not expired."""
  return _manager.validate_session_token(token)

def invalidate_token(token: str) -> None:
  """Remove a session token from the database."""
  _manager.invalidate_token(token)
