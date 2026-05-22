"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_pyright_unbound_fixes_20260521.py
Description: Anti-regression tests for the 2 pyright reportPossiblyUnbound
             findings fixed on 2026-05-21 (post-Tier S cleanup):

             1. core/endpoints/installer.py:832 — DownloadIntegrityError must
                be bound at module-level so the except clause never raises
                NameError when the lazy verify_download_integrity import fails.

             2. core/lifespan_modules.py:342 — qdrant_path must be defensively
                initialised before the project_root branch so the logger.info
                call cannot reference an unbound name.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import pytest


class TestInstallerDownloadIntegrityError:
    """Module-level binding of DownloadIntegrityError (pyright fix 20260521)."""

    def test_class_is_importable_from_module_top(self) -> None:
        """DownloadIntegrityError must be available right after import."""
        from core.endpoints import installer

        assert hasattr(installer, "DownloadIntegrityError"), (
            "DownloadIntegrityError missing from installer module — "
            "the top-level try/except import block must always bind it "
            "(either the real class or the fallback)."
        )

    def test_class_is_exception_subclass(self) -> None:
        """Whatever ends up bound (real class or fallback) must be raisable."""
        from core.endpoints import installer

        assert issubclass(installer.DownloadIntegrityError, Exception)

    def test_can_be_used_in_except_clause(self) -> None:
        """Confirm the binding is catchable in the original codepath's except.

        Real class signature: (artifact, message, *, cause). Fallback: (msg).
        We pass enough positional args to satisfy both, then catch.
        """
        from core.endpoints import installer

        caught: bool = False
        try:
            try:
                raise installer.DownloadIntegrityError(
                    "sentinel-artifact", "sentinel-message"
                )
            except TypeError:
                # Fallback class accepts a single arg only
                raise installer.DownloadIntegrityError("sentinel-message")
        except installer.DownloadIntegrityError:
            caught = True
        assert caught, "DownloadIntegrityError must be catchable"


class TestLifespanModulesQdrantPath:
    """qdrant_path defensive init (pyright fix 20260521)."""

    def test_qdrant_path_default_when_project_root_missing(self) -> None:
        """
        Read the source and confirm `qdrant_path` is initialised with a
        default before the conditional branch that may not assign it.

        We avoid invoking the full lifespan (heavy deps) and just check
        the source-level invariant. The pyright check itself is the
        primary guarantee; this test pins it from regression.
        """
        import inspect

        from core import lifespan_modules

        src = inspect.getsource(lifespan_modules)
        assert 'qdrant_path: str = "default"' in src, (
            "qdrant_path must be defensively initialised to 'default' before "
            "the `if project_root:` branch so the logger.info reference is "
            "always bound (pyright reportPossiblyUnbound)."
        )

    def test_lifespan_modules_imports_without_error(self) -> None:
        """Module must be importable at minimum (no syntax/runtime errors)."""
        from core import lifespan_modules

        assert hasattr(lifespan_modules, "initialize_plugin_modules")
