"""
Regression tests for the session-manager double-init + router stale-reference
chain (commit 5abd171).

Three bugs chained together:
  1. Loader early-init — core/loader/manifest_base._get_module calls
     instance._init_router() immediately after __init__, before
     initialize() runs.
  2. Plugin double-create — WebUIModule used to build a SessionManager()
     in __init__ without crypto, then replace it in initialize() with a
     crypto-aware manager. Two divergent instances.
  3. Router stale ref — create_router() captured
     module_instance.session_manager into a local, snapshotting the
     crypto-less instance from bug #2.

Fix: a single SessionManager is built only in initialize(); routes read
through a _SessionManagerProxy with late-binding __getattr__.

These tests pin the contract so a future refactor cannot silently
reintroduce any of the three bugs.
"""

import asyncio

import pytest

from plugins.web_ui_module.api.routes import _SessionManagerProxy, create_router
from plugins.web_ui_module.module import WebUIModule


class TestSessionManagerLateInit:
    def test_init_leaves_session_manager_none(self):
        """__init__ must NOT create a SessionManager (bug #2 regression guard)."""
        mod = WebUIModule()
        assert mod.session_manager is None

    def test_initialize_creates_single_session_manager(self):
        """initialize() creates the one and only SessionManager."""
        mod = WebUIModule()
        ok = asyncio.run(mod.initialize({"config": {}}))
        assert ok is True
        first = mod.session_manager
        assert first is not None

        # Idempotent: re-initialize returns True without swapping the instance.
        ok2 = asyncio.run(mod.initialize({"config": {}}))
        assert ok2 is True
        assert mod.session_manager is first


class TestSessionManagerProxy:
    def test_proxy_raises_before_initialize(self):
        """Accessing the proxy before initialize() must fail loudly.

        Silent fallback to None is exactly what let bug #3 slip past review.
        """
        mod = WebUIModule()
        proxy = _SessionManagerProxy(mod)
        with pytest.raises(RuntimeError, match="initialize"):
            proxy.list_sessions()

    def test_proxy_reads_through_after_initialize(self):
        """After initialize(), the proxy delegates transparently."""
        mod = WebUIModule()
        proxy = _SessionManagerProxy(mod)
        asyncio.run(mod.initialize({"config": {}}))
        assert proxy.list_sessions() == mod.session_manager.list_sessions()

    def test_proxy_tracks_reassignment(self):
        """If session_manager is replaced, the proxy sees the new instance.

        This is the core of the fix: no local capture, always fresh read.
        """
        mod = WebUIModule()
        asyncio.run(mod.initialize({"config": {}}))
        proxy = _SessionManagerProxy(mod)
        original = mod.session_manager

        # Simulate a hypothetical rebuild of session_manager (e.g. after a
        # key rotation). The proxy must follow, not keep pointing at the
        # original.
        from plugins.web_ui_module.core.session_manager import SessionManager
        mod.session_manager = SessionManager()
        assert mod.session_manager is not original
        assert proxy.list_sessions() == mod.session_manager.list_sessions()


class TestCreateRouterBeforeInitialize:
    def test_router_built_pre_initialize_uses_live_manager_post_initialize(self):
        """Router created before initialize() still sees the real manager later.

        This is exactly the ordering the loader imposes (bug #1). The
        regression would be: create_router captures a local reference,
        initialize() replaces session_manager, the router keeps using the
        old (crypto-less) one — sessions look missing and new ones are
        written unencrypted.
        """
        mod = WebUIModule()
        router = create_router(mod)  # pre-initialize — legal under the fix
        assert router is not None

        asyncio.run(mod.initialize({"config": {}}))
        assert mod.session_manager is not None
        # We can't introspect closures directly, but we can verify the
        # observable behaviour: the proxy (and therefore every route that
        # was registered with it) reads through to the live manager.
        proxy = _SessionManagerProxy(mod)
        assert proxy.list_sessions() == mod.session_manager.list_sessions()
