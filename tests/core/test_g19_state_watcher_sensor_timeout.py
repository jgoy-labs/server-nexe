"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/test_g19_state_watcher_sensor_timeout.py
Description: #944 — un sensor que ES PENJA congelava el semàfor a verd, sense
             cap log. Reproduït el 24/08 abans de tocar res: amb un sensor
             `async` que fa `sleep(3600)` i un altre que crida que FALTA el RAG,
             el bucle real (interval=0.05, ~12 rondes) donava
             `estat = normal`, `last_signals = ()` i **ni una línia de log**.

             `asyncio.gather` no portava rellotge i `_read` només capturava
             `Exception`: un `await` que no torna no és una excepció. És #890
             («un try/except no captura un bloqueig») al vigilant d'estat.

             El mode de fallada NO és un vermell fals — és un VERD que menteix,
             que és pitjor: el RAG faltava de debò i el semàfor deia `normal`.

             Aquest gate mesura les dues meitats: que la ronda TORNI, i que el
             sensor que no contesta compti com a **senyal** (`unknown` →
             DEGRADED) i no com a silenci.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging

import pytest

from core import state_watcher as sw
from core.config_catalog import get_decl
from core.operational_state import (
    STATUS_UNKNOWN,
    ModuleSignal,
    OperationalState,
    clear_refusals,
)

LENT = 0.2  # el sensor penjat no ha de trigar més que això a ser declarat cec


@pytest.fixture(autouse=True)
def sensors_nets():
    """Sensors I refusos: tots dos registres són de PROCÉS.

    Un refús registrat mana sobre qualsevol senyal (`current_state`), o sigui
    que un test que en deixi un de penjat converteix aquest gate en teatre:
    mesuraria REFUSED passi el que passi amb els sensors. Mesurat el 24/08 —
    aquest fitxer passava sol i fallava dins la suite.
    """
    sw.clear_sensors()
    clear_refusals()
    yield
    sw.clear_sensors()
    clear_refusals()


def _penjat():
    async def sensor():
        await asyncio.sleep(3600)  # no peta: simplement no torna mai
    return sensor


def _crida_que_falta_el_rag():
    return [ModuleSignal(name="rag", status="missing")]


class TestG19AHangingSensorDoesNotBlindTheRound:

    async def test_the_round_still_sees_the_other_sensors(self):
        sw.register_sensor("penjat", _penjat())
        sw.register_sensor("sa", _crida_que_falta_el_rag)
        watcher = sw.StateWatcher(interval=0.05, confirmations=1, sensor_timeout=LENT)

        estat = await asyncio.wait_for(watcher.poll_once(), 5.0)

        assert estat is OperationalState.LIMITED, (
            "#944: el RAG falta i el semàfor no ho ha vist — un sol sensar penjat "
            f"s'ha menjat la ronda sencera (estat={estat})"
        )
        assert ("rag", "missing") in [(s.name, s.status) for s in watcher.last_signals]

    async def test_the_hanging_sensor_is_a_signal_not_silence(self):
        sw.register_sensor("penjat", _penjat())
        watcher = sw.StateWatcher(interval=0.05, confirmations=1, sensor_timeout=LENT)

        estat = await asyncio.wait_for(watcher.poll_once(), 5.0)

        vistos = [(s.name, s.status) for s in watcher.last_signals]
        assert ("penjat", STATUS_UNKNOWN) in vistos, (
            f"#944: el sensor que no contesta ha de reportar-se, no callar: {vistos}"
        )
        assert estat is OperationalState.DEGRADED, (
            "«no puc veure» ha de degradar l'estat; quedar-se a normal és el verd "
            f"que menteix (estat={estat})"
        )

    async def test_the_timeout_is_logged(self, caplog):
        sw.register_sensor("penjat", _penjat())
        watcher = sw.StateWatcher(interval=0.05, confirmations=1, sensor_timeout=LENT)

        with caplog.at_level(logging.WARNING, logger="core.state_watcher"):
            await asyncio.wait_for(watcher.poll_once(), 5.0)

        assert any("penjat" in r.getMessage() for r in caplog.records), (
            f"#944: el sensor cec ha de deixar rastre: {[r.getMessage() for r in caplog.records]}"
        )

    async def test_the_running_loop_keeps_advancing(self):
        """El bucle real, que és on es va mesurar el defecte."""
        sw.register_sensor("penjat", _penjat())
        sw.register_sensor("sa", _crida_que_falta_el_rag)
        watcher = sw.StateWatcher(interval=0.05, confirmations=1, sensor_timeout=LENT)

        watcher.start()
        try:
            await asyncio.sleep(0.8)
            assert watcher.last_signals, (
                "#944: després de diverses rondes el vigilant no ha vist RES"
            )
            assert watcher.state is not OperationalState.NORMAL, (
                "#944: el semàfor s'ha quedat congelat a verd amb el RAG faltant"
            )
        finally:
            await watcher.stop()


class TestG19TheBoundIsNotTheCallersFavour:

    async def test_collect_is_bounded_without_any_watcher(self, monkeypatch):
        """Qui cridi `collect()` pel seu compte també ha d'estar protegit."""
        monkeypatch.setattr(
            sw, "default_for",
            lambda key, **kw: LENT if key == "state_watcher_sensor_timeout" else 0.05,
        )
        sw.register_sensor("penjat", _penjat())

        signals = await asyncio.wait_for(sw.collect(), 5.0)

        assert [(s.name, s.status) for s in signals] == [("penjat", STATUS_UNKNOWN)], (
            "#944: `collect()` sense argument ha d'agafar el rellotge del catàleg, "
            "no quedar-se sense cap"
        )

    def test_the_catalog_declares_the_clock(self):
        """Un timeout que no es pot configurar és una constant amagada."""
        decl = get_decl("state_watcher_sensor_timeout")

        assert decl.env == "NEXE_STATE_WATCHER_SENSOR_TIMEOUT"
        assert float(decl.default) > 0


class TestG19WhatMustNotChange:
    """Controls inversos: el rellotge no pot inventar-se avaries."""

    async def test_fast_sensors_produce_no_phantom_signals(self):
        sw.register_sensor("rapid", lambda: [])
        sw.register_sensor("sa", _crida_que_falta_el_rag)
        watcher = sw.StateWatcher(interval=0.05, confirmations=1, sensor_timeout=LENT)

        await watcher.poll_once()

        vistos = [(s.name, s.status) for s in watcher.last_signals]
        assert vistos == [("rag", "missing")], (
            f"el rellotge ha fabricat senyals que ningú ha reportat: {vistos}"
        )

    async def test_a_sensor_that_raises_still_reports_nothing(self, caplog):
        """Un sensor que PETA ja estava cobert: ha de seguir igual."""
        def peta():
            raise RuntimeError("el sensor ha petat")

        sw.register_sensor("peta", peta)
        sw.register_sensor("sa", _crida_que_falta_el_rag)
        watcher = sw.StateWatcher(interval=0.05, confirmations=1, sensor_timeout=LENT)

        with caplog.at_level(logging.WARNING, logger="core.state_watcher"):
            estat = await watcher.poll_once()

        vistos = [(s.name, s.status) for s in watcher.last_signals]
        assert ("peta", STATUS_UNKNOWN) not in vistos, (
            "un sensor que peta no és un sensor que es penja: no ha de reportar unknown"
        )
        assert estat is OperationalState.LIMITED
        assert any("peta" in r.getMessage() for r in caplog.records)
