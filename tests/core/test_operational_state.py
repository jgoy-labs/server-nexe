"""
Tests for core/operational_state.py — D-Q, the single decision point.

Mutation guard for the whole file: make every module critical (add a name to
CRITICAL_MODULES, or drop the criticality split from decide()) and the
"degradable" cases below must turn red. If they stay green, the policy is not
actually being applied and #889 can come back.
"""

from core.operational_state import (
    CRITICAL_MODULES,
    Criticality,
    ModuleSignal,
    OperationalState,
    criticality_of,
    decide,
    readiness_status,
)


class TestDeclaredCriticality:
    def test_the_critical_set_is_closed_and_small(self):
        """Only auth and the UI serving the chat. Growing this set is a policy
        change: everything in it can lock the user out of the interface."""
        assert CRITICAL_MODULES == frozenset({"security", "web_ui_module"})

    def test_unknown_modules_are_degradable(self):
        """A module nobody declared critical must not be able to lock the UI."""
        assert criticality_of("rag") is Criticality.DEGRADABLE
        assert criticality_of("embeddings") is Criticality.DEGRADABLE
        assert criticality_of("ollama_module") is Criticality.DEGRADABLE
        assert criticality_of("a_plugin_written_next_year") is Criticality.DEGRADABLE

    def test_declared_critical_modules_are_critical(self):
        assert criticality_of("security") is Criticality.CRITICAL
        assert criticality_of("web_ui_module") is Criticality.CRITICAL


class TestDecide:
    def test_no_signals_is_normal(self):
        assert decide([]) is OperationalState.NORMAL

    def test_everything_healthy_is_normal(self):
        signals = [ModuleSignal("security", "healthy"), ModuleSignal("rag", "healthy")]
        assert decide(signals) is OperationalState.NORMAL

    def test_missing_degradable_only_limits(self):
        """#889: rag never initialised → the server is limited, not refused."""
        assert decide([ModuleSignal("rag", "missing")]) is OperationalState.LIMITED

    def test_missing_critical_refuses(self):
        assert decide([ModuleSignal("security", "missing")]) is OperationalState.REFUSED

    def test_degraded_is_degraded_whatever_the_criticality(self):
        assert decide([ModuleSignal("security", "degraded")]) is OperationalState.DEGRADED
        assert decide([ModuleSignal("rag", "degraded")]) is OperationalState.DEGRADED

    def test_unknown_status_counts_as_degraded(self):
        """A module that cannot say how it is doing is not evidence of health."""
        assert decide([ModuleSignal("rag", "unknown")]) is OperationalState.DEGRADED

    def test_worst_signal_wins(self):
        signals = [
            ModuleSignal("rag", "degraded"),
            ModuleSignal("security", "missing"),
            ModuleSignal("web_ui_module", "healthy"),
        ]
        assert decide(signals) is OperationalState.REFUSED

    def test_a_limited_state_is_not_downgraded_by_a_later_healthy_signal(self):
        signals = [ModuleSignal("rag", "missing"), ModuleSignal("security", "healthy")]
        assert decide(signals) is OperationalState.LIMITED


class TestReadinessWord:
    def test_normal_is_healthy(self):
        assert readiness_status(OperationalState.NORMAL) == "healthy"

    def test_limited_reads_as_degraded_so_the_ui_loads(self):
        """The readiness overlay only lifts on healthy/degraded. LIMITED must
        not read as "unhealthy" or the user waits six minutes for nothing."""
        assert readiness_status(OperationalState.LIMITED) == "degraded"

    def test_refused_is_unhealthy(self):
        assert readiness_status(OperationalState.REFUSED) == "unhealthy"

    def test_a_degradable_module_answering_unhealthy_does_not_block_either(self):
        """Decision 22/08: criticality decides, and only criticality.

        A degradable module that says "I am unhealthy" is in the same position
        as one that never loaded — the user cannot fix it from behind a
        blocking overlay. It gets shown, not used as a door.
        """
        state = decide([ModuleSignal("rag", "unhealthy")])
        assert state is OperationalState.LIMITED
        assert readiness_status(state) == "degraded"

    def test_a_critical_module_answering_unhealthy_does_block(self):
        """The other half: without auth there is genuinely nothing to use."""
        state = decide([ModuleSignal("security", "unhealthy")])
        assert state is OperationalState.REFUSED
        assert readiness_status(state) == "unhealthy"

