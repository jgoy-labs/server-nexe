"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/tests/test_constants.py
Description: Tests for RAG constants.py.

www.jgoy.net · https://server-nexe.org
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
    assert MODULE_ID == "rag" or "Nexe" in MODULE_ID or "RAG" in MODULE_ID

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

  def test_capabilities_reflect_retired_surface(self):
    """WS6-01/02: the standalone /rag surface (keyword_search substring
    matcher, temp_upload_rag, catalog_rag) was retired. The manifest must
    advertise only the surviving PersonalityRAG source and must never
    over-claim vector_search (B114: it was never vector search)."""
    caps = MANIFEST.get("capabilities", [])
    assert "personality_rag" in caps
    assert "vector_search" not in caps
    # The retired substring/upload/catalog capabilities must be gone.
    for retired in ("keyword_search", "temp_upload_rag", "catalog_rag"):
      assert retired not in caps, f"retired capability still advertised: {retired}"
