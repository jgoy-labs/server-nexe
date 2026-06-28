"""
────────────────────────────────────
Server Nexe
Location: installer/tray_alerts.py
Description: Shared macOS NSAlert helpers for the tray apps (installer/tray.py
             and installer/tray_uninstaller.py). Extracted to remove the
             duplicated alert/foreground logic (finding B157).

             All AppKit/rumps imports are LAZY (inside the functions) so this
             module stays importable on Linux/CI where neither is available.
             The rumps fallback resolves rumps defensively and degrades to
             None instead of raising when neither AppKit nor rumps exist —
             previously the two copies diverged here: tray.py used a
             module-level rumps stub, while tray_uninstaller.py did a hard
             `import rumps` that raised ImportError on Linux/CI.
────────────────────────────────────
"""

NS_STATUS_WINDOW_LEVEL = 25  # above any normal app window


class _ForegroundContext:
    """Context manager that promotes the tray to .regular for an entire alert
    flow and restores the previous activation policy on exit. Done ONCE per
    flow to avoid interfering with the modal event loop between alerts (the
    cause of alerts being 'skipped' — activation policy flip-flop).
    """
    def __init__(self):
        self.old_policy = None

    def __enter__(self):
        try:
            from AppKit import NSApp, NSApplicationActivationPolicyRegular
            self.old_policy = NSApp.activationPolicy()
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:  # nosec B110: best-effort AppKit activation policy promotion; non-fatal if AppKit unavailable
            pass
        return self

    def __exit__(self, *exc):
        if self.old_policy is not None:
            try:
                from AppKit import NSApp
                NSApp.setActivationPolicy_(self.old_policy)
            except Exception:  # nosec B110: best-effort AppKit activation policy restore on context exit; non-fatal
                pass


def _front_alert_rumps_fallback(title, message, ok, cancel, other):
    """Fallback path when AppKit is unavailable: delegate to rumps.alert.

    rumps is imported lazily and defensively: on a host without rumps (e.g.
    Linux/CI) this returns None instead of raising, keeping callers robust.
    """
    try:
        import rumps
    except ImportError:
        return None
    kwargs = {}
    if title is not None:
        kwargs["title"] = title
    if message is not None:
        kwargs["message"] = message
    if ok is not None:
        kwargs["ok"] = ok
    if cancel is not None:
        kwargs["cancel"] = cancel
    if other is not None:
        kwargs["other"] = other
    return rumps.alert(**kwargs)


def _build_nsalert(title, message, ok, cancel, other):
    """Construct and configure an NSAlert with buttons."""
    from AppKit import NSAlert, NSAlertStyleWarning
    alert = NSAlert.alloc().init()
    if title is not None:
        alert.setMessageText_(str(title))
    if message is not None:
        alert.setInformativeText_(str(message))
    alert.setAlertStyle_(NSAlertStyleWarning)
    alert.addButtonWithTitle_(str(ok) if ok is not None else "OK")
    if cancel is not None:
        alert.addButtonWithTitle_(str(cancel))
    if other is not None:
        alert.addButtonWithTitle_(str(other))
    return alert


def _nsalert_response_to_int(response):
    """Convert NSAlertFirstButtonReturn=1000, Second=1001, Third=1002 to ints."""
    if response == 1000:
        return 1
    elif response == 1001:
        return 0
    elif response == 1002:
        return -1
    return response


def _front_alert(title=None, message=None, ok=None, cancel=None, other=None, **_):
    """Show an always-on-top NSAlert.

    Assumes activation policy is ALREADY promoted to .regular (via
    _ForegroundContext in the caller). Only raises window level and calls
    runModal. Return compat with rumps: 1 (OK) / 0 (Cancel) / -1 (Other).
    """
    try:
        alert = _build_nsalert(title, message, ok, cancel, other)
    except Exception:
        return _front_alert_rumps_fallback(title, message, ok, cancel, other)

    window = alert.window()
    window.setLevel_(NS_STATUS_WINDOW_LEVEL)
    window.makeKeyAndOrderFront_(None)

    return _nsalert_response_to_int(alert.runModal())
