"""
────────────────────────────────────
Server Nexe
Location: tests/onada4_mypy_plugins/test_cluster06_from_dict_missing_timestamps.py
Description: Tests cecs Onada 4.4 — Cluster 6 (session_manager.py from_dict arg-type).

Cluster 6: ChatSession.from_dict() rep dicts de sessió deserialitzats del disc.
Si el dict no té 'created_at' o 'last_activity' (sessió antiga, corrupció parcial,
o migració), datetime.fromisoformat(None) → TypeError → sessió descartada
silenciosament per _load_sessions() try/except.

Contracte post-fix (Dev#2): from_dict() NO peta amb claus absents i retorna
timestamps fallback raonables (e.g. datetime.now(timezone.utc)).

Contract pin: ChatSession.from_dict({'id': 'x'}) → cap TypeError, sessió vàlida.

Veure: nat/dev/server-nexe/diari/2026-05/20260504/onada4-mypy-plugins/02-tests.md
────────────────────────────────────
"""

import pytest
from datetime import datetime, timezone


def test_from_dict_missing_created_at_does_not_raise():
    """TDD Cluster 6: from_dict() amb 'created_at' absent NO ha de petar.

    Pre-fix: TypeError ('NoneType'). Post-fix: fallback datetime.now(utc).
    """
    from plugins.web_ui_module.core.session_manager import ChatSession

    data = {
        "id": "test-c6-no-created-at",
        "last_activity": "2026-01-01T12:00:00+00:00",
        "messages": [],
        "context_files": [],
    }
    session = ChatSession.from_dict(data)

    assert isinstance(session.created_at, datetime), (
        f"created_at ha de ser datetime post-fix, obtingut: {type(session.created_at)}"
    )
    assert session.created_at.tzinfo is not None, (
        "created_at ha de tenir timezone (aware datetime)"
    )


def test_from_dict_missing_last_activity_does_not_raise():
    """TDD Cluster 6: from_dict() amb 'last_activity' absent NO ha de petar.

    Pre-fix: TypeError. Post-fix: fallback datetime.now(utc).
    """
    from plugins.web_ui_module.core.session_manager import ChatSession

    data = {
        "id": "test-c6-no-last-activity",
        "created_at": "2026-01-01T12:00:00+00:00",
        "messages": [],
        "context_files": [],
    }
    session = ChatSession.from_dict(data)

    assert isinstance(session.last_activity, datetime), (
        f"last_activity ha de ser datetime post-fix, obtingut: {type(session.last_activity)}"
    )
    assert session.last_activity.tzinfo is not None, (
        "last_activity ha de tenir timezone (aware datetime)"
    )


def test_from_dict_complete_dict_preserved():
    """Anti-regressió Cluster 6: from_dict() amb totes les claus presents NO ha de canviar.

    Pina que el fix de Dev#2 no altera el comportament del cas normal (sessió
    correctament serialitzada). Passa pre-fix i post-fix.
    """
    from plugins.web_ui_module.core.session_manager import ChatSession

    data = {
        "id": "test-c6-complete",
        "created_at": "2026-03-15T10:30:00+00:00",
        "last_activity": "2026-03-15T11:00:00+00:00",
        "messages": [{"role": "user", "content": "hola"}],
        "context_files": ["fitxer.txt"],
        "thinking_enabled": True,
        "custom_name": "La meva sessió",
    }
    session = ChatSession.from_dict(data)

    assert session.id == "test-c6-complete"
    assert session.created_at == datetime(2026, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert session.last_activity == datetime(2026, 3, 15, 11, 0, 0, tzinfo=timezone.utc)
    assert session.messages == [{"role": "user", "content": "hola"}]
    assert session.context_files == ["fitxer.txt"]
    assert session.thinking_enabled is True
    assert session.custom_name == "La meva sessió"
