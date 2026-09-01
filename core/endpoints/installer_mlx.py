"""The MLX install path of the wizard: snapshot download from the Hub.

Split out of ``core.endpoints.installer`` (finding #969). The download itself
is blocking, so it runs on the shared single-worker executor of
``installer_shared`` — reached through the module so there is exactly one
queue, which is the whole point of it being max_workers=1.

Real byte progress comes from ``installer_progress`` (imported inside the
function, as it was: it pulls heavier transitive deps).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading as _threading
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import Request

from core.endpoints import installer_shared

logger = logging.getLogger(__name__)

def _hf_download_with_retry(
    model_id: str,
    dest: Path,
    tqdm_class: type,
    cancel_ev: "_threading.Event",
    errors: "list[Exception]",
) -> bool:
    """Attempt snapshot_download up to 3×. Returns True if cancelled between retries."""
    from huggingface_hub import snapshot_download as _sd  # type: ignore[import]
    from huggingface_hub.utils import (  # type: ignore[import]
        HfHubHTTPError, RepositoryNotFoundError, GatedRepoError, RevisionNotFoundError,
    )
    for attempt in range(3):
        try:
            _sd(repo_id=model_id, local_dir=str(dest), tqdm_class=tqdm_class)  # nosec B615
            break
        except (RepositoryNotFoundError, GatedRepoError, RevisionNotFoundError) as exc:
            errors.append(exc)
            break
        except HfHubHTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500:
                errors.append(exc)
                break
            if attempt < 2:
                logger.warning("installer: HfHubHTTPError attempt %d/3 (status=%s): %s", attempt + 1, status, exc)
                time.sleep(5)
                if cancel_ev.is_set():
                    return True
                continue
            errors.append(exc)
        except Exception as exc:  # noqa: BLE001
            if attempt < 2:
                logger.warning("installer: download error attempt %d/3: %s", attempt + 1, exc)
                time.sleep(5)
                if cancel_ev.is_set():
                    return True
                continue
            errors.append(exc)
    return False

def _get_finalizing_hint(
    ev: dict,
    pct: int,
    finalizing_announced: bool,
    slow_since_t: "float | None",
    now: float,
    stuck_speed_bps: int = 100 * 1024,
    stuck_window_s: float = 30.0,
) -> "tuple[dict | None, float | None]":
    """Return (hint_event_or_None, new_slow_since_t) for the stuck-99% handler.

    Extracts the branching logic from _stream_mlx to keep its CCN ≤ 15.
    Returns (hint, slow_since_t) where hint is non-None only once: the first
    time speed stays below stuck_speed_bps for stuck_window_s at pct >= 99.
    """
    if finalizing_announced or pct < 99:
        return None, slow_since_t
    if ev["speed_bps"] < stuck_speed_bps:
        if slow_since_t is None:
            return None, now
        if (now - slow_since_t) >= stuck_window_s:
            hint = dict(ev)
            hint["finalizing"] = True
            hint["message"] = "Finalitzant últims chunks (pot trigar 1-3 min)…"
            return hint, slow_since_t
        return None, slow_since_t
    return None, None  # speed recovered — reset timer


async def _stream_mlx(model_id: str, request: Request) -> AsyncIterator[dict]:
    """Download an MLX model via huggingface_hub.snapshot_download.

    real-byte progress via SSEProgressTqdm + DirSize polling
    (replaces the legacy pct += 3 / 1.5s fake-progress loop). hf_xet
    transfers don't write to Python tqdm, so we always run the dir poller
    in parallel — the DownloadTracker takes max(tqdm_n, dir_size).
    """
    import queue as stdlib_queue

    from core.endpoints.installer_progress import (
        DownloadTracker,
        SSEProgressTqdm,
        is_xet_active,
        set_tqdm_queue,
    )

    model_name = installer_shared._safe_model_basename(model_id)
    dest = installer_shared._models_dir() / model_name
    dest.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_event_loop()
    done_ev = asyncio.Event()
    # cancel event so _run() skips snapshot_download if the client
    # disconnects before the worker thread actually starts. Cannot interrupt
    # snapshot_download mid-flight (no hook), but prevents a new download from
    # starting after an AbortController cancel on the frontend.
    # _threading now imported at the top of the module (for installer_shared._ollama_install_lock).
    cancel_ev = _threading.Event()
    errors: list[Exception] = []

    # Thread-safe queue. Class-level shared mutable state is safe ONLY
    # because installer_shared._dl_executor has max_workers=1 (serialised downloads).
    tqdm_queue: "stdlib_queue.Queue[dict]" = stdlib_queue.Queue(maxsize=2048)
    set_tqdm_queue(tqdm_queue)
    xet_active = is_xet_active()

    def _run() -> None:
        # core/lifespan.py forces HF_HUB_OFFLINE=1 to prevent fastembed from
        # phoning home on startup. The constant is read once at import time,
        # so os.environ changes don't propagate — we must monkey-patch the
        # constant directly. Restore on exit.
        # skip download if client already disconnected before we started.
        if cancel_ev.is_set():
            loop.call_soon_threadsafe(done_ev.set)
            return

        from huggingface_hub import constants as hf_constants  # type: ignore[import]
        import huggingface_hub as _hf  # type: ignore[import]

        prev_env = os.environ.pop("HF_HUB_OFFLINE", None)
        prev_const = hf_constants.HF_HUB_OFFLINE
        hf_constants.HF_HUB_OFFLINE = False
        prev_tqdm_disable = os.environ.pop("TQDM_DISABLE", None)
        logger.info(
            "installer: starting MLX download %s -> %s (xet_active=%s, hf=%s)",
            model_id, dest, xet_active, _hf.__version__,
        )
        try:
            cancelled = _hf_download_with_retry(model_id, dest, SSEProgressTqdm, cancel_ev, errors)
            if cancelled:
                logger.info("installer: download cancelled by user between retries")
        finally:
            hf_constants.HF_HUB_OFFLINE = prev_const
            if prev_env is not None:
                os.environ["HF_HUB_OFFLINE"] = prev_env
            if prev_tqdm_disable is not None:
                os.environ["TQDM_DISABLE"] = prev_tqdm_disable
            loop.call_soon_threadsafe(done_ev.set)

    loop.run_in_executor(installer_shared._dl_executor, _run)

    tracker = DownloadTracker(dest_dir=dest)
    tracker.maybe_poll_dir(force=True)  # stabilise initial baseline
    if xet_active:
        logger.info(
            "installer: hf_xet active for %s — relying on dir polling for progress",
            model_id,
        )

    try:
        last_pct = -1
        # WebKit SSE keepalive: WebKit (used by Tauri's
        # WebView on macOS) drops EventSource/fetch streams that go silent
        # for >~30s. Emit a 'keepalive' event every 15s so the frontend
        # stays connected even when hf_xet has been transferring a giant
        # single file with no per-chunk updates.
        # Stuck-99% handler: when speed drops below
        # 100 KB/s for >30s while we're not done yet, surface a
        # "finalizing" hint so the user understands the silence is normal
        # checksum/extract work (huggingface_hub 1.1.x bug + xet finalize).
        KEEPALIVE_S = 15.0
        STUCK_LOW_SPEED_BPS = 100 * 1024  # 100 KB/s
        STUCK_WINDOW_S = 30.0
        last_emit_t = time.monotonic()
        slow_since_t: float | None = None
        finalizing_announced = False

        # Poll cadence: 250ms for the queue (cheap), 3s effective for the
        # dir poller (debounced inside maybe_poll_dir).
        while not done_ev.is_set():
            await asyncio.sleep(0.25)
            if await request.is_disconnected():
                cancel_ev.set()  # prevent worker from starting if not yet running
                return
            tracker.drain_tqdm_queue(tqdm_queue)
            tracker.maybe_poll_dir()
            ev = tracker.to_event()
            pct = ev["percent"]
            now = time.monotonic()
            # Stuck-99% handler — logic extracted to _get_finalizing_hint.
            hint_ev, slow_since_t = _get_finalizing_hint(
                ev, pct, finalizing_announced, slow_since_t, now,
                STUCK_LOW_SPEED_BPS, STUCK_WINDOW_S,
            )
            if hint_ev is not None:
                finalizing_announced = True
                yield hint_ev
                last_emit_t = now
                continue
            # Only emit when the percent changes — keeps the SSE stream
            # lean and the WebView responsive.
            if pct != last_pct:
                last_pct = pct
                yield ev
                last_emit_t = now
                continue
            # keepalive when nothing else has been emitted.
            if (now - last_emit_t) >= KEEPALIVE_S:
                yield {"type": "keepalive", "ts": now}
                last_emit_t = now

        if errors:
            raise errors[0]

        # Final stat: forces a last dir scan so very small models (which
        # finish before the regular 3s poll) still emit non-zero bytes.
        tracker.final_stat()
        final_ev = tracker.to_event(percent_override=100)
        yield final_ev
    finally:
        # Always release the class-level queue installer so the next
        # download starts with a fresh tracker.
        set_tqdm_queue(None)
