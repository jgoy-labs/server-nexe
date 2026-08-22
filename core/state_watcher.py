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
from core.operational_state import ModuleSignal, OperationalState, current_state

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


async def _read(name: str, sensor: Sensor) -> list[ModuleSignal]:
    """Read one sensor. A sensor that raises reports nothing and says so."""
    try:
        result = sensor()
        if inspect.isawaitable(result):
            result = await result
        return list(result or [])
    except Exception as exc:
        logger.warning("state watcher: sensor %r failed: %s", name, exc)
        return []


async def collect() -> list[ModuleSignal]:
    """One round of every sensor, concurrently."""
    with _sensors_lock:
        items = list(_sensors.items())
    if not items:
        return []
    readings = await asyncio.gather(*(_read(name, s) for name, s in items))
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
        signals = await collect()
        self.last_signals = tuple(signals)
        return self.observe(current_state(signals))

    async def prime(self) -> OperationalState:
        """First round at startup, believed on the spot.

        Hysteresis defends against a state that CHANGES under a flapping
        module. The starting point is not a change: if RAG failed to load
        during startup, the user has to be told now, not two rounds from now.
        """
        signals = await collect()
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
