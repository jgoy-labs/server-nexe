"""
Bug 11 — Bootstrap token expira sense recuperacio.
Implementacio: background task asyncio que cada (ttl-5)*60 segons
regenera el token via regenerate_bootstrap_token().

Tests:
- regenerate_bootstrap_token genera token diferent del previ
- start_bootstrap_token_renewal arrenca una asyncio.Task viva
- stop_bootstrap_token_renewal cancel·la net (sense exception)
- la task es cancellable quan està dormint
"""
import asyncio
import pytest

import core.lifespan_tokens as lt
from core.lifespan_tokens import (
    generate_bootstrap_token,
    regenerate_bootstrap_token,
    start_bootstrap_token_renewal,
    stop_bootstrap_token_renewal,
    _bootstrap_token_renewal_loop,
)
from core.bootstrap_tokens import (
    initialize_tokens,
    get_bootstrap_token,
    set_bootstrap_token,
)


@pytest.fixture
def init_db(tmp_path):
    """Initialize bootstrap token DB on a tmp path."""
    initialize_tokens(tmp_path)
    yield tmp_path


@pytest.fixture(autouse=True)
async def cleanup_renewal_task():
    yield
    # Sempre netejar la task entre tests
    await stop_bootstrap_token_renewal()


class TestRegenerateBootstrapToken:

    def test_regenerate_returns_new_token(self, init_db):
        old = generate_bootstrap_token()
        set_bootstrap_token(old, ttl_minutes=30)
        new = regenerate_bootstrap_token(ttl_minutes=30)
        assert new != old
        assert new.startswith("Nexe-")
        # I esta persistit
        info = get_bootstrap_token()
        assert info["token"] == new

    def test_regenerate_format_is_secure(self, init_db):
        new = regenerate_bootstrap_token(ttl_minutes=15)
        # Nexe- + 32 hex chars
        assert new.startswith("Nexe-")
        assert len(new) == len("Nexe-") + 32


class TestRenewalTaskLifecycle:

    @pytest.mark.asyncio
    async def test_start_creates_task(self, init_db):
        task = start_bootstrap_token_renewal(ttl_minutes=30, interval_seconds=3600)
        assert isinstance(task, asyncio.Task)
        assert not task.done()
        assert lt._renewal_task is task

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, init_db):
        task = start_bootstrap_token_renewal(ttl_minutes=30, interval_seconds=3600)
        await stop_bootstrap_token_renewal()
        assert task.cancelled() or task.done()
        assert lt._renewal_task is None

    @pytest.mark.asyncio
    async def test_start_twice_replaces_task(self, init_db):
        first = start_bootstrap_token_renewal(ttl_minutes=30, interval_seconds=3600)
        second = start_bootstrap_token_renewal(ttl_minutes=30, interval_seconds=3600)
        # La primera s'ha de cancellar
        await asyncio.sleep(0)  # let cancellation propagate
        assert first.cancelled() or first.done()
        assert lt._renewal_task is second
        await stop_bootstrap_token_renewal()

    @pytest.mark.asyncio
    async def test_stop_when_no_task_is_safe(self, init_db):
        # Sense haver arrencat res
        await stop_bootstrap_token_renewal()  # no exception


class TestRenewalLoopRegenerates:
    """Verifica que el loop crida regenerate quan passa el sleep."""

    @pytest.mark.asyncio
    async def test_loop_regenerates_after_interval(self, init_db, monkeypatch):
        # Set initial token
        initial = "Nexe-INITIALAAAAAAAAAAAAAAAAAAAAAAAA"
        set_bootstrap_token(initial, ttl_minutes=30)

        regen_calls = []

        # Patch sleep perque sigui instantani
        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await real_sleep(0)

        monkeypatch.setattr("core.lifespan_tokens.asyncio.sleep", fast_sleep)

        # Patch regenerate per comptar
        original_regen = lt.regenerate_bootstrap_token

        def counting_regen(ttl_minutes=30):
            regen_calls.append(ttl_minutes)
            return original_regen(ttl_minutes=ttl_minutes)

        monkeypatch.setattr(lt, "regenerate_bootstrap_token", counting_regen)

        task = asyncio.create_task(_bootstrap_token_renewal_loop(1, 30))
        # Donem temps a unes quantes iteracions
        await real_sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(regen_calls) >= 1
        # I el token ha canviat
        info = get_bootstrap_token()
        assert info["token"] != initial


class TestRenewalRetryBackoff:
    """Fix Consultor passada 1 — Finding 4: retry exponencial quan regenerate falla."""

    @pytest.mark.asyncio
    async def test_retry_recovers_after_transient_failures(
        self, init_db, monkeypatch, caplog
    ):
        """Si regenerate falla 2 cops i recupera al 3r, hi ha missatge 'recovered'."""
        import logging

        # Sleep instantani
        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await real_sleep(0)

        monkeypatch.setattr("core.lifespan_tokens.asyncio.sleep", fast_sleep)

        # Regenerate falla 2 cops, tercera OK
        calls = {"n": 0}

        def flaky_regen(ttl_minutes=30):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError(f"disk full #{calls['n']}")
            return "Nexe-RECOVEREDAAAAAAAAAAAAAAAAAAAAA"

        monkeypatch.setattr(lt, "regenerate_bootstrap_token", flaky_regen)

        with caplog.at_level(logging.INFO, logger="core.lifespan_tokens"):
            task = asyncio.create_task(_bootstrap_token_renewal_loop(1, 30))
            await real_sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Hi ha hagut com a minim 3 crides (1 inicial + 2 retries)
        assert calls["n"] >= 3
        # Hi ha d'haver missatge 'recovered'
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "recovered" in text.lower(), (
            f"no s'ha trobat missatge 'recovered' als logs: {text}"
        )

    @pytest.mark.asyncio
    async def test_retry_all_fail_loop_continues(
        self, init_db, monkeypatch, caplog
    ):
        """Si tots els retries fallen, el loop continua (no aturada)."""
        import logging

        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await real_sleep(0)

        monkeypatch.setattr("core.lifespan_tokens.asyncio.sleep", fast_sleep)

        call_count = {"n": 0}

        def always_fail(ttl_minutes=30):
            call_count["n"] += 1
            raise RuntimeError("permanent failure")

        monkeypatch.setattr(lt, "regenerate_bootstrap_token", always_fail)

        with caplog.at_level(logging.ERROR, logger="core.lifespan_tokens"):
            task = asyncio.create_task(_bootstrap_token_renewal_loop(1, 30))
            await real_sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Com a minim la crida inicial + 3 retries = 4 (i pot passar al segon cicle)
        assert call_count["n"] >= 4
        text = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "exhausted" in text or "retries" in text
