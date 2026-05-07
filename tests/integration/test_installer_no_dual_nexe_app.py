"""
Integration tests for installer/install_headless.py — Fix bug #19d.

Goal: the installer must NOT create a residual `/Applications/Nexe.app`.
The only legitimate installation is `<install_dir>/Nexe.app`. Dock and Login
Items point there.

Regression protection: if someone puts the copy back in /Applications,
these tests will fail.
"""

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from installer import install_headless


class TestInstallerDoesNotCopyToApplications:

    def test_source_has_no_copy_to_applications_nexe_app(self):
        """Static protection: no line of production code in install_headless
        should copy Nexe.app to `/Applications/Nexe.app`."""
        src = inspect.getsource(install_headless)
        # Pattern: `copytree(..., Path("/Applications/Nexe.app"))` or `/Applications/Nexe.app` as destination
        problematic_patterns = [
            r'copytree\s*\([^,]+,\s*[^)]*"/Applications/Nexe\.app"',
            r'nexe_app_dest\s*=\s*Path\s*\(\s*"/Applications/Nexe\.app"\s*\)',
        ]
        for pat in problematic_patterns:
            assert not re.search(pat, src), (
                f"REGRESSIÓ: patró prohibit detectat al source: {pat!r}. "
                "Bug #19d: installer NO pot tornar a duplicar Nexe.app a /Applications."
            )

    def test_source_has_no_login_items_registering_applications_nexe_app(self):
        """Login Items must NOT point to `/Applications/Nexe.app` (orphan app
        with no code alongside). Must point to `<install_dir>/Nexe.app`."""
        src = inspect.getsource(install_headless)
        assert "/Applications/Nexe.app" not in src or _only_cleanup_refs(src), (
            "install_headless no pot registrar /Applications/Nexe.app com a "
            "Login Item; si hi apareix la cadena, ha de ser només cleanup "
            "de residus legacy documentat."
        )


class TestLegacyCleanupPreserved:
    """The uninstaller continues to clean up the residual `/Applications/Nexe.app`
    from old installations (backwards compatibility).
    """

    def test_uninstaller_still_handles_legacy_applications_nexe_app(self):
        from installer import tray_uninstaller

        src = inspect.getsource(tray_uninstaller)
        assert "/Applications/Nexe.app" in src, (
            "Uninstaller must keep the reference to /Applications/Nexe.app "
            "to clean up legacy installations (users with older versions)."
        )


def _only_cleanup_refs(src: str) -> bool:
    """Heuristic: if `/Applications/Nexe.app` appears, it must only be
    in a cleanup context (comments, 'if exists: remove' branches).
    Not in creation branches."""
    # Simplified: must never appear inside a `copytree` call, `osascript`
    # Login Item creation, or as a `nexe_app_dest` destination.
    forbidden_contexts = ["copytree", "make login item at end", "nexe_app_dest"]
    for ctx in forbidden_contexts:
        # If the problematic string appears within 200 chars of the context, break.
        for m in re.finditer(re.escape(ctx), src):
            window = src[max(0, m.start() - 200):m.end() + 200]
            if "/Applications/Nexe.app" in window:
                return False
    return True
