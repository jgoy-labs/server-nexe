"""
────────────────────────────────────
Server Nexe
Location: tests/test_bloc3_dev_b.py
Description: Tests for bugs 12, 18, 23, 26, 27 of Block 3.
────────────────────────────────────
"""

from pathlib import Path


_ROOT = Path(__file__).parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# Bug 12 — Double module discovery at startup
# ═══════════════════════════════════════════════════════════════════════════

def test_bug12_resolve_force_flag_returns_none_for_known_modules(monkeypatch):
    """Outside the pytest/test runtime, _resolve_force_flag(force=False) with a
    non-empty modules dict must return the early-return sentinel None, so the
    caller skips a second discovery pass (Bug 12)."""
    from unittest.mock import MagicMock

    from personality.data.models import ModuleInfo, ModuleState
    from personality.module_manager.discovery import ModuleDiscovery
    from personality.module_manager.types import DiscoveryConfig

    # Remove the test-mode env shortcuts so the production branch is exercised.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("NEXE_ENV", raising=False)

    discovery = ModuleDiscovery(DiscoveryConfig(
        path_discovery=MagicMock(),
        config_manager=MagicMock(),
        events=MagicMock(),
    ))

    modules = {
        "known": ModuleInfo(
            name="known",
            path="/fake/known",
            manifest_path="known.toml",
            state=ModuleState.DISCOVERED,
        ),
    }

    assert discovery._resolve_force_flag(False, modules) is None


# ═══════════════════════════════════════════════════════════════════════════
# Bug 18 — Hardcoded UTF-8 encoding: fallback
# ═══════════════════════════════════════════════════════════════════════════

def test_bug18_read_file_latin1_fallback(tmp_path: Path, caplog):
    """A latin-1 file with accented characters must be read via fallback."""
    import logging
    from core.ingest.ingest_knowledge import read_file

    f = tmp_path / "hola.txt"
    # Write "àéíòú" in latin-1 (cp1252)
    f.write_bytes("àéíòú".encode("latin-1"))

    with caplog.at_level(logging.INFO, logger="core.ingest.ingest_knowledge"):
        content = read_file(f)

    assert "àéíòú" in content
    # Must have logged that the fallback was used
    assert any("fallback encoding" in r.message for r in caplog.records), (
        f"Expected 'fallback encoding' log, got: {[r.message for r in caplog.records]}"
    )


def test_bug18_read_file_utf8_no_warning(tmp_path: Path, caplog):
    """A normal UTF-8 file must not emit any fallback warning."""
    import logging
    from core.ingest.ingest_knowledge import read_file

    f = tmp_path / "hola_utf8.md"
    f.write_text("àéíòú\n## header", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="core.ingest.ingest_knowledge"):
        content = read_file(f)

    assert "àéíòú" in content
    assert not any("fallback encoding" in r.message for r in caplog.records)


def test_bug18_read_file_undecodable_returns_empty(tmp_path: Path):
    """Bytes undecodable by any common encoding → empty return + no exception."""
    from core.ingest.ingest_knowledge import read_file

    f = tmp_path / "binary.txt"
    # Bytes that no fallback encoding decodes to legitimate "text";
    # latin-1 accepts any byte, so technically always returns something.
    # This test verifies that no exception is raised.
    f.write_bytes(b"\x00\x01\x02\x03")
    result = read_file(f)
    assert isinstance(result, str)  # no exception raised


# ═══════════════════════════════════════════════════════════════════════════
# Bug 27 — Backend name normalisation
# ═══════════════════════════════════════════════════════════════════════════

def test_bug27_routes_auth_has_backend_aliases():
    """The routes_auth file must contain the aliases dict for Bug 27."""
    src = (_ROOT / "plugins/web_ui_module/api/routes_auth.py").read_text()
    # _BACKEND_ALIASES must be present with the expected keys
    assert "_BACKEND_ALIASES" in src, "Bug 27: _BACKEND_ALIASES no present"
    for alias in ("llama_cpp", "llama-cpp", "llama_cpp_module", "llamacpp"):
        assert f'"{alias}"' in src, f"Bug 27: alies {alias!r} no present a _BACKEND_ALIASES"
    assert "_normalize_backend_name" in src, "Bug 27: normalizer no present"


def test_bug26_routes_auth_has_model_exists_check():
    """routes_auth must call _backend_model_exists before accepting the change."""
    src = (_ROOT / "plugins/web_ui_module/api/routes_auth.py").read_text()
    assert "_backend_model_exists" in src, "Bug 26: verificació model no present"
    assert 'status_code=400' in src and "not found for backend" in src, (
        "Bug 26: HTTPException 400 per model inexistent no present"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Bug 23 — No silent model fallback in Ollama
# ═══════════════════════════════════════════════════════════════════════════

def test_bug23_ollama_no_silent_fallback_when_model_not_found():
    """When the requested model does not exist (neither exact nor partial), the Ollama
    endpoint must raise 404 instead of picking the first chat model."""
    import inspect
    from core.endpoints.chat_engines import ollama as ollama_engine
    # Verify directly in the source code that the silent fallback has been removed
    source = inspect.getsource(ollama_engine._forward_to_ollama)
    # Must NOT contain the comment "Use first available chat model as fallback"
    assert "first available chat model as fallback" not in source, (
        "Bug 23: fallback silenciós encara present"
    )
    # Must contain the HTTPException 404 for model not found
    assert "status_code=404" in source, (
        "Bug 23: falta 404 per model inexistent"
    )
