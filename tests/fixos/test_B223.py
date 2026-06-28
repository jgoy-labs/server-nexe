"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B223.py
Description: TDD fix for B223 — `nexe status` mai mostra mòduls perquè
             client.py llegeix una clau JSON inexistent.
────────────────────────────────────
"""

from unittest.mock import patch, MagicMock


def _make_client():
    """Return a NexeClient instance with a stubbed config."""
    from core.cli.client import NexeClient
    cfg = MagicMock()
    cfg.server_url = "http://localhost:11434"
    return NexeClient(config=cfg)


def test_get_status_modules_populated_from_data_modules_loaded():
    """
    B223: quan /modules retorna {status,data:{modules_loaded:[...]}},
    get_status() ha d'exposar la llista de mòduls, NO una llista buida.
    """
    client = _make_client()

    health_resp = {"status": "ok", "version": "1.2.3"}
    modules_resp = {
        "status": "ok",
        "data": {
            "modules_loaded": ["chat", "memory", "cli"],
            "total_modules_loaded": 3,
        }
    }

    with patch.object(client, "_request", side_effect=[health_resp, modules_resp]):
        result = client.get_status()

    modules = result.get("modules", [])
    assert len(modules) == 3, f"S'esperaven 3 mòduls, s'han rebut {len(modules)}: {modules}"
    names = [m["name"] for m in modules]
    assert "chat" in names
    assert "memory" in names
    assert "cli" in names


def test_get_status_modules_empty_when_data_missing():
    """
    B223 (cas de fallback): si data no conté modules_loaded (e.g. minimal_mode),
    get_status() ha de retornar llista buida sense petar.
    """
    client = _make_client()

    health_resp = {"status": "ok", "version": "1.2.3"}
    modules_resp = {"status": "ok", "data": {}}

    with patch.object(client, "_request", side_effect=[health_resp, modules_resp]):
        result = client.get_status()

    assert result.get("modules") == []
