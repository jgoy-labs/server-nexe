"""
Tests d'integració per installer/install_headless.py — Fix bug #19d.

Objectiu: l'installer NO ha de crear `/Applications/Nexe.app` residual.
L'única instal·lació legítima és `<install_dir>/Nexe.app`. Dock i Login
Items apunten allà.

Protecció contra regressió: si algú torna a posar la còpia a /Applications,
aquests tests fallaran.
"""

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from installer import install_headless


class TestInstallerDoesNotCopyToApplications:

    def test_source_has_no_copy_to_applications_nexe_app(self):
        """Protecció estàtica: cap línia de codi productiu d'install_headless
        ha de copiar Nexe.app a `/Applications/Nexe.app`."""
        src = inspect.getsource(install_headless)
        # Pattern: `copytree(..., Path("/Applications/Nexe.app"))` o `/Applications/Nexe.app` com a destí
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
        """Login Items NO pot apuntar a `/Applications/Nexe.app` (app orfe
        sense codi al costat). Ha d'apuntar a `<install_dir>/Nexe.app`."""
        src = inspect.getsource(install_headless)
        assert "/Applications/Nexe.app" not in src or _only_cleanup_refs(src), (
            "install_headless no pot registrar /Applications/Nexe.app com a "
            "Login Item; si hi apareix la cadena, ha de ser només cleanup "
            "de residus legacy documentat."
        )


class TestLegacyCleanupPreserved:
    """L'uninstaller continua netejant `/Applications/Nexe.app` residual
    d'instal·lacions antigues (retrocompat).
    """

    def test_uninstaller_still_handles_legacy_applications_nexe_app(self):
        from installer import tray_uninstaller

        src = inspect.getsource(tray_uninstaller)
        assert "/Applications/Nexe.app" in src, (
            "Uninstaller ha de mantenir la referència a /Applications/Nexe.app "
            "per netejar instal·lacions legacy (usuaris amb versions anteriors)."
        )


def _only_cleanup_refs(src: str) -> bool:
    """Heurística: si `/Applications/Nexe.app` apareix, només ha de ser
    en context de neteja de residus (comentaris, branques 'if exists: remove').
    No en branques de creació."""
    # Simplificat: mai ha d'aparèixer dins una crida a `copytree`, `osascript`
    # de Login Items creació, ni com a `nexe_app_dest` de destí.
    forbidden_contexts = ["copytree", "make login item at end", "nexe_app_dest"]
    for ctx in forbidden_contexts:
        # Si la cadena problemàtica apareix a menys de 200 chars del context, trenca.
        for m in re.finditer(re.escape(ctx), src):
            window = src[max(0, m.start() - 200):m.end() + 200]
            if "/Applications/Nexe.app" in window:
                return False
    return True
