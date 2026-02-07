"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/auth_models.py
Description: Data models for the Nexe authentication system.

www.jgoy.net
────────────────────────────────────
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class KeyStatus(str, Enum):
  """Status of an API key."""
  ACTIVE = "active"
  GRACE_PERIOD = "grace"
  EXPIRED = "expired"
  NOT_CONFIGURED = "not_configured"

@dataclass
class ApiKeyData:
  """Represents an API key with expiry metadata."""
  key: str
  expires_at: Optional[datetime] = None
  created_at: Optional[datetime] = None

  @property
  def status(self) -> KeyStatus:
    """
    Calculate current status based on expiry.

    Returns:
      KeyStatus: Current status of this key
    """
    if not self.key:
      return KeyStatus.NOT_CONFIGURED

    if self.expires_at is None:
      return KeyStatus.ACTIVE

    now = datetime.now(self.expires_at.tzinfo)

    if now < self.expires_at:
      return KeyStatus.ACTIVE
    else:
      return KeyStatus.EXPIRED

  @property
  def is_valid(self) -> bool:
    """Check if key is currently valid (active or grace period)."""
    return self.status in (KeyStatus.ACTIVE, KeyStatus.GRACE_PERIOD)

@dataclass
class ApiKeyConfig:
  """
  Configuration for dual-key authentication.

  Supports primary key (active) + secondary key (grace period during rotation).
  """
  primary: Optional[ApiKeyData] = None
  secondary: Optional[ApiKeyData] = None

  def get_valid_keys(self) -> list[ApiKeyData]:
    """
    Get all currently valid keys.

    Returns:
      List of valid ApiKeyData objects
    """
    valid = []

    if self.primary and self.primary.is_valid:
      valid.append(self.primary)

    if self.secondary and self.secondary.is_valid:
      valid.append(self.secondary)

    return valid

  @property
  def has_any_valid_key(self) -> bool:
    """Check if at least one valid key is configured."""
    if self.primary and self.primary.is_valid:
      return True
    if self.secondary and self.secondary.is_valid:
      return True
    return False

__all__ = [
  'KeyStatus',
  'ApiKeyData',
  'ApiKeyConfig',
]
