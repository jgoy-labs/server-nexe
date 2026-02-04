"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/tests/test_constants.py
Description: Tests per RAG constants.py.

www.jgoy.net
────────────────────────────────────
"""

from memory.rag.constants import (
  MANIFEST,
  MODULE_ID,
)

class TestManifest:
  """Tests for MANIFEST constant."""

  def test_manifest_is_dict(self):
    """Verify MANIFEST is a dictionary."""
    assert isinstance(MANIFEST, dict)

  def test_manifest_has_name(self):
    """Verify MANIFEST has name."""
    assert "name" in MANIFEST
    assert MANIFEST["name"] == "rag"

  def test_manifest_has_version(self):
    """Verify MANIFEST has version."""
    assert "version" in MANIFEST

  def test_manifest_has_description(self):
    """Verify MANIFEST has description."""
    assert "description" in MANIFEST
    assert len(MANIFEST["description"]) > 0

  def test_manifest_has_capabilities(self):
    """Verify MANIFEST has capabilities."""
    assert "capabilities" in MANIFEST
    assert isinstance(MANIFEST["capabilities"], list)

  def test_manifest_capabilities_not_empty(self):
    """Verify capabilities list is not empty."""
    assert len(MANIFEST["capabilities"]) > 0

  def test_manifest_has_default_config(self):
    """Verify MANIFEST has default_config."""
    assert "default_config" in MANIFEST
    assert isinstance(MANIFEST["default_config"], dict)

class TestModuleId:
  """Tests for MODULE_ID constant."""

  def test_module_id_is_string(self):
    """Verify MODULE_ID is a string."""
    assert isinstance(MODULE_ID, str)

  def test_module_id_not_empty(self):
    """Verify MODULE_ID is not empty."""
    assert len(MODULE_ID) > 0

  def test_module_id_format(self):
    """Verify MODULE_ID follows expected format."""
    assert "Nexe" in MODULE_ID or "RAG" in MODULE_ID or "{{" in MODULE_ID

class TestManifestDefaultConfig:
  """Tests for MANIFEST default_config."""

  def test_default_config_has_top_k(self):
    """Verify default_config has top_k."""
    config = MANIFEST.get("default_config", {})
    assert "top_k" in config
    assert isinstance(config["top_k"], int)
    assert config["top_k"] > 0

  def test_default_config_has_similarity_threshold(self):
    """Verify default_config has similarity_threshold."""
    config = MANIFEST.get("default_config", {})
    assert "similarity_threshold" in config
    assert isinstance(config["similarity_threshold"], (int, float))
    assert 0 <= config["similarity_threshold"] <= 1

class TestManifestCapabilities:
  """Tests for MANIFEST capabilities."""

  def test_capabilities_include_vector_search(self):
    """Verify capabilities include vector_search."""
    caps = MANIFEST.get("capabilities", [])
    assert "vector_search" in caps

  def test_capabilities_include_multi_source(self):
    """Verify capabilities include multi_rag_management or similar."""
    caps = MANIFEST.get("capabilities", [])
    has_multi = any("multi" in cap.lower() or "source" in cap.lower() for cap in caps)
    assert has_multi or len(caps) > 1
