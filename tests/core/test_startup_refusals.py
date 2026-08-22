"""
Tests for the startup-refusal register — D-Q, second half.

Refusing to start still happens where the cause is found; what these tests fix
is that every one of those sites now says WHY in the same words, in one place.

Mutation guard: drop the record_refusal() call from any site below and its test
turns red. That is the whole point — before this, a refusal left nothing but a
log line, and the eight sites each phrased it differently.
"""

import pytest

from core.operational_state import (
    OperationalState,
    RefusalReason,
    clear_refusals,
    current_state,
    record_refusal,
    refusals,
)


@pytest.fixture(autouse=True)
def _clean_register():
    """The register is process-wide: no test may inherit another's refusals."""
    clear_refusals()
    yield
    clear_refusals()


class TestRegister:
    def test_a_refusal_is_recorded_with_its_reason_and_detail(self):
        record_refusal(RefusalReason.PORT_IN_USE, "port 9119")
        assert [(r.reason, r.detail) for r in refusals()] == [
            (RefusalReason.PORT_IN_USE, "port 9119")
        ]

    def test_recording_does_not_abort(self):
        """record_refusal reports; the caller keeps its own exit or raise."""
        record_refusal(RefusalReason.IPV6_BIND, "::1")
        assert True  # reaching this line is the assertion

    def test_a_refusal_outranks_every_module_signal(self):
        record_refusal(RefusalReason.SERVICES_TIMEOUT, "60s")
        assert current_state() is OperationalState.REFUSED

    def test_without_refusals_the_state_comes_from_the_signals(self):
        assert current_state() is OperationalState.NORMAL

    def test_refusals_keep_their_order(self):
        record_refusal(RefusalReason.PORT_IN_USE, "first")
        record_refusal(RefusalReason.IPV6_BIND, "second")
        assert [r.detail for r in refusals()] == ["first", "second"]


class TestRunnerSites:
    """core/server/runner.py — five of the eight sites were the same cause."""

    def test_sidecar_port_conflict_names_the_reason(self):
        from core.server.runner import _handle_port_conflict

        with pytest.raises(SystemExit):
            _handle_port_conflict("127.0.0.1", 9119, headless=False, sidecar=True, i18n=None)
        assert [r.reason for r in refusals()] == [RefusalReason.PORT_IN_USE]

    def test_ipv6_bind_names_the_reason(self):
        from core.server.runner import _reject_ipv6_bind

        with pytest.raises(SystemExit):
            _reject_ipv6_bind("::1")
        assert [r.reason for r in refusals()] == [RefusalReason.IPV6_BIND]

    def test_a_loopback_host_is_not_a_refusal(self):
        """The negative control: the happy path must record nothing."""
        from core.server.runner import _enforce_loopback_bind

        _enforce_loopback_bind("127.0.0.1")
        assert refusals() == ()

    def test_non_loopback_bind_without_optin_names_the_reason(self, monkeypatch):
        from core.server.runner import _enforce_loopback_bind

        monkeypatch.delenv("NEXE_ALLOW_PUBLIC_BIND", raising=False)
        with pytest.raises(SystemExit):
            _enforce_loopback_bind("0.0.0.0")  # nosemgrep: bind-all-interfaces — the value under test
        assert [r.reason for r in refusals()] == [RefusalReason.NON_LOOPBACK_BIND]


class TestAllowlistSites:
    """One cause, one record — asking is not refusing.

    Both files used to record it: the query in core/config.py AND the boundary
    in factory_security.py that catches its ValueError. One event, two entries.
    Worse than the duplicate: a recorded refusal outranks every signal in
    current_state(), so any caller that merely ASKED for the allowlist and
    handled the error would leave the watcher reporting REFUSED for a server
    that is serving fine — the same shape as the lifespan bug where an error
    hours into serving was recorded as a refusal to start.
    """

    def test_asking_for_the_allowlist_is_not_a_refusal(self, monkeypatch):
        """The query raises so the caller can decide; it records nothing."""
        from core.config import get_module_allowlist

        monkeypatch.setenv("NEXE_ENV", "production")
        monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
        with pytest.raises(ValueError):
            get_module_allowlist({"core": {"environment": {"mode": "production"}}})
        assert refusals() == (), (
            "core.config.get_module_allowlist recorded a startup refusal. It is a "
            "query — the plugin loader calls it too. Only the site that aborts "
            "startup may record (core/server/factory_security.py)."
        )

    def test_an_allowlist_in_place_is_not_a_refusal(self, monkeypatch):
        from core.config import get_module_allowlist

        monkeypatch.setenv("NEXE_ENV", "production")
        monkeypatch.setenv("NEXE_APPROVED_MODULES", "security,web_ui_module")
        assert get_module_allowlist({}) == {"security", "web_ui_module"}
        assert refusals() == ()


class TestFactorySecuritySite:
    def test_production_without_allowlist_refuses_from_the_factory_too(self, monkeypatch):
        """The same cause reached from the other file. Note the empty string:
        importing the module loads .env, which sets the variable back — a
        delenv before the import would test nothing."""
        from core.server.factory_security import validate_production_security

        monkeypatch.setenv("NEXE_ENV", "production")
        monkeypatch.setenv("NEXE_APPROVED_MODULES", "")
        with pytest.raises(ValueError):
            validate_production_security(
                None, {"core": {"environment": {"mode": "production"}}}
            )
        # Exactly one, not "contains one": the `in` here is what let the
        # double record from core/config.py hide for a day.
        assert [r.reason for r in refusals()] == [RefusalReason.NO_MODULE_ALLOWLIST]


class TestLifespanSite:
    """The lifespan try block wraps the yield too — the whole serving life."""

    @pytest.mark.asyncio
    async def test_an_error_after_startup_is_not_a_refusal_to_start(self, monkeypatch):
        from unittest.mock import AsyncMock

        from core import lifespan as lifespan_mod

        monkeypatch.setattr(lifespan_mod, "_startup", AsyncMock())
        monkeypatch.setattr(lifespan_mod, "_shutdown", AsyncMock())

        with pytest.raises(RuntimeError):
            async with lifespan_mod.lifespan(object()):
                raise RuntimeError("the server died after hours of serving")

        assert refusals() == (), (
            "an error raised after startup succeeded must not be recorded as a "
            "refusal to start: the state machine would report REFUSED forever"
        )

    @pytest.mark.asyncio
    async def test_an_error_during_startup_is_a_refusal(self, monkeypatch):
        from unittest.mock import AsyncMock

        from core import lifespan as lifespan_mod

        monkeypatch.setattr(
            lifespan_mod, "_startup", AsyncMock(side_effect=RuntimeError("qdrant is not there"))
        )
        monkeypatch.setattr(lifespan_mod, "_shutdown", AsyncMock())

        with pytest.raises(RuntimeError):
            async with lifespan_mod.lifespan(object()):
                pass

        assert [r.reason for r in refusals()] == [RefusalReason.CRITICAL_STARTUP_ERROR]


class TestCriticalityDecidesAtStartup:
    """#892, gates G3 and G4 — the startup path applies the DECLARED criticality.

    The inversion this closes: Qdrant dead let the server start (an exception
    in load_memory_modules put the module in degraded_modules and startup went
    on), while Qdrant slow killed it (the same three phases ran inside
    asyncio.wait_for and a TimeoutError became a RuntimeError). The same
    subsystem failed open by exception and closed by clock.

    Since D-Q the project declares that rag, embeddings, memory and the engines
    are degradable and only authentication and the interface are not. These
    tests hold the startup path to that declaration.
    """

    def _app(self, modules):
        from unittest.mock import MagicMock

        app = MagicMock()
        app.state.modules = modules
        return app

    @pytest.mark.asyncio
    async def test_g3_a_degradable_subsystem_that_times_out_does_not_refuse(self, monkeypatch):
        """The whole point: a slow memory store leaves a server the user can
        reach and fix, not a process that died before showing anything.

        Drives the REAL phase loop with a phase that never finishes. An earlier
        draft called the two helpers by hand and never went through the loop —
        putting the `raise` back left it green, which is the mutation this test
        exists to catch.
        """
        import asyncio

        from core import lifespan as lifespan_mod
        from core.server_state import server_state

        server_state.degraded_modules = []
        app = self._app({"security": object(), "web_ui_module": object()})

        async def _never(*_a, **_kw):
            await asyncio.sleep(30)

        async def _fine(*_a, **_kw):
            return None

        monkeypatch.setattr(lifespan_mod, "load_memory_modules", _never)
        monkeypatch.setattr(lifespan_mod, "initialize_plugin_modules", _fine)
        monkeypatch.setattr(lifespan_mod, "start_memory_service_v1", _fine)
        monkeypatch.setattr(lifespan_mod, "STARTUP_TIMEOUT", 0.05)

        await lifespan_mod._run_startup_phases(app)  # must not raise

        assert "rag" in server_state.degraded_modules, (
            "the subsystem that did not come up has to be named, or nothing "
            "downstream can warn the user"
        )
        assert refusals() == (), (
            "a phase the server survives must not record a refusal: a recorded "
            "refusal outranks every signal in current_state()"
        )

    @pytest.mark.asyncio
    async def test_a_timeout_that_loses_a_critical_module_still_refuses(self, monkeypatch):
        """Criticality decides both ways, through the same loop."""
        import asyncio

        from core import lifespan as lifespan_mod
        from core.server_state import server_state

        server_state.degraded_modules = []
        app = self._app({"security": object()})  # web_ui_module never arrives

        async def _never(*_a, **_kw):
            await asyncio.sleep(30)

        monkeypatch.setattr(lifespan_mod, "load_memory_modules", _never)
        monkeypatch.setattr(lifespan_mod, "initialize_plugin_modules", _never)
        monkeypatch.setattr(lifespan_mod, "start_memory_service_v1", _never)
        monkeypatch.setattr(lifespan_mod, "STARTUP_TIMEOUT", 0.05)

        with pytest.raises(RuntimeError, match="web_ui_module"):
            await lifespan_mod._run_startup_phases(app)

    def test_a_missing_critical_module_still_refuses(self):
        """Criticality decides BOTH ways. Without this, the fix above would
        read as 'startup never refuses', which is a different bug."""
        from core.lifespan import _refuse_if_a_critical_module_is_missing

        app = self._app({"web_ui_module": object()})  # security absent

        with pytest.raises(RuntimeError, match="security"):
            _refuse_if_a_critical_module_is_missing(app)
        assert [r.reason for r in refusals()] == [RefusalReason.CRITICAL_MODULE_MISSING]

    def test_the_refusal_names_every_missing_critical_module(self):
        from core.lifespan import _refuse_if_a_critical_module_is_missing

        with pytest.raises(RuntimeError) as exc:
            _refuse_if_a_critical_module_is_missing(self._app({}))
        assert "security" in str(exc.value) and "web_ui_module" in str(exc.value)

    @pytest.mark.asyncio
    async def test_g4_qdrant_failing_to_start_degrades_instead_of_killing(self, monkeypatch):
        """A `.lock` still held by the previous sidecar used to prevent startup
        while the same store being dead only degraded it.

        Drives the real _start_qdrant_or_degrade(). Two earlier drafts of this
        test were worse: one asserted that the stub raised (proving nothing
        about the code under test) and one re-implemented the guard's body
        inside the test, which would stay green if the guard were deleted.
        """
        from core import lifespan as lifespan_mod
        from core.server_state import server_state

        server_state.degraded_modules = []
        server_state.qdrant_available = True

        def _locked():
            raise RuntimeError(
                "Storage folder storage/vectors is already accessed by another instance"
            )

        monkeypatch.setattr(lifespan_mod, "_startup_qdrant", _locked)

        # Drives the production helper, not a copy of it.
        lifespan_mod._start_qdrant_or_degrade()

        assert server_state.qdrant_available is False
        assert "qdrant" in server_state.degraded_modules
        assert refusals() == (), "a degradable store failing to start is not a refusal"


async def _noop_async(*_a, **_kw):
    return None
