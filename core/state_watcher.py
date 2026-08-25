"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/state_watcher.py
Description: D-Q — the periodic eye. Sensors report, core.operational_state
             decides, and a state only counts once it has held still.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from typing import Any, Callable, Optional

from core.config_catalog import default_for
from core.operational_state import (
    STATUS_UNKNOWN,
    ModuleSignal,
    OperationalState,
    current_state,
)

logger = logging.getLogger(__name__)

# A sensor answers "what do you see?" with signals. It never decides, and it is
# not allowed to break the round: one blind sensor must not blind the rest.
Sensor = Callable[[], Any]  # -> list[ModuleSignal] | Awaitable[list[...]]

_sensors: dict[str, Sensor] = {}
_sensors_lock = threading.Lock()


def register_sensor(name: str, sensor: Sensor) -> None:
    """Add an eye. Registering the same name twice replaces it."""
    with _sensors_lock:
        _sensors[name] = sensor


def clear_sensors() -> None:
    """Forget every sensor. For tests and for a supervised restart."""
    with _sensors_lock:
        _sensors.clear()


def sensor_names() -> tuple[str, ...]:
    with _sensors_lock:
        return tuple(sorted(_sensors))


async def _ask(name: str, sensor: Sensor) -> list[ModuleSignal]:
    """Ask one sensor, without deciding what to do if it misbehaves."""
    result = sensor()
    if inspect.isawaitable(result):
        result = await result
    return list(result or [])


async def _read(name: str, sensor: Sensor, timeout: float) -> list[ModuleSignal]:
    """Read one sensor. A sensor that raises — or that HANGS — says so.

    #944: the round used to wait forever. A sensor that raises was handled from
    the start, but a sensor that simply never returns is not an exception, so
    `except Exception` never saw it: one blind eye blinded the whole round, the
    confirmed state froze at whatever it was (normal, in the case that matters)
    and not one line was logged. The failure mode was not a false red — it was a
    green that lied.

    A sensor that runs out of time reports STATUS_UNKNOWN, which `decide()`
    reads as DEGRADED: "I cannot see" is a finding, not silence. The signal
    carries the SENSOR's name because that is what failed; the modules it was
    meant to watch stay unreported, which is honest.

    Limit worth knowing: this only reaches sensors that await. A SYNCHRONOUS
    sensor that blocks holds the event loop itself, and no timeout inside a
    coroutine can interrupt that — it would need a thread. Today's sensors are
    local and synchronous; the type has always accepted awaitables.
    """
    try:
        return await asyncio.wait_for(_ask(name, sensor), timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "state watcher: sensor %r did not answer in %ss — reporting unknown",
            name,
            timeout,
        )
        return [ModuleSignal(name=name, status=STATUS_UNKNOWN)]
    except Exception as exc:
        logger.warning("state watcher: sensor %r failed: %s", name, exc)
        return []


async def collect(*, sensor_timeout: Optional[float] = None) -> list[ModuleSignal]:
    """One round of every sensor, concurrently, each on its own clock.

    The timeout defaults from the catalog rather than from the caller, so a
    `collect()` from anywhere else is bounded too (#944).
    """
    with _sensors_lock:
        items = list(_sensors.items())
    if not items:
        return []
    timeout = float(
        sensor_timeout
        if sensor_timeout is not None
        else default_for("state_watcher_sensor_timeout")
    )
    readings = await asyncio.gather(*(_read(name, s, timeout) for name, s in items))
    return [signal for reading in readings for signal in reading]


class StateWatcher:
    """Polls the sensors and holds the confirmed state.

    Hysteresis: a new reading has to repeat before it becomes the state. A
    module that flaps — a backend that answers slowly, an engine warming up —
    would otherwise walk the UI banner in and out every few seconds, and a
    warning that blinks is a warning nobody reads.
    """

    def __init__(
        self,
        *,
        interval: Optional[float] = None,
        confirmations: Optional[int] = None,
        sensor_timeout: Optional[float] = None,
    ) -> None:
        self.interval = float(
            interval if interval is not None else default_for("state_watcher_interval")
        )
        self.confirmations = max(
            1,
            int(
                confirmations
                if confirmations is not None
                else default_for("state_watcher_confirmations")
            ),
        )
        self.sensor_timeout = float(
            sensor_timeout
            if sensor_timeout is not None
            else default_for("state_watcher_sensor_timeout")
        )
        self._confirmed = OperationalState.NORMAL
        self._candidate = OperationalState.NORMAL
        self._streak = 0
        self._task: Optional[asyncio.Task[None]] = None
        self.last_signals: tuple[ModuleSignal, ...] = ()

    @property
    def state(self) -> OperationalState:
        """The state that has held still long enough to be believed."""
        return self._confirmed

    def observe(self, reading: OperationalState) -> OperationalState:
        """Feed one reading through the hysteresis. Returns the confirmed state."""
        if reading is self._confirmed:
            self._candidate = reading
            self._streak = 0
            return self._confirmed
        if reading is self._candidate:
            self._streak += 1
        else:
            self._candidate = reading
            self._streak = 1
        if self._streak >= self.confirmations:
            previous = self._confirmed
            self._confirmed = reading
            self._streak = 0
            logger.info(
                "state watcher: %s → %s (confirmed after %d readings)",
                previous.value,
                reading.value,
                self.confirmations,
            )
        return self._confirmed

    async def poll_once(self) -> OperationalState:
        """One full round: read the eyes, ask the decider, apply hysteresis."""
        signals = await collect(sensor_timeout=self.sensor_timeout)
        self.last_signals = tuple(signals)
        return self.observe(current_state(signals))

    async def prime(self) -> OperationalState:
        """First round at startup, believed on the spot.

        Hysteresis defends against a state that CHANGES under a flapping
        module. The starting point is not a change: if RAG failed to load
        during startup, the user has to be told now, not two rounds from now.
        """
        signals = await collect(sensor_timeout=self.sensor_timeout)
        self.last_signals = tuple(signals)
        self._confirmed = current_state(signals)
        self._candidate = self._confirmed
        self._streak = 0
        if self._confirmed is not OperationalState.NORMAL:
            logger.warning(
                "state watcher: starting at %s (%s)",
                self._confirmed.value,
                ", ".join(f"{s.name}={s.status}" for s in signals) or "no detail",
            )
        return self._confirmed

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The watcher watches; it never brings the server down with it.
                logger.warning("state watcher: round failed: %s", exc)

    def start(self) -> Optional[asyncio.Task[None]]:
        if self.interval <= 0:
            logger.info("state watcher: disabled (interval=%s)", self.interval)
            return None
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info(
                "state watcher: started (every %ss, %d readings to confirm, sensors=%s)",
                self.interval,
                self.confirmations,
                list(sensor_names()),
            )
        return self._task

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


watcher = StateWatcher()
