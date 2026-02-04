"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/config.py
Description: Configuració del CLI Central Nexe.

www.jgoy.net
────────────────────────────────────
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
  import yaml
except ImportError:
  yaml = None

DEFAULT_SERVER_URL = "http://localhost:9119"
DEFAULT_TIMEOUT = 30
DEFAULT_VERIFY_SSL = False

@dataclass
class NexeConfig:
  """
  Configuració del CLI Nexe.

  Cerca config a:
  1. ~/.nexe/config.yaml
  2. Variables d'entorn NEXE_*
  3. Defaults
  """

  server_url: str = DEFAULT_SERVER_URL
  timeout: int = DEFAULT_TIMEOUT
  verify_ssl: bool = DEFAULT_VERIFY_SSL
  color: bool = True
  verbose: bool = False

  extra: Dict[str, Any] = field(default_factory=dict)

  def __post_init__(self):
    """Load config from file and environment."""
    self._load_from_file()
    self._load_from_env()

  def _get_config_path(self) -> Path:
    """Get path to config file."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
      return Path(xdg_config) / "nexe" / "config.yaml"

    return Path.home() / ".nexe" / "config.yaml"

  def _load_from_file(self) -> None:
    """Load config from YAML file if exists."""
    config_path = self._get_config_path()

    if not config_path.exists():
      return

    if yaml is None:
      return

    try:
      with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

      server = data.get("server", {})
      if "url" in server:
        self.server_url = server["url"]
      if "timeout" in server:
        self.timeout = int(server["timeout"])
      if "verify_ssl" in server:
        self.verify_ssl = bool(server["verify_ssl"])

      cli = data.get("cli", {})
      if "color" in cli:
        self.color = bool(cli["color"])
      if "verbose" in cli:
        self.verbose = bool(cli["verbose"])

      self.extra = data

    except Exception as e:
      logger.debug("Failed to load CLI config: %s", e)

  def _load_from_env(self) -> None:
    """Load config from environment variables."""
    if url := os.environ.get("NEXE_SERVER_URL"):
      self.server_url = url

    if timeout := os.environ.get("NEXE_TIMEOUT"):
      try:
        self.timeout = int(timeout)
      except ValueError:
        pass

    if verify := os.environ.get("NEXE_VERIFY_SSL"):
      self.verify_ssl = verify.lower() in ("1", "true", "yes")

    if color := os.environ.get("NEXE_COLOR"):
      self.color = color.lower() in ("1", "true", "yes")

    if os.environ.get("NO_COLOR"):
      self.color = False

  def save(self) -> bool:
    """
    Save current config to file.

    Returns:
      True if saved successfully
    """
    if yaml is None:
      return False

    config_path = self._get_config_path()

    try:
      config_path.parent.mkdir(parents=True, exist_ok=True)

      data = {
        "server": {
          "url": self.server_url,
          "timeout": self.timeout,
          "verify_ssl": self.verify_ssl,
        },
        "cli": {
          "color": self.color,
          "verbose": self.verbose,
        },
      }

      data.update(self.extra)

      with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)

      return True

    except Exception:
      return False

  def to_dict(self) -> dict:
    """Convert to dictionary."""
    return {
      "server_url": self.server_url,
      "timeout": self.timeout,
      "verify_ssl": self.verify_ssl,
      "color": self.color,
      "verbose": self.verbose,
    }

_config_instance: Optional[NexeConfig] = None

def get_config() -> NexeConfig:
  """Get singleton config instance."""
  global _config_instance
  if _config_instance is None:
    _config_instance = NexeConfig()
  return _config_instance