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
