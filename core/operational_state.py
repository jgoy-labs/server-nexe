"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/operational_state.py
Description: D-Q — one place decides the server's operational state; every other
             site only reports a signal. Criticality is declared here, not
             inferred from which folder a module happens to live in.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OperationalState(str, Enum):
    """What the server can do right now — not how a single module feels.

    NORMAL    everything critical is present and healthy.
    DEGRADED  something answers worse than usual; every function still works.
    LIMITED   the server runs but a central function is unavailable. The user
              can still reach the UI and fix it (pick another engine, retry an
              ingest). This is the state that must NOT lock the user out.
    REFUSED   there is no usable service: refuse to start, or say so plainly.
    """

    NORMAL = "normal"
    DEGRADED = "degraded"
    LIMITED = "limited"
    REFUSED = "refused"


class Criticality(str, Enum):
    """Whether the service is usable at all without this module.

    CRITICAL    no module can replace it and the user cannot work around it.
    DEGRADABLE  the server keeps serving; the user can act on it from the UI.
    """

    CRITICAL = "critical"
    DEGRADABLE = "degradable"


# The closed set of modules whose absence leaves nothing to use: authentication
# and the UI that serves the chat. Everything else — RAG, embeddings, inference
# engines — is degradable by nature: the user reaches the interface and fixes it
# from there. This encodes invariant A10: no degradable manager sits on the
# critical path of the chat.
CRITICAL_MODULES: frozenset[str] = frozenset({"security", "web_ui_module"})

# The in-tree memory packages, in dependency order. core/modules
# holds the same tuple as its import allowlist; a test pins them together so
# they cannot drift apart (importing it here would mean core depending on
# personality, which the layering gate freezes).
MEMORY_CORE_MODULES: tuple[str, ...] = ("embeddings", "rag", "memory")

# Module-level health words we accept as a signal. Anything else is treated as
# UNKNOWN — a module that cannot say how it is doing is not evidence of health.
STATUS_MISSING = "missing"
STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_UNHEALTHY = "unhealthy"
STATUS_UNKNOWN = "unknown"

_WORSE_THAN_USUAL = frozenset({STATUS_DEGRADED, STATUS_UNKNOWN})


def criticality_of(module_name: str) -> Criticality:
    """Declared criticality of a module. Unknown modules are degradable.

    The default is deliberate: a module nobody declared critical must not be
    able to lock the user out of the interface. Making a new module critical is
    an explicit edit to CRITICAL_MODULES, reviewed like any other policy.
    """
    return (
        Criticality.CRITICAL
        if module_name in CRITICAL_MODULES
        else Criticality.DEGRADABLE
    )


@dataclass(frozen=True)
class ModuleSignal:
    """One observation about one module. A signal states, it does not rule."""

    name: str
    status: str

    @property
    def criticality(self) -> Criticality:
        return criticality_of(self.name)


def decide(signals: list[ModuleSignal]) -> OperationalState:
    """The single decision point: signals in, one operational state out.

    Worst wins, weighted by declared criticality — a missing critical module
    refuses the service, a missing degradable one only limits it.
    """
    state = OperationalState.NORMAL
    for signal in signals:
        critical = signal.criticality is Criticality.CRITICAL
        if signal.status == STATUS_MISSING:
            candidate = (
                OperationalState.REFUSED if critical else OperationalState.LIMITED
            )
        elif signal.status == STATUS_UNHEALTHY:
            # A module that answers "unhealthy" is making a statement about
            # itself, not merely absent. Its own aggregation contract decides
            # that word (one failing sub-check flips the whole module), and
            # readiness carries it verbatim — see readiness_status().
            candidate = (
                OperationalState.REFUSED if critical else OperationalState.LIMITED
            )
        elif signal.status in _WORSE_THAN_USUAL:
            candidate = OperationalState.DEGRADED
        else:
            continue
        state = _worst(state, candidate)
    return state


# Ordered best → worst. _worst() reads the order from here so adding a state
# later cannot silently invert a comparison.
_SEVERITY_ORDER: tuple[OperationalState, ...] = (
    OperationalState.NORMAL,
    OperationalState.DEGRADED,
    OperationalState.LIMITED,
    OperationalState.REFUSED,
)


def _worst(a: OperationalState, b: OperationalState) -> OperationalState:
    return max(a, b, key=_SEVERITY_ORDER.index)


# Mapping to the public /health/ready contract, which stays a three-word
# vocabulary (healthy | degraded | unhealthy) so the frontend and the live
# suite keep working.
#
# LIMITED maps to "degraded" on purpose: the readiness overlay only lifts on
# healthy/degraded, and a user whose engine or RAG failed to start must be able
# to reach the UI and fix it. Reporting "unhealthy" there is what left the user
# staring at a black screen for six minutes.
_READINESS_WORD: dict[OperationalState, str] = {
    OperationalState.NORMAL: "healthy",
    OperationalState.DEGRADED: "degraded",
    OperationalState.LIMITED: "degraded",
    OperationalState.REFUSED: "unhealthy",
}


def readiness_status(state: OperationalState) -> str:
    """Translate the internal state into the public readiness word.

    Criticality decides, and only criticality. A degradable module that
    answers "unhealthy" about itself is in the same position as one that never
    loaded: the user cannot fix it from behind a blocking overlay, and locking
    them out buys nothing. It has to be SHOWN, not used as a door — /status
    names it and the interface says so plainly.

    The earlier reported_unhealthy escape hatch is gone (decision by Jordi,
    22/08). What the Bug #3 sentinel was really protecting is one level down
    and untouched: a module must not aggregate a failing sub-check into
    "healthy". Its own aggregation contract still enforces that.
    """
    return _READINESS_WORD[state]


# ═══════════════════════════════════════════════════════════════════════════
# Startup refusals — the second half of D-Q
# ═══════════════════════════════════════════════════════════════════════════
#
# Refusing to start still happens where the cause is found: a port already in
# use has to abort there and then, and moving that would only make startup
# harder to follow. What was missing is a type and a common name. Eight sites
# across five files each said it their own way (sys.exit, RuntimeError,
# ValueError, a log line), so nothing could answer "why did it refuse?" without
# grepping logs — and the watcher that has to report it cannot grep.


class RefusalReason(str, Enum):
    """One name per cause the server can refuse to start for.

    STARTUP_PHASE_TIMEOUT used to live here. A phase running out of time is no
    longer a refusal on its own: what it was bringing up is recorded as
    unavailable and criticality decides (#892). If nothing critical is missing
    the server serves and says so, so there is no refusal left to name.
    """

    PORT_IN_USE = "port_in_use"
    IPV6_BIND = "ipv6_bind"
    NON_LOOPBACK_BIND = "non_loopback_bind"
    SIDECAR_CONFIG_INVALID = "sidecar_config_invalid"
    NO_MODULE_ALLOWLIST = "no_module_allowlist"
    SERVICES_TIMEOUT = "services_timeout"
    CRITICAL_MODULE_MISSING = "critical_module_missing"
    SERVER_STARTUP_ERROR = "server_startup_error"
    CRITICAL_STARTUP_ERROR = "critical_startup_error"


@dataclass(frozen=True)
class Refusal:
    """A refusal that happened, with the detail the operator needs."""

    reason: RefusalReason
    detail: str = ""


_refusals: list[Refusal] = []
_refusals_lock = threading.Lock()


def record_refusal(reason: RefusalReason, detail: str = "") -> Refusal:
    """Report a refusal. This records and logs; it never aborts.

    The caller keeps its own sys.exit/raise exactly as it was — the point is
    that the reason now has a name and a single place that knows it.
    """
    refusal = Refusal(reason=reason, detail=detail)
    with _refusals_lock:
        _refusals.append(refusal)
    logger.error("startup refused: reason=%s detail=%s", reason.value, detail)
    return refusal


def refusals() -> tuple[Refusal, ...]:
    """Every refusal recorded so far, oldest first."""
    with _refusals_lock:
        return tuple(_refusals)


def clear_refusals() -> None:
    """Forget recorded refusals. For tests and for a supervised restart."""
    with _refusals_lock:
        _refusals.clear()


def current_state(signals: list[ModuleSignal] | None = None) -> OperationalState:
    """The server's state right now: a recorded refusal outranks any signal."""
    if refusals():
        return OperationalState.REFUSED
    return decide(signals or [])


__all__ = [
    "CRITICAL_MODULES",
    "MEMORY_CORE_MODULES",
    "Criticality",
    "ModuleSignal",
    "OperationalState",
    "Refusal",
    "RefusalReason",
    "clear_refusals",
    "current_state",
    "record_refusal",
    "refusals",
    "criticality_of",
    "decide",
    "readiness_status",
]
