"""F5.4 Fase 4a — tests for the real-byte progress tracker.

Covers DownloadTracker (combines tqdm queue + dir polling, EWMA), the
SSEProgressTqdm shim, hf_xet detection, and the integration into
_stream_mlx (fake tqdm class injected so we don't hit the network).
"""

from __future__ import annotations

import queue as stdlib_queue
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# DownloadTracker
# ──────────────────────────────────────────────────────────────────────────────


class TestDownloadTracker:
    def test_bytes_done_uses_max_of_tqdm_and_dir(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker

        # Pre-seed a file so dir size > 0
        (tmp_path / "f1").write_bytes(b"\x00" * 1024)

        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=100_000)
        # Tracker captures initial dir bytes so further dir growth shows
        # as "downloaded".
        tracker.update_from_tqdm(n=500, total=10_000)
        # Add a new file of 4 KB → dir grew by 4 KB
        (tmp_path / "f2").write_bytes(b"\x00" * 4096)
        tracker.maybe_poll_dir(force=True)

        # bytes_done = max(tqdm.n=500, dir_delta=4096) = 4096
        assert tracker.bytes_done == 4096

    def test_percent_uses_tqdm_total_when_available(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker
        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=100)
        tracker.update_from_tqdm(n=50, total=1000)
        # 50 / 1000 = 5%
        assert tracker.percent == 5

    def test_percent_falls_back_to_expected_when_no_tqdm_total(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker
        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=200)
        # No tqdm event yet; pre-seed file so dir polling reports 50 bytes
        (tmp_path / "f").write_bytes(b"\x00" * 50)
        # Need to start tracker AFTER seeding so initial_dir_bytes captures it
        tracker2 = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=200)
        (tmp_path / "f2").write_bytes(b"\x00" * 100)  # +100 bytes downloaded
        tracker2.maybe_poll_dir(force=True)
        # 100 / 200 = 50%
        assert tracker2.percent == 50

    def test_percent_clamped_at_99(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker
        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=100)
        tracker.update_from_tqdm(n=1_000_000, total=100)
        assert tracker.percent == 99

    def test_drain_tqdm_queue_applies_all_events(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker
        q: stdlib_queue.Queue = stdlib_queue.Queue()
        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=1000)
        q.put_nowait({"n": 100, "total": 1000})
        q.put_nowait({"n": 200, "total": 1000})
        q.put_nowait({"n": 300, "total": 1000})
        tracker.drain_tqdm_queue(q)
        assert tracker.bytes_done >= 300

    def test_to_event_returns_sse_compatible_dict(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker
        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=1000)
        tracker.update_from_tqdm(n=250, total=1000)
        ev = tracker.to_event()
        assert ev["type"] == "progress"
        assert ev["percent"] == 25
        assert ev["bytes_done"] == 250
        assert ev["bytes_total"] == 1000
        assert "speed_bps" in ev
        assert "eta_s" in ev

    def test_speed_bps_after_multiple_samples(self, tmp_path):
        from core.endpoints.installer_progress import DownloadTracker
        tracker = DownloadTracker(dest_dir=tmp_path, expected_total_bytes=10_000)
        # Two manual samples spaced ~50ms apart at 100B and 600B.
        # F5.5 G9: use record_sample() explicitly (bytes_done is now a pure getter).
        tracker.update_from_tqdm(n=100, total=10_000)
        tracker.record_sample()
        time.sleep(0.05)
        tracker.update_from_tqdm(n=600, total=10_000)
        tracker.record_sample()
        speed = tracker.speed_bps
        # Should be > 0 (we downloaded 500 bytes in ~50ms → ~10 KB/s).
        assert speed > 0


# ──────────────────────────────────────────────────────────────────────────────
# hf_xet detection
# ──────────────────────────────────────────────────────────────────────────────


class TestIsXetActive:
    def test_env_var_opt_in(self, monkeypatch):
        from core.endpoints.installer_progress import is_xet_active
        monkeypatch.setenv("HF_HUB_ENABLE_HF_TRANSFER", "1")
        assert is_xet_active() is True

    def test_hf_xet_present(self, monkeypatch):
        # hf_xet is in the venv (verified pre-flight), so this should be True.
        from core.endpoints.installer_progress import is_xet_active
        monkeypatch.delenv("HF_HUB_ENABLE_HF_TRANSFER", raising=False)
        # The actual import in is_xet_active will succeed because hf_xet is
        # installed in the DEV venv (preflight verification).
        assert is_xet_active() is True


# ──────────────────────────────────────────────────────────────────────────────
# SSEProgressTqdm publishes to the installed queue
# ──────────────────────────────────────────────────────────────────────────────


class TestSSEProgressTqdm:
    """Use file=StringIO + mininterval=0 to silence output without breaking
    tqdm's internal n counter (which `disable=True` does break)."""

    @staticmethod
    def _silent_tqdm_kwargs() -> dict:
        """Silence tqdm output without disabling the n counter.

        Note: `disable=False` is REQUIRED — without it tqdm autodetects no
        TTY and silently turns into a no-op (super().update() returns
        without touching self.n, breaking our SSEProgressTqdm shim).
        """
        import io
        return {"file": io.StringIO(), "mininterval": 0, "disable": False}

    def test_update_publishes_to_queue(self):
        from core.endpoints.installer_progress import SSEProgressTqdm, set_tqdm_queue
        q: stdlib_queue.Queue = stdlib_queue.Queue()
        set_tqdm_queue(q)
        try:
            t = SSEProgressTqdm(total=1000, **self._silent_tqdm_kwargs())
            t.update(50)
            t.update(150)
        finally:
            set_tqdm_queue(None)

        events = []
        try:
            while True:
                events.append(q.get_nowait())
        except stdlib_queue.Empty:
            pass
        assert events, "Queue empty — tqdm did not publish"
        # Latest event reflects cumulative n.
        assert events[-1]["n"] == 200
        assert events[-1]["total"] == 1000

    def test_update_with_no_queue_does_not_crash(self):
        """When the queue is not installed the tqdm wrapper must still work
        (used standalone in tests or when the installer is not active)."""
        from core.endpoints.installer_progress import SSEProgressTqdm, set_tqdm_queue
        set_tqdm_queue(None)
        t = SSEProgressTqdm(total=100, **self._silent_tqdm_kwargs())
        # Must not raise.
        t.update(5)
        assert t.n == 5


# ──────────────────────────────────────────────────────────────────────────────
# Integration: _stream_mlx uses tracker (no fake +3% / 1.5s loop)
# ──────────────────────────────────────────────────────────────────────────────


class TestStreamMlxRealProgress:
    @pytest.mark.asyncio
    async def test_stream_mlx_emits_real_byte_events_not_fake_pct(self, tmp_path, monkeypatch):
        """Patch snapshot_download to simulate a download that writes files
        progressively to dest. Verify the SSE events report bytes_done and
        a final percent==100, AND that the events are not the legacy
        evenly-spaced +3% pattern."""
        from core.endpoints import installer as installer_mod
        from core.endpoints.installer import _stream_mlx

        # Redirect models_dir to tmp_path so the test doesn't touch real cache.
        monkeypatch.setattr(installer_mod, "_models_dir", lambda: tmp_path)

        # Fake snapshot_download: writes a few files to the dest dir,
        # spaced ~50ms apart, to simulate streaming bytes.
        def _fake_snapshot_download(repo_id, local_dir, tqdm_class=None, **kw):
            import io as _io
            dest = Path(local_dir)
            dest.mkdir(parents=True, exist_ok=True)
            # Drive the SSEProgressTqdm via tqdm_class — simulate the bytes
            # huggingface_hub would publish. disable=False is needed because
            # stderr in a pytest run isn't a TTY (tqdm would otherwise no-op).
            if tqdm_class is not None:
                t = tqdm_class(
                    total=10_000, file=_io.StringIO(), mininterval=0,
                    disable=False,
                )
                for chunk in (2000, 3000, 2500, 2500):
                    (dest / f"part_{chunk}").write_bytes(b"\x00" * chunk)
                    t.update(chunk)
                    time.sleep(0.05)

        monkeypatch.setattr(
            "huggingface_hub.snapshot_download",
            _fake_snapshot_download,
        )

        # Build a fake Request that is never disconnected
        request = MagicMock()
        async def _not_disconnected():
            return False
        request.is_disconnected = _not_disconnected

        events = []
        async for ev in _stream_mlx("ns/test-model", request):
            events.append(ev)

        assert events, "No SSE events emitted"
        # Last event must be 100%.
        assert events[-1]["percent"] == 100
        # Real-byte events must include bytes_done and bytes_total.
        bytes_events = [ev for ev in events if ev.get("bytes_total", 0) > 0]
        assert bytes_events, (
            f"No real-byte events emitted (only fake-pct ones?): {events}"
        )
        # bytes_done must be monotonic non-decreasing.
        for a, b in zip(bytes_events, bytes_events[1:]):
            assert b["bytes_done"] >= a["bytes_done"]
        # Final byte total is at least 10000 (sum of the chunks above).
        assert events[-1]["bytes_total"] >= 10_000
