"""F5.4 Bug — Real-byte download progress tracker for the installer wizard.

Replaces the legacy `pct += 3 / 1.5s` fake-progress polling at
core/endpoints/installer.py::_stream_mlx with two complementary sources of
truth:

1. ``SSEProgressTqdm`` — subclass of tqdm.tqdm wired to a thread-safe
   ``queue.Queue``. Used as the ``tqdm_class`` argument of
   ``huggingface_hub.snapshot_download`` so we capture every byte the
   Python downloader streams.

2. ``DirSizePoller`` — polls the destination directory size at a coarse
   interval (3s) with mtime-change detection to avoid repeated ``du -s``
   on idle directories. The xet protocol (Rust binary used by hf_xet) does
   NOT write to Python tqdm; without this fallback we'd see zero progress
   for big-file transfers.

The ``DownloadTracker`` combines both sources with an exponentially weighted
moving average (EWMA, window 15 s — Turing #2 C1) so the surfaced speed and
ETA don't jitter on small-chunk transfers. Returns at any moment the
``max(tqdm_n, dir_size)`` so the displayed progress never goes backwards.

Threading contract (see Turing #2 C1):
  * The tqdm callback runs inside the ``_dl_executor`` worker thread.
  * ``stdlib_queue.Queue`` is thread-safe by design (internal Lock).
  * Consumers ``get_nowait()`` from the main asyncio loop.
  * The class-level shared queue is safe ONLY because the executor has
    max_workers=1 (sequential downloads). If multi-download is needed in
    future, refactor to instance-level queues passed via kwargs.
"""

from __future__ import annotations

import collections
import os
import queue as stdlib_queue
import time
from pathlib import Path
from typing import Any, Deque, Optional

try:  # tqdm is a transitive dependency of huggingface_hub; pinned in reqs
    from tqdm import tqdm as _tqdm
except ImportError:  # pragma: no cover — tqdm is always present in the bundle
    _tqdm = None  # type: ignore[assignment]


# Default polling interval for the directory-size fallback. 3s is the
# Turing #2 recommendation (1s was too aggressive on dirs with many files).
DEFAULT_DIR_POLL_SECONDS = 3.0

# EWMA window for speed/ETA smoothing. Turing #2: 15s (was 5s) gives a
# more stable display on jittery networks.
DEFAULT_EWMA_WINDOW_SECONDS = 15.0


# ──────────────────────────────────────────────────────────────────────────────
# hf_xet detection — Turing #2 C1
# ──────────────────────────────────────────────────────────────────────────────


def is_xet_active() -> bool:
    """Detect whether huggingface_hub is using the hf_xet Rust transfer.

    hf_xet does NOT write to Python tqdm, so when it's active we must rely
    on directory-size polling for progress. Detection is conservative:
    returns True if any of the known hf_xet activation paths are present.

    F5.6 Bloc 8: honour ``HF_HUB_DISABLE_XET`` first. When the constant
    evaluates True (because the env var was set BEFORE huggingface_hub
    import — see lib.rs::spawn_sidecar_process) huggingface_hub bypasses
    xet entirely regardless of whether the ``hf_xet`` package is installed.
    Without this short-circuit ``is_xet_active`` returned True simply on
    package presence, which made the dir-size poller and the "xet active"
    log line misleading even when xet was effectively off.
    """
    # 0. Authoritative source — the constant huggingface_hub reads at
    #    import time. If True, xet is off, full stop.
    try:
        from huggingface_hub.constants import HF_HUB_DISABLE_XET
        if HF_HUB_DISABLE_XET:
            return False
    except ImportError:
        pass
    # 1. Explicit env-var opt-in still recognised by older huggingface_hub
    if os.environ.get("HF_HUB_ENABLE_HF_TRANSFER", "").lower() in ("1", "true", "yes"):
        return True
    # 2. hf_xet package present in the runtime — when installed,
    #    huggingface_hub >= 1.0 uses it by default for large files
    try:
        import hf_xet  # noqa: F401  pyright: ignore[reportMissingImports]
        return True
    except ImportError:
        pass
    # 3. Legacy hf_transfer (predecessor of hf_xet)
    try:
        import hf_transfer  # noqa: F401  pyright: ignore[reportMissingImports]
        return True
    except ImportError:
        pass
    return False


# ──────────────────────────────────────────────────────────────────────────────
# SSEProgressTqdm — captures Python-tqdm bytes via a thread-safe Queue
# ──────────────────────────────────────────────────────────────────────────────


# Class-level queue. F5.5 G13: protected by a Lock to prevent concurrent
# set_tqdm_queue() calls from racing (two simultaneous SSE requests could
# overwrite each other's queue). max_workers=1 prevents two simultaneous
# downloads, but the Lock makes the invariant explicit and safe.
_TQDM_QUEUE: Optional["stdlib_queue.Queue[dict[str, Any]]"] = None
_TQDM_QUEUE_LOCK = __import__("threading").Lock()


def set_tqdm_queue(q: Optional["stdlib_queue.Queue[dict[str, Any]]"]) -> None:
    """Install (or clear) the queue used by SSEProgressTqdm to publish bytes."""
    global _TQDM_QUEUE
    with _TQDM_QUEUE_LOCK:
        _TQDM_QUEUE = q


if _tqdm is not None:  # pragma: no branch — always true when tqdm is installed
    class SSEProgressTqdm(_tqdm):  # type: ignore[misc, valid-type]
        """tqdm.tqdm subclass that publishes update() bytes to a shared queue.

        Used as ``tqdm_class`` argument to
        ``huggingface_hub.snapshot_download`` so every chunk update is
        forwarded to the SSE stream consumer in the main loop.

        F5.5 G13: reads _TQDM_QUEUE under _TQDM_QUEUE_LOCK to prevent a race
        where a concurrent set_tqdm_queue(None) nulls the reference after we
        checked it but before we call put_nowait.

        See module docstring for threading contract.
        """

        def update(self, n: int = 1) -> Optional[bool]:  # type: ignore[override]
            result = super().update(n)
            with _TQDM_QUEUE_LOCK:
                q = _TQDM_QUEUE
            if q is not None:
                try:
                    q.put_nowait({"n": int(self.n), "total": int(self.total or 0)})
                except stdlib_queue.Full:
                    # Backpressure: drop the event; the dir poller will
                    # catch up on the next tick and the next tqdm event
                    # will overwrite the stale value via DownloadTracker.
                    pass
            return result
else:  # pragma: no cover — tqdm always present in production
    class SSEProgressTqdm:  # type: ignore[no-redef]
        """No-op fallback when tqdm is not installed."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: D401
            pass

        def update(self, _n: int = 1) -> None:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# DirSizePoller — coarse-grained file-size fallback for hf_xet transfers
# ──────────────────────────────────────────────────────────────────────────────


def _dir_size_bytes(root: Path) -> int:
    """Return the sum of all file sizes under ``root``. Cheap on small
    cache dirs; on a HF snapshot dir with a handful of files this is
    O(files) (typically <50). Returns 0 if the dir does not exist."""
    if not root.exists():
        return 0
    total = 0
    try:
        for entry in root.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        return total
    return total


def _dir_mtime(root: Path) -> float:
    """Return the most-recent mtime of any file under ``root``, or 0.0 if
    the dir does not exist or is empty."""
    if not root.exists():
        return 0.0
    latest = 0.0
    try:
        for entry in root.rglob("*"):
            if entry.is_file():
                try:
                    mt = entry.stat().st_mtime
                    if mt > latest:
                        latest = mt
                except OSError:
                    pass
    except OSError:
        return latest
    return latest


# ──────────────────────────────────────────────────────────────────────────────
# DownloadTracker — combines tqdm queue + dir polling with EWMA smoothing
# ──────────────────────────────────────────────────────────────────────────────


class DownloadTracker:
    """Tracks bytes-downloaded over time and surfaces speed/ETA.

    Combines:
      * tqdm queue events (preferred when available)
      * directory-size polling (fallback for hf_xet)

    The current ``bytes_done`` is always ``max(tqdm_n, dir_size)`` so the
    displayed progress never goes backwards even if a slow tqdm event
    arrives after the dir poller has already observed the bytes on disk.

    Speed is computed via a deque of (timestamp, bytes) samples kept inside
    the EWMA window; ETA = remaining_bytes / speed_bps (clamped to >=1).
    """

    def __init__(
        self,
        dest_dir: Path,
        expected_total_bytes: int = 0,
        ewma_window_s: float = DEFAULT_EWMA_WINDOW_SECONDS,
        dir_poll_seconds: float = DEFAULT_DIR_POLL_SECONDS,
    ) -> None:
        self._dest = dest_dir
        self._expected = max(0, int(expected_total_bytes))
        self._ewma_window_s = ewma_window_s
        self._dir_poll_seconds = dir_poll_seconds
        self._tqdm_n: int = 0
        self._tqdm_total: int = 0
        self._dir_bytes: int = 0
        self._last_dir_check: float = 0.0
        self._last_dir_mtime: float = 0.0
        self._samples: Deque[tuple[float, int]] = collections.deque(maxlen=256)
        self._initial_dir_bytes: int = _dir_size_bytes(dest_dir)

    @property
    def bytes_total(self) -> int:
        """Best-known total. Prefer the tqdm-reported total (covers all
        files in the snapshot) over the caller-provided expected value."""
        return self._tqdm_total or self._expected

    @property
    def bytes_done(self) -> int:
        """Bytes downloaded so far. Always >= last observation (monotonic).

        F5.5 G9: pure getter — no longer mutates _samples. Call
        record_sample() explicitly once per poll cycle instead.
        """
        return max(self._tqdm_n, max(0, self._dir_bytes - self._initial_dir_bytes))

    def record_sample(self) -> None:
        """Add a speed-estimation sample. Call exactly once per poll cycle
        (inside to_event) so _samples never accumulates duplicates."""
        observed = self.bytes_done
        if not self._samples or self._samples[-1][1] < observed:
            self._samples.append((time.monotonic(), observed))
            self._prune_samples()

    @property
    def percent(self) -> int:
        total = self.bytes_total
        if total <= 0:
            return 0
        return min(99, int(self.bytes_done * 100 / total))

    @property
    def speed_bps(self) -> float:
        """Bytes per second over the EWMA window. 0 if too few samples."""
        if len(self._samples) < 2:
            return 0.0
        now = time.monotonic()
        # Find the oldest sample inside the window
        window_start = now - self._ewma_window_s
        prior = next(
            (s for s in self._samples if s[0] >= window_start),
            self._samples[0],
        )
        dt = self._samples[-1][0] - prior[0]
        if dt <= 0:
            return 0.0
        db = self._samples[-1][1] - prior[1]
        return max(0.0, db / dt)

    @property
    def eta_seconds(self) -> int:
        speed = self.speed_bps
        if speed < 1.0:
            return 0
        remaining = max(0, self.bytes_total - self.bytes_done)
        return int(remaining / speed)

    # ──────────────────── update sources ────────────────────

    def update_from_tqdm(self, n: int, total: int) -> None:
        """Merge a tqdm-published event. Caller guarantees no concurrent
        callers from multiple worker threads (single-worker executor)."""
        if n > self._tqdm_n:
            self._tqdm_n = int(n)
        if total > 0 and total != self._tqdm_total:
            self._tqdm_total = int(total)

    def drain_tqdm_queue(self, q: "stdlib_queue.Queue[dict[str, Any]]") -> None:
        """Consume all available tqdm events from the queue, non-blocking."""
        try:
            while True:
                ev = q.get_nowait()
                self.update_from_tqdm(ev.get("n", 0), ev.get("total", 0))
        except stdlib_queue.Empty:
            return

    def maybe_poll_dir(self, force: bool = False) -> None:
        """Refresh ``_dir_bytes`` from disk if the poll interval has
        elapsed AND something looks like it has changed (mtime delta).

        The mtime check avoids redundant ``rglob`` scans on idle dirs —
        Turing #2 recommendation."""
        now = time.monotonic()
        if not force and (now - self._last_dir_check) < self._dir_poll_seconds:
            return
        self._last_dir_check = now
        try:
            mt = _dir_mtime(self._dest)
        except OSError:
            return
        if force or mt > self._last_dir_mtime or self._dir_bytes == 0:
            self._last_dir_mtime = mt
            self._dir_bytes = _dir_size_bytes(self._dest)

    def final_stat(self) -> None:
        """Force a final dir poll on stream end so very small models
        (which finish before the regular polling interval) still emit
        bytes_done."""
        self.maybe_poll_dir(force=True)

    # ──────────────────── serialisation ────────────────────

    def to_event(self, percent_override: Optional[int] = None) -> dict[str, Any]:
        """Serialise current state to an SSE-friendly dict.

        Calls record_sample() so every emitted event contributes exactly one
        speed-estimation sample (F5.5 G9: side-effect removed from bytes_done).
        """
        self.record_sample()
        return {
            "type": "progress",
            "percent": percent_override if percent_override is not None else self.percent,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "speed_bps": int(self.speed_bps),
            "eta_s": self.eta_seconds,
        }

    # ──────────────────── private ────────────────────

    def _prune_samples(self) -> None:
        """Drop samples older than the EWMA window to bound memory."""
        if not self._samples:
            return
        cutoff = time.monotonic() - self._ewma_window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
