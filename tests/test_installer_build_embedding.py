"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_build_embedding.py
Description: Smoke tests for installer/build-embedding-bundle.sh — the script
             that pre-downloads the default fastembed model into
             InstallNexe.app/Contents/Resources/embeddings/ so the client
             starts with RAG working offline from the first boot.

             These tests do NOT download the model (slow + network). They
             verify: file existence, executable bit, bash syntax, and the
             coherence between the model name in the script and the SSOT
             constant at memory/embeddings/constants.py.
────────────────────────────────────
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "installer" / "build-embedding-bundle.sh"
_CONSTANTS = _ROOT / "memory" / "embeddings" / "constants.py"


# ═══════════════════════════════════════════════════════════════════════
# Existence and executable bit
# ═══════════════════════════════════════════════════════════════════════


def test_build_embedding_script_exists() -> None:
    assert _SCRIPT.exists(), f"Build script missing: {_SCRIPT}"
    assert _SCRIPT.is_file()


def test_build_embedding_script_is_executable() -> None:
    import os

    assert os.access(_SCRIPT, os.X_OK), f"Script not executable: {_SCRIPT}"


# ═══════════════════════════════════════════════════════════════════════
# Bash syntax
# ═══════════════════════════════════════════════════════════════════════


def test_build_embedding_script_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n failed:\nstderr: {result.stderr}"
    )


# ═══════════════════════════════════════════════════════════════════════
# SSOT coherence — the model name must match memory/embeddings/constants.py
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def script_content() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def embedding_model_from_constants() -> str:
    """Extract DEFAULT_EMBEDDING_MODEL from memory/embeddings/constants.py."""
    text = _CONSTANTS.read_text(encoding="utf-8")
    match = re.search(r'DEFAULT_EMBEDDING_MODEL\s*=\s*["\']([^"\']+)["\']', text)
    assert match is not None, (
        "Could not find DEFAULT_EMBEDDING_MODEL in memory/embeddings/constants.py"
    )
    return match.group(1)


def test_build_embedding_model_matches_ssot(
    script_content: str, embedding_model_from_constants: str
) -> None:
    """build-embedding-bundle.sh must download the same model that runtime uses.
    If code SSOT changes, this test fails and reminds us to update the script."""
    assert embedding_model_from_constants in script_content, (
        f"Script bundles a different model than runtime. "
        f"constants.py says {embedding_model_from_constants!r} but the "
        f"script does not reference it."
    )


# ═══════════════════════════════════════════════════════════════════════
# Critical constants — regression guards
# ═══════════════════════════════════════════════════════════════════════


def test_build_embedding_target_dir_inside_app_bundle(script_content: str) -> None:
    """Output must land where build_dmg.sh and installer_setup_env.py expect."""
    assert "InstallNexe.app" in script_content
    assert 'EMBEDDINGS_DIR="$RESOURCES/embeddings"' in script_content


def test_build_embedding_uses_temporary_venv(script_content: str) -> None:
    """Script must not pollute the host Python environment."""
    assert "mktemp" in script_content
    assert "venv" in script_content
    assert "trap" in script_content  # cleanup on exit


def test_build_embedding_installs_fastembed(script_content: str) -> None:
    """The temp venv must install fastembed to download the model."""
    assert "fastembed" in script_content


def test_build_embedding_validates_artefacts(script_content: str) -> None:
    """Script must check the model was actually downloaded (ONNX + tokenizer + config)."""
    assert "model*.onnx" in script_content or "model.onnx" in script_content
    assert "tokenizer.json" in script_content
    assert "config.json" in script_content


def test_build_embedding_has_size_sanity_check(script_content: str) -> None:
    """Fail if bundle is obviously too small (download failed silently)."""
    assert "SIZE_MB" in script_content
    assert "-lt 300" in script_content  # fail if <300 MB


def test_build_embedding_has_safe_bash_flags(script_content: str) -> None:
    assert "set -euo pipefail" in script_content
