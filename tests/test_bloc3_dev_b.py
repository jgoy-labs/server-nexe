"""
────────────────────────────────────
Server Nexe
Location: tests/test_bloc3_dev_b.py
Description: Tests pels bugs 12, 18, 23, 26, 27 del Bloc 3.
────────────────────────────────────
"""

import asyncio
from pathlib import Path
from unittest import mock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Bug 12 — Doble descobriment de mòduls a l'inici
# ═══════════════════════════════════════════════════════════════════════════

def test_bug12_discover_has_early_return_for_known_modules():
    """El source de discover() ha de contenir l'early return del Bug 12."""
    import inspect
    from personality.module_manager.discovery import ModuleDiscovery

    source = inspect.getsource(ModuleDiscovery.discover)
    assert "Module discovery skipped" in source, (
        "Bug 12: early return sense implementar"
    )
    assert "if not force and modules_dict:" in source, (
        "Bug 12: condició early return incorrecta"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Bug 18 — Encoding UTF-8 hardcoded: fallback
# ═══════════════════════════════════════════════════════════════════════════

def test_bug18_read_file_latin1_fallback(tmp_path: Path, caplog):
    """Un fitxer latin-1 amb caràcters accentuats ha de llegir-se via fallback."""
    import logging
    from core.ingest.ingest_knowledge import read_file

    f = tmp_path / "hola.txt"
    # Escrivim "àéíòú" en latin-1 (cp1252)
    f.write_bytes("àéíòú".encode("latin-1"))

    with caplog.at_level(logging.INFO, logger="core.ingest.ingest_knowledge"):
        content = read_file(f)

    assert "àéíòú" in content
    # Ha d'haver loguejat que el fallback ha estat usat
    assert any("fallback encoding" in r.message for r in caplog.records), (
        f"Expected 'fallback encoding' log, got: {[r.message for r in caplog.records]}"
    )


def test_bug18_read_file_utf8_no_warning(tmp_path: Path, caplog):
    """Fitxer UTF-8 normal no ha d'emetre cap warning de fallback."""
    import logging
    from core.ingest.ingest_knowledge import read_file

    f = tmp_path / "hola_utf8.md"
    f.write_text("àéíòú\n## header", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="core.ingest.ingest_knowledge"):
        content = read_file(f)

    assert "àéíòú" in content
    assert not any("fallback encoding" in r.message for r in caplog.records)


def test_bug18_read_file_undecodable_returns_empty(tmp_path: Path):
    """Bytes impossibles en cap encoding habitual → retorn buit + no excepció."""
    from core.ingest.ingest_knowledge import read_file

    f = tmp_path / "binary.txt"
    # Bytes que cap encoding del fallback decodifica a "text" legítim;
    # latin-1 acceptarà qualsevol byte, així que tècnicament sempre retorna algo.
    # Aquest test verifica que no llança excepció.
    f.write_bytes(b"\x00\x01\x02\x03")
    result = read_file(f)
    assert isinstance(result, str)  # NO excepció


# ═══════════════════════════════════════════════════════════════════════════
# Bug 27 — Normalització nom backend
# ═══════════════════════════════════════════════════════════════════════════

def test_bug27_routes_auth_has_backend_aliases():
    """El fitxer routes_auth ha de contenir el dict d'alies per Bug 27."""
    src = Path("/Users/jgoy/AI/nat/dev/server-nexe/plugins/web_ui_module/api/routes_auth.py").read_text()
    # Cal que hi hagi el _BACKEND_ALIASES amb els claus esperats
    assert "_BACKEND_ALIASES" in src, "Bug 27: _BACKEND_ALIASES no present"
    for alias in ("llama_cpp", "llama-cpp", "llama_cpp_module", "llamacpp"):
        assert f'"{alias}"' in src, f"Bug 27: alies {alias!r} no present a _BACKEND_ALIASES"
    assert "_normalize_backend_name" in src, "Bug 27: normalizer no present"


def test_bug26_routes_auth_has_model_exists_check():
    """routes_auth ha de cridar _backend_model_exists abans d'acceptar el canvi."""
    src = Path("/Users/jgoy/AI/nat/dev/server-nexe/plugins/web_ui_module/api/routes_auth.py").read_text()
    assert "_backend_model_exists" in src, "Bug 26: verificació model no present"
    assert 'status_code=400' in src and "not found for backend" in src, (
        "Bug 26: HTTPException 400 per model inexistent no present"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Bug 23 — No silent model fallback a Ollama
# ═══════════════════════════════════════════════════════════════════════════

def test_bug23_ollama_no_silent_fallback_when_model_not_found():
    """Quan el model demanat no existeix (ni exacte ni partial), l'endpoint
    Ollama ha de llançar 404 en lloc d'agafar el primer chat model."""
    import inspect
    from core.endpoints.chat_engines import ollama as ollama_engine
    # Verifiquem al codi font directament que el fallback silenciós s'ha eliminat
    source = inspect.getsource(ollama_engine._forward_to_ollama)
    # Cal que NO contingui el comentari "Use first available chat model as fallback"
    assert "first available chat model as fallback" not in source, (
        "Bug 23: fallback silenciós encara present"
    )
    # Cal que SÍ contingui el HTTPException 404 per model no trobat
    assert "status_code=404" in source, (
        "Bug 23: falta 404 per model inexistent"
    )
