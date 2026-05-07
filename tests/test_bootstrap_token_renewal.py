"""
Bug 11 — Bootstrap token expires without recovery.
Implementation: asyncio background task that every (ttl-5)*60 seconds
regenerates the token via regenerate_bootstrap_token().

Tests:
- regenerate_bootstrap_token generates a token different from the previous one
- start_bootstrap_token_renewal starts a live asyncio.Task
- stop_bootstrap_token_renewal cancels cleanly (without exception)
- the task is cancellable while sleeping
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
    # Always clean up the task between tests
    await stop_bootstrap_token_renewal()


class TestRegenerateBootstrapToken:

    def test_regenerate_returns_new_token(self, init_db):
        old = generate_bootstrap_token()
        set_bootstrap_token(old, ttl_minutes=30)
        new = regenerate_bootstrap_token(ttl_minutes=30)
        assert new != old
        assert new.startswith("Nexe-")
        # And it is persisted
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
        # The first one must be cancelled
        await asyncio.sleep(0)  # let cancellation propagate
        assert first.cancelled() or first.done()
        assert lt._renewal_task is second
        await stop_bootstrap_token_renewal()

    @pytest.mark.asyncio
    async def test_stop_when_no_task_is_safe(self, init_db):
        # Without having started anything
        await stop_bootstrap_token_renewal()  # no exception


class TestRenewalLoopRegenerates:
    """Verifies that the loop calls regenerate after the sleep elapses."""

    @pytest.mark.asyncio
    async def test_loop_regenerates_after_interval(self, init_db, monkeypatch):
        # Set initial token
        initial = "Nexe-INITIALAAAAAAAAAAAAAAAAAAAAAAAA"
        set_bootstrap_token(initial, ttl_minutes=30)

        regen_calls = []

        # Patch sleep to make it instantaneous
        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await real_sleep(0)

        monkeypatch.setattr("core.lifespan_tokens.asyncio.sleep", fast_sleep)

        # Patch regenerate to count calls
        original_regen = lt.regenerate_bootstrap_token

        def counting_regen(ttl_minutes=30):
            regen_calls.append(ttl_minutes)
            return original_regen(ttl_minutes=ttl_minutes)

        monkeypatch.setattr(lt, "regenerate_bootstrap_token", counting_regen)

        task = asyncio.create_task(_bootstrap_token_renewal_loop(1, 30))
        # Give time for a few iterations
        await real_sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(regen_calls) >= 1
        # And the token has changed
        info = get_bootstrap_token()
        assert info["token"] != initial


class TestRenewalRetryBackoff:
    """Fix Consultor passada 1 — Finding 4: retry exponencial quan regenerate falla."""

    @pytest.mark.asyncio
    async def test_retry_recovers_after_transient_failures(
        self, init_db, monkeypatch, caplog
    ):
        """If regenerate fails 2 times and recovers on the 3rd, there is a 'recovered' message."""
        import logging

        # Instantaneous sleep
        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await real_sleep(0)

        monkeypatch.setattr("core.lifespan_tokens.asyncio.sleep", fast_sleep)

        # Regenerate fails 2 times, third call OK
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

        # There have been at least 3 calls (1 initial + 2 retries)
        assert calls["n"] >= 3
        # There must be a 'recovered' message
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "recovered" in text.lower(), (
            f"no s'ha trobat missatge 'recovered' als logs: {text}"
        )

    @pytest.mark.asyncio
    async def test_retry_all_fail_loop_continues(
        self, init_db, monkeypatch, caplog
    ):
        """If all retries fail, the loop continues (no stop)."""
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

        # At least the initial call + 3 retries = 4 (and may spill into the second cycle)
        assert call_count["n"] >= 4
        text = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "exhausted" in text or "retries" in text
