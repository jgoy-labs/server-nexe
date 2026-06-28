"""
Tests for installer/tray_alerts.py — the shared NSAlert helpers extracted from
tray.py and tray_uninstaller.py (finding B157).

The key invariant guarded here is the one the duplication hid: the rumps
fallback must be import-safe. tray.py used a module-level rumps stub while
tray_uninstaller.py did a hard `import rumps` that raised ImportError on
Linux/CI. The unified helper resolves rumps defensively and degrades to None.
"""

import sys

import pytest


def test_module_importable_without_appkit_or_rumps(monkeypatch):
    """tray_alerts must import on a host without AppKit/rumps (Linux/CI):
    all platform imports are lazy (inside the functions), nothing at top level.
    """
    # Force any import of rumps/AppKit to fail, then re-import the module fresh.
    monkeypatch.setitem(sys.modules, "rumps", None)
    monkeypatch.setitem(sys.modules, "AppKit", None)
    monkeypatch.delitem(sys.modules, "installer.tray_alerts", raising=False)

    import importlib

    mod = importlib.import_module("installer.tray_alerts")
    assert mod.NS_STATUS_WINDOW_LEVEL == 25
    assert callable(mod._front_alert)
    assert callable(mod._build_nsalert)


def test_rumps_fallback_returns_none_without_rumps(monkeypatch):
    """REGRESSION GUARD (B157): the fallback must NOT raise when rumps is
    absent. The old tray_uninstaller copy did `import rumps` unguarded, which
    raised ImportError; copying it into the shared module would reintroduce
    that bug. Setting sys.modules['rumps'] = None makes `import rumps` raise.
    """
    from installer import tray_alerts

    monkeypatch.setitem(sys.modules, "rumps", None)
    result = tray_alerts._front_alert_rumps_fallback(
        title="t", message="m", ok="OK", cancel=None, other=None
    )
    assert result is None


def test_rumps_fallback_delegates_to_rumps_alert(monkeypatch):
    """When rumps IS importable, the fallback forwards the non-None kwargs to
    rumps.alert and returns its value (behaviour preserved from both copies).
    """
    import types

    calls = {}

    fake_rumps = types.ModuleType("rumps")

    def _fake_alert(**kwargs):
        calls.update(kwargs)
        return 1

    fake_rumps.alert = _fake_alert
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)

    from installer import tray_alerts

    out = tray_alerts._front_alert_rumps_fallback(
        title="t", message=None, ok="OK", cancel="Cancel", other=None
    )
    assert out == 1
    # Only the non-None args are forwarded.
    assert calls == {"title": "t", "ok": "OK", "cancel": "Cancel"}


@pytest.mark.parametrize(
    "response,expected",
    [(1000, 1), (1001, 0), (1002, -1), (42, 42)],
)
def test_nsalert_response_to_int_mapping(response, expected):
    """Guards the NSAlert button-code → rumps-compat int mapping (1/0/-1)."""
    from installer import tray_alerts

    assert tray_alerts._nsalert_response_to_int(response) == expected
