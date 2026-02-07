"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/scanner.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

try:
  import tomllib
except ImportError:
  import tomli as tomllib

from .protocol import ModuleMetadata, SpecialistInfo
from personality.i18n.resolve import resolve_i18n_string, resolve_i18n_tree
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"core.loader_scanner.{key}", fallback, **kwargs)

@dataclass
class ModuleDiscovery:
  """
  Result of module discovery.

  Contains all information extracted from manifest.toml
  needed to load the module.
  """
  metadata: ModuleMetadata
  manifest_path: Path

  entry_class: str = ""
  entry_module: str = ""

  router_path: Optional[str] = None
  router_prefix: Optional[str] = None

  health_function: Optional[str] = None

  outgoing_specialists: List[SpecialistInfo] = field(default_factory=list)
  incoming_specialist_types: List[str] = field(default_factory=list)

  cli_alias: Optional[str] = None
  cli_entry: Optional[str] = None
  cli_commands: List[str] = field(default_factory=list)

  raw_data: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> Dict[str, Any]:
    """Convert to a dictionary for serialization."""
    return {
      "name": self.metadata.name,
      "version": self.metadata.version,
      "description": self.metadata.description,
      "manifest_path": str(self.manifest_path),
      "entry_class": self.entry_class,
      "entry_module": self.entry_module,
      "router_prefix": self.router_prefix,
      "has_health": self.health_function is not None,
      "has_cli": self.cli_alias is not None,
      "specialists_out": len(self.outgoing_specialists),
      "specialists_in": self.incoming_specialist_types,
    }

class ModuleScanner:
  """
  Scan the file system looking for Nexe modules.

  Finds manifest.toml files in configured directories
  and extracts the information needed to load each module.
  """

  DEFAULT_SCAN_PATHS = [
    "plugins",
    "memory",
    "personality",
    "core",
  ]

  def __init__(
    self,
    base_path: Optional[Path] = None,
    scan_paths: Optional[List[str]] = None
  ):
    """
    Initialize the scanner.

    Args:
      base_path: Project root directory
      scan_paths: List of subdirectories to scan
    """
    if base_path is None:
      base_path = Path(__file__).parent.parent.parent

    self.base_path = Path(base_path)
    self.scan_paths = scan_paths or self.DEFAULT_SCAN_PATHS

    logger.info(_t(
      "initialized",
      "ModuleScanner initialized - base={base}, paths={paths}",
      base=self.base_path,
      paths=self.scan_paths
    ))

  def scan(self) -> List[ModuleDiscovery]:
    """
    Scan all configured directories.

    Returns:
      List of ModuleDiscovery with found modules
    """
    discoveries = []

    for scan_path in self.scan_paths:
      full_path = self.base_path / scan_path
      if full_path.exists():
        discoveries.extend(self._scan_directory(full_path))

    logger.info(_t(
      "scan_complete",
      "Scan complete - found {count} modules",
      count=len(discoveries)
    ))
    return discoveries

  def scan_path(self, path: Path) -> List[ModuleDiscovery]:
    """
    Scan a specific directory.

    Args:
      path: Directory to scan

    Returns:
      List of ModuleDiscovery
    """
    if not path.exists():
      logger.warning(_t(
        "path_missing",
        "Path does not exist: {path}",
        path=path
      ))
      return []

    return self._scan_directory(path)

  def _scan_directory(self, directory: Path) -> List[ModuleDiscovery]:
    """
    Recursively scan a directory for manifest.toml.

    Args:
      directory: Directory to scan

    Returns:
      List of discovered modules
    """
    discoveries = []

    for manifest_path in directory.rglob("manifest.toml"):
      try:
        discovery = self._parse_manifest(manifest_path)
        if discovery:
          discoveries.append(discovery)
          logger.debug(
            _t(
              "discovered",
              "Discovered module: {module} at {path}",
              module=discovery.metadata.name,
              path=manifest_path
            )
          )
      except Exception as e:
        logger.error(_t(
          "manifest_parse_failed",
          "Failed to parse manifest {path}: {error}",
          path=manifest_path,
          error=str(e)
        ))

    return discoveries

  def _parse_manifest(self, manifest_path: Path) -> Optional[ModuleDiscovery]:
    """
    Parse a manifest.toml file.

    Args:
      manifest_path: Path to the manifest.toml file

    Returns:
      ModuleDiscovery or None if the manifest is invalid
    """
    with open(manifest_path, "rb") as f:
      data = tomllib.load(f)
    data = resolve_i18n_tree(data)

    module_section = data.get("module", {})
    if not module_section:
      logger.warning(_t(
        "missing_module_section",
        "No [module] section in {path}",
        path=manifest_path
      ))
      return None

    name = module_section.get("name")
    if not name:
      logger.warning(_t(
        "missing_module_name",
        "No module name in {path}",
        path=manifest_path
      ))
      return None

    metadata = ModuleMetadata(
      name=name,
      version=module_section.get("version", "0.0.0"),
      description=resolve_i18n_string(module_section.get("description", "")),
      author=module_section.get("author", ""),
      license=module_section.get("license", "AGPL-3.0"),
      module_type=module_section.get("type", "module"),
      quadrant=module_section.get("quadrant", "core"),
      dependencies=module_section.get("dependencies", []),
      tags=module_section.get("tags", []),
      manifest_path=str(manifest_path),
    )

    discovery = ModuleDiscovery(
      metadata=metadata,
      manifest_path=manifest_path,
      raw_data=data
    )

    entry = module_section.get("entry", {})
    if entry:
      discovery.entry_class = entry.get("class", "")
      discovery.entry_module = entry.get("module", "")
      discovery.router_path = entry.get("router")
      discovery.health_function = entry.get("health")

    if not discovery.entry_module and discovery.entry_class:
      discovery.entry_module = self._infer_module_path(manifest_path)

    router = module_section.get("router", {})
    if router:
      discovery.router_path = router.get("path", discovery.router_path)
      discovery.router_prefix = router.get("prefix", f"/{name}")

    specialists = module_section.get("specialists", {})
    if specialists:
      for spec in specialists.get("outgoing", []):
        discovery.outgoing_specialists.append(SpecialistInfo(
          name=spec.get("name", ""),
          specialist_type=spec.get("type", ""),
          file_path=spec.get("file", ""),
          target_module=spec.get("target")
        ))

      discovery.incoming_specialist_types = specialists.get("incoming", [])

    cli = module_section.get("cli", {})
    if cli:
      discovery.cli_alias = cli.get("alias") or cli.get("command_name")
      discovery.cli_entry = cli.get("entry_point")
      discovery.cli_commands = cli.get("commands", [])

    return discovery

  def _infer_module_path(self, manifest_path: Path) -> str:
    """
    Infer the Python module path from the manifest path.

    Args:
      manifest_path: Path to manifest.toml

    Returns:
      String with the Python module (ex: "plugins.security.module")
    """
    try:
      relative = manifest_path.parent.relative_to(self.base_path)

      module_path = str(relative).replace(os.sep, ".")

      module_file = manifest_path.parent / "module.py"
      if module_file.exists():
        module_path = f"{module_path}.module"

      return module_path
    except ValueError:
      return ""

def scan_modules(base_path: Optional[Path] = None) -> List[ModuleDiscovery]:
  """
  Helper function to scan modules.

  Args:
    base_path: Root directory (optional)

  Returns:
    List of discovered modules
  """
  scanner = ModuleScanner(base_path)
  return scanner.scan()

def discover_module(manifest_path: Path) -> Optional[ModuleDiscovery]:
  """
  Discover a single module from its manifest.

  Args:
    manifest_path: Path to manifest.toml

  Returns:
    ModuleDiscovery or None
  """
  scanner = ModuleScanner()
  return scanner._parse_manifest(manifest_path)
