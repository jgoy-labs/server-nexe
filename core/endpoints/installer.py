"""
HTTP endpoints for the onboarding wizard.

All endpoints are intentionally unauthenticated — the user has no API key
yet when running through the wizard. The wizard is only reachable from the
local WebView (same-machine, loopback only) so the risk is minimal.

Endpoints:
  GET  /installer/download   — SSE stream: model download progress
  POST /installer/ollama     — SSE stream: Ollama install check
  POST /installer/finalize   — JSON: {api_key, status} + persists onboarding state
  GET  /installer/finalize   — JSON: {api_key, status} — legacy, no state persisted
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import threading as _threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.installer_constants import VALID_ENGINES as _VALID_ENGINES
from core.onboarding_state import (
    OnboardingState,
    _read_hf_token_from_keychain,
    _store_hf_token_in_keychain,
)
from core.proc_utils import no_window_kwargs

# cleanup: import DownloadIntegrityError at top to
# avoid pyright `reportPossiblyUnboundVariable` when the lazy import inside
# the SHA256 verification block is re-used in the except clause. The lazy
# import is kept below (for verify_download_integrity which has heavier
# transitive deps); the class itself is small and import-safe.
try:
    from installer.download_verify import DownloadIntegrityError  # type: ignore[import]
except ImportError:  # pragma: no cover - PBS bundle resilience
    class DownloadIntegrityError(Exception):  # type: ignore[no-redef]
        """Fallback if installer.download_verify is not importable (PBS bundle)."""

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/installer", tags=["installer"])

# canonical fastembed model id for the wizard. Kept here (not
# imported from memory.embeddings.constants) so the installer remains
# import-safe in PBS bundles where memory/structlog chains can fail —
# see memory `feedback_dmg_structlog_import.md`.
_EMBEDDER_MODEL_ID = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# Single-worker executor for blocking download tasks (MLX snapshot_download).
_dl_executor = ThreadPoolExecutor(max_workers=1)

# Module-level lock to prevent concurrent Ollama installs.
# If the user clicks "install" twice, the first one grabs the lock and
# the second returns an informational message. Without this, two threads would
# run zip_extract on /Applications/Ollama.app simultaneously → corrupt app.
_ollama_install_lock = _threading.Lock()


async def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _models_dir() -> Path:
    """Return the canonical models directory (same as MLX auto-discovery).

    delegate to `core.paths.helpers.get_models_dir()` so the wizard
    download path matches the path scanned by the MLX/llama.cpp plugins. In
    sidecar mode `get_models_dir()` prefers `NEXE_DATA_DIR/models` but only
    returns it if it already exists; we pre-create it so the canonical path
    wins on a fresh install (otherwise it would fall back to cwd/storage).
    """
    data_env = os.environ.get("NEXE_DATA_DIR", "").strip()
    if data_env:
        (Path(data_env).expanduser() / "models").mkdir(parents=True, exist_ok=True)
    from core.paths.helpers import get_models_dir
    return get_models_dir()


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


def _find_ollama_bin() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    # MC-028: the well-known install paths are the canonical list shared with
    # ollama_runtime (deferred import keeps the layering gate green: core must
    # not import-time depend on plugins). Here we LOCATE an executable binary
    # (X_OK) for model installs — a different concern from spawning `serve`.
    from plugins.ollama_module.core.ollama_runtime import OLLAMA_BIN_CANDIDATES

    for candidate in OLLAMA_BIN_CANDIDATES:
        candidate = os.path.expanduser(candidate)  # expand ~ at call time, honouring current $HOME
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


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

    model_name = _safe_model_basename(model_id)
    dest = _models_dir() / model_name
    dest.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_event_loop()
    done_ev = asyncio.Event()
    # cancel event so _run() skips snapshot_download if the client
    # disconnects before the worker thread actually starts. Cannot interrupt
    # snapshot_download mid-flight (no hook), but prevents a new download from
    # starting after an AbortController cancel on the frontend.
    # _threading now imported at the top of the module (for _ollama_install_lock).
    cancel_ev = _threading.Event()
    errors: list[Exception] = []

    # Thread-safe queue. Class-level shared mutable state is safe ONLY
    # because _dl_executor has max_workers=1 (serialised downloads).
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

    loop.run_in_executor(_dl_executor, _run)

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


async def _install_ollama_and_locate() -> str:
    """Run ensure_ollama_installed and return the Ollama binary path.

    Falls back to the bundled Ollama.app binary when the CLI is installed but
    not yet registered on PATH. Raises RuntimeError with a UX-friendly,
    platform-specific message on any failure. The caller MUST hold
    ``_ollama_install_lock``.

    MC-031: single source of truth for the install→locate machine shared by
    _install_ollama_if_needed (RuntimeError path) and install_ollama_endpoint
    (SSE path), so the bundle fallback can never diverge between them again.
    """
    from installer.installer_ollama_install import ensure_ollama_installed
    loop = asyncio.get_event_loop()
    try:
        installed = await loop.run_in_executor(None, ensure_ollama_installed, True)
    except PermissionError:
        logger.exception("Ollama install: permission denied")
        _system = platform.system().lower()
        if _system == "darwin":
            raise RuntimeError(
                "No s'ha pogut instal.lar Ollama a /Applications/. "
                "Permis denegat. Instal.la'l manualment des d'ollama.com"
            ) from None
        if _system == "linux":
            raise RuntimeError(
                "Linux: l'instal.lador d'Ollama necessita sudo. "
                "Instal.la manualment des d'ollama.com/download/linux"
            ) from None
        raise RuntimeError("Ollama install permission denied") from None
    except Exception as exc:
        logger.exception("Ollama auto-install failed")
        raise RuntimeError(f"Ollama auto-install failed: {exc}") from exc
    if not installed:
        raise RuntimeError(
            "Ollama install did not complete. Restart the app or "
            "install manually from https://ollama.com"
        )
    ollama = _find_ollama_bin()
    if ollama:
        return ollama
    for _fallback in [
        "/Applications/Ollama.app/Contents/Resources/ollama",  # nosemgrep: absolute_path
        os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
    ]:
        if os.path.isfile(_fallback) and os.access(_fallback, os.X_OK):
            logger.info("ollama: CLI not yet registered; using bundle binary %s", _fallback)
            return _fallback
    raise RuntimeError(
        "Ollama installed but binary still not located. "
        "Open Ollama.app once to finish setup, then restart server-nexe."
    )


async def _install_ollama_if_needed(request: Request) -> str:
    """Auto-install Ollama and return its binary path. Raises RuntimeError on failure."""
    if await request.is_disconnected():
        raise RuntimeError("client disconnected before Ollama install")
    if not _ollama_install_lock.acquire(blocking=False):
        raise RuntimeError("Ja s'esta instal.lant Ollama en un altre proces")
    try:
        return await _install_ollama_and_locate()
    finally:
        _ollama_install_lock.release()


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


async def _stream_ollama(model_id: str, request: Request) -> AsyncIterator[dict]:
    """Download an Ollama model via ollama pull, streaming real progress.

    If Ollama is not present, install it automatically
    via ensure_ollama_installed(headless=True) abans del pull. Validat amb
    agentic audit 2026-05-20 (8 iters, 92K tokens, 4 correccions C1-C5).
    """
    ollama = _find_ollama_bin()
    if not ollama:
        yield {"type": "progress", "stage": "Instal.lant Ollama...", "percent": 0}
        ollama = await _install_ollama_if_needed(request)

    # In MINIMAL MODE (onboarding) the lifespan that auto-starts `ollama serve`
    # is skipped, and on Windows the standalone-zip install has no background
    # service — so `ollama pull` would hit a dead server (exit 1). Ensure the
    # server is up (spawn + wait for readiness) before pulling. Idempotent: it
    # returns early when Ollama is already running.
    from plugins.ollama_module.core.client import resolve_base_url
    from plugins.ollama_module.core.ollama_runtime import ensure_ollama_running

    yield {"type": "progress", "stage": "Iniciant Ollama...", "percent": 0}
    await ensure_ollama_running(resolve_base_url(), wait=True)

    proc = await asyncio.create_subprocess_exec(
        ollama, "pull", model_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        # Windows: CREATE_NO_WINDOW so the pull does not flash a console window
        # during onboarding (blocking: we read stdout=PIPE, so not detached).
        **no_window_kwargs(),
    )

    assert proc.stdout is not None  # noqa: S101  # nosec B101 — type guard: proc created with stdout=PIPE so stdout cannot be None by construction
    last_pct = -1
    async for raw in proc.stdout:
        if await request.is_disconnected():
            proc.kill()
            return
        line = raw.decode(errors="replace")
        m = re.search(r"(\d+)%", line)
        if m:
            pct = int(m.group(1))
            if pct != last_pct:
                last_pct = pct
                speed_m = re.search(r"([\d.]+\s*(?:MB|GB|KB)/s)", line)
                eta_m = re.search(r"(\d+[hm]\d*[ms]?|\d+s)", line)
                yield {
                    "type": "progress",
                    "percent": pct,
                    "speed": speed_m.group(1) if speed_m else "—",
                    "eta": eta_m.group(1) if eta_m else "—",
                }

    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ollama pull failed (exit {proc.returncode})")


def _fastembed_cache_dir() -> Path:
    """Resolve the canonical fastembed cache dir without importing the memory
    subsystem (which pulls structlog and can fail in PBS bundles pre-pip)."""
    env_override = os.environ.get("FASTEMBED_CACHE_DIR")
    if env_override:
        return Path(env_override).expanduser()
    return Path.home() / ".cache" / "fastembed"


def _fastembed_model_bytes(cache_dir: Path, model_id: str) -> int:
    """Sum bytes for a specific model in the fastembed cache.

    fastembed stores models under:
      models--{org}--{name}/snapshots/{sha}/onnx/   (HF-style layout)
    or legacy flat layout: {name}/

    Sums only the requested model's bytes so size estimates don't count
    other models already present in the cache.
    """
    safe_id = model_id.replace("/", "--")
    # Try HF-style layout first
    model_path = cache_dir / f"models--{safe_id}"
    if not model_path.exists():
        # Legacy flat layout (old fastembed versions)
        model_path = cache_dir / model_id.split("/")[-1]
    if not model_path.exists():
        return 0
    total = 0
    try:
        for f in model_path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        return total
    return total


def _embedder_model_present(cache_dir: Path) -> bool:
    """Heuristic: the embedder is present iff at least one onnx file exists
    under the cache. fastembed lays models under
    `models--xenova--paraphrase-multilingual-mpnet-base-v2/snapshots/<sha>/`
    or the legacy flat `paraphrase-multilingual-mpnet-base-v2/`."""
    if not cache_dir.exists():
        return False
    try:
        for f in cache_dir.rglob("*.onnx"):
            if f.is_file() and f.stat().st_size > 1024 * 1024:  # > 1 MB sanity
                return True
    except OSError:
        return False
    return False


# Expected total bytes for the multilingual mpnet base v2 ONNX model.
# Used for progress estimation when total is not otherwise knowable.
_EMBEDDER_EXPECTED_BYTES = 430 * 1024 * 1024  # ~430 MB (int8 ONNX)


async def _stream_embedder(model_id: str, request: Request) -> AsyncIterator[dict]:
    """Download the fastembed embedding model with directory-size polling.

    fastembed.TextEmbedding triggers a download from HuggingFace
    when the model is not in cache_dir. The download progress is not exposed
    via Python tqdm in a way we can intercept reliably across fastembed
    versions, so we poll the cache directory size at 1s intervals.

    If the model is already present (heuristic: an onnx file exists), we
    emit a single 'done' event with cached=True so the wizard skips the
    download and continues to the next step.
    """
    cache_dir = _fastembed_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Fast-path: model already in cache → no download needed.
    if _embedder_model_present(cache_dir):
        yield {
            "type": "progress",
            "percent": 100,
            "speed": "—",
            "eta": "—",
            "cached": True,
        }
        return

    initial_bytes = _fastembed_model_bytes(cache_dir, model_id)

    loop = asyncio.get_event_loop()
    done_ev = asyncio.Event()
    errors: list[Exception] = []

    def _run() -> None:
        try:
            # Import inside the thread so the import cost is paid off the
            # event loop and import errors propagate via `errors`.
            from fastembed import TextEmbedding  # type: ignore[import]
            # Constructing TextEmbedding triggers the snapshot download
            # if the model is not in cache_dir.
            TextEmbedding(model_id, cache_dir=str(cache_dir))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            loop.call_soon_threadsafe(done_ev.set)

    loop.run_in_executor(_dl_executor, _run)

    last_pct = -1
    while not done_ev.is_set():
        await asyncio.sleep(1.0)
        if await request.is_disconnected():
            return
        current = _fastembed_model_bytes(cache_dir, model_id)
        downloaded = max(0, current - initial_bytes)
        pct = min(98, int(downloaded * 100 / _EMBEDDER_EXPECTED_BYTES))
        if pct != last_pct:
            last_pct = pct
            yield {
                "type": "progress",
                "percent": pct,
                "speed": "—",
                "eta": "—",
                "bytes_done": downloaded,
                "bytes_total": _EMBEDDER_EXPECTED_BYTES,
            }

    if errors:
        raise errors[0]

    yield {
        "type": "progress",
        "percent": 100,
        "speed": "—",
        "eta": "—",
        "cached": False,
    }


def _is_hf_hub_url(url: str) -> bool:
    """True iff the URL host is on the HuggingFace Hub.

    Used to decide whether to attach the HF token: we only ever send it to HF
    hosts, never to an arbitrary catalog host. The endswith check is anchored on
    a leading dot so ``huggingface.co.evil.com`` and ``evilhuggingface.co`` do
    not match.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "huggingface.co" or host == "hf.co" or host.endswith(".huggingface.co")


def _hf_repo_id_from_url(url: str) -> "str | None":
    """Derive the HF repo_id (org/model) from a Hugging Face Hub file URL.

    GGUF models are referenced by a raw .gguf URL like
    ``https://huggingface.co/<org>/<model>/resolve/<rev>/<file>.gguf``, but the
    HF preflight (model_info / snapshot_download) expects a repo_id. Returns the
    ``<org>/<model>`` segment, or None when the URL is not on the HF Hub or the
    path is too short to carry a repo_id (caller should then skip the HF probe).
    """
    if not _is_hf_hub_url(url):
        return None
    try:
        path = urlparse(url).path.strip("/")
    except ValueError:
        return None
    parts = [p for p in path.split("/") if p]
    # Cut at the first path marker; the repo_id is everything before it.
    for marker in ("resolve", "blob", "tree", "raw"):
        if marker in parts:
            parts = parts[: parts.index(marker)]
            break
    if len(parts) < 2:
        return None
    return "/".join(parts[:2])


def _preflight_repo_id(model_id: str) -> "str | None":
    """Map a preflight model_id to the HF repo_id to probe, or None to skip (B257).

    mlx model_ids are already repo_ids (``org/model``) → returned as-is. gguf
    model_ids are raw HF file URLs → derive the repo_id. A gguf URL on a non-HF
    catalog host has no HF gated/size concept → return None so the caller skips
    the HF probe instead of passing a URL to model_info/snapshot_download (which
    expect a repo_id and would degrade to a spurious network_error/not_found).
    """
    if "://" in model_id:
        return _hf_repo_id_from_url(model_id)
    return model_id


async def _stream_gguf(model_id: str, request: Request) -> AsyncIterator[dict]:
    """Download a GGUF model via HTTP with progress reporting."""
    import httpx

    filename = _safe_model_basename(model_id)
    dest = _models_dir() / filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    # B255: a gated GGUF on the HF Hub needs an "Authorization: Bearer <HF_TOKEN>"
    # header. Attach it ONLY when the URL points at the HF Hub, so the token is
    # never handed to an arbitrary catalog host. httpx already strips the
    # Authorization header on cross-origin redirects (verified on 0.28.1), so the
    # HF→CDN hop that follows a /resolve/ URL does not leak it to the CDN.
    headers: dict[str, str] = {}
    if _is_hf_hub_url(model_id):
        token = await _ensure_hf_token_in_env()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:  # nosec B113 — GGUF downloads are unbounded by design; disconnect detection via request.is_disconnected()
        async with client.stream("GET", model_id, headers=headers) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                    if await request.is_disconnected():
                        return
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded * 100 / total)
                        if pct != last_pct:
                            last_pct = pct
                            yield {"type": "progress", "percent": pct, "speed": "—", "eta": "—"}


# ──────────────────────────────────────────────────────────────────────────────
# Gated-model detection + dry_run preflight
# ──────────────────────────────────────────────────────────────────────────────


# Timeout for the off-thread Keychain read in _ensure_hf_token_in_env (CRY-01).
# Module-level so tests can shrink it; mirrors the 5s write guard in set_hf_token.
_HF_KEYCHAIN_READ_TIMEOUT = 5.0


async def _ensure_hf_token_in_env() -> str | None:
    """Return the HF token for gated access, restoring it from the Keychain into
    ``os.environ`` if the live env lost it (B253).

    ``set_hf_token`` (step 3) stores the token to the Keychain best-effort, but
    the preflight + ``snapshot_download`` only read ``os.environ['HF_TOKEN']``
    (process-local). If the sidecar PROCESS restarts mid-download (force-quit +
    reopen, or a crash), the env is gone and ``apply_to_env`` cannot help — it is
    only invoked when ``OnboardingState.load()`` succeeds, which does NOT happen
    while the wizard is still mid-flow (the state file is written at finalize,
    step 5). The token then sits orphaned in the Keychain. We read it here and
    re-inject it so the env-based preflight + download pick it up. No-op (zero
    Keychain access) when the env already holds the token — the common case.
    """
    token = os.environ.get("HF_TOKEN") or None
    if token:
        return token
    # Read the Keychain OFF the event loop with a timeout: a headless macOS
    # Keychain ACL prompt can block for minutes when the bundled Python binary is
    # not on the item's ACL (precedent CRY-01 — the same guard B054 applied to
    # the WRITE path in set_hf_token). On timeout/error the wizard keeps going
    # without a token rather than hanging the whole sidecar.
    try:
        loop = asyncio.get_event_loop()
        token = await asyncio.wait_for(
            loop.run_in_executor(_dl_executor, _read_hf_token_from_keychain),
            timeout=_HF_KEYCHAIN_READ_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — timeout or keyring error: never fatal
        logger.warning("installer: Keychain read for HF_TOKEN skipped (%s)", type(exc).__name__)
        token = None
    if token:
        os.environ["HF_TOKEN"] = token
        logger.info("installer: HF_TOKEN restored from Keychain (mid-flow restart recovery, B253)")
    return token


def _check_model_access(repo_id: str, token: str | None = None) -> dict:
    """Inspect a Hugging Face repo to detect gated/private/missing status.

    Returns one of:
      {"status": "ok"}
      {"status": "gated", "url": "https://huggingface.co/<repo_id>"}
      {"status": "gated_no_access", "url": ...}
      {"status": "not_found"}
      {"status": "network_error", "reason": "..."}
    """
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.errors import (
            GatedRepoError,
            RepositoryNotFoundError,
        )
    except ImportError as exc:
        return {"status": "network_error", "reason": f"huggingface_hub missing: {exc}"}

    api = HfApi(token=token) if token else HfApi()
    try:
        info = api.model_info(repo_id, expand=["gated"])
    except GatedRepoError:
        return {
            "status": "gated_no_access",
            "url": f"https://huggingface.co/{repo_id}",
        }
    except RepositoryNotFoundError:
        return {"status": "not_found"}
    except Exception as exc:  # noqa: BLE001  network/timeout/etc.
        return {"status": "network_error", "reason": str(exc)}

    gated = getattr(info, "gated", None)
    if gated in ("auto", "manual"):
        return {
            "status": "gated" if token else "gated_no_access",
            "url": f"https://huggingface.co/{repo_id}",
        }
    return {"status": "ok"}


def _dry_run_plan(repo_id: str, token: str | None = None) -> dict:
    """Probe the snapshot_download plan without downloading any bytes.

    Returns: {"total_bytes": int, "cached_bytes": int, "files_count": int}
    or {"error": "..."} on failure.
    """
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import]
    except ImportError as exc:
        return {"error": f"huggingface_hub missing: {exc}"}
    try:
        plan = snapshot_download(repo_id=repo_id, dry_run=True, token=token)  # nosec B615 — dry_run=True: no download occurs, only metadata; token from Keychain
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    total = 0
    cached = 0
    count = 0
    for item in plan:
        size = int(getattr(item, "file_size", 0) or 0)
        total += size
        if getattr(item, "is_cached", False):
            cached += size
        count += 1
    return {
        "total_bytes": total,
        "cached_bytes": cached,
        "files_count": count,
    }


@router.get("/preflight", operation_id="installer_preflight")
async def preflight(engine: str, model_id: str) -> JSONResponse:
    """Probe a model BEFORE downloading: gated status + total bytes.

    Exposed so the wizard can show the user
    a meaningful summary ("Will download 4.5 GB in 12 files, 1.2 GB
    already cached") and surface gated-model errors before the user
    commits to a download.

    For engine="ollama" we skip the HF lookup entirely (Ollama models are
    pulled via the ollama daemon, no HF concept of gated/private applies).
    """
    if engine not in _VALID_ENGINES:
        return JSONResponse({"error": f"Unknown engine: {engine!r}"}, status_code=400)
    if engine == "ollama":
        return JSONResponse({
            "engine": "ollama",
            "access": {"status": "ok"},
            "plan": {"total_bytes": 0, "cached_bytes": 0, "files_count": 0},
        })

    # if the user has stored an HF token, the access check
    # and dry-run plan use it so gated repos the user has access to are
    # reported as "ok" instead of "gated_no_access". Falls back to the Keychain
    # so a token handed over before a mid-flow sidecar restart is not lost (B253).
    # gguf model_ids are raw .gguf URLs; HF probes need the repo_id (B257). A
    # gguf URL on a non-HF host has no HF gated/size concept → report ok/empty.
    repo_id = _preflight_repo_id(model_id)
    if repo_id is None:
        return JSONResponse({
            "engine": engine,
            "access": {"status": "ok"},
            "plan": {"total_bytes": 0, "cached_bytes": 0, "files_count": 0},
        })
    token = await _ensure_hf_token_in_env()
    # Run blocking HF calls in the executor so we don't block the event loop.
    loop = asyncio.get_event_loop()
    access = await loop.run_in_executor(_dl_executor, _check_model_access, repo_id, token)
    plan = await loop.run_in_executor(_dl_executor, _dry_run_plan, repo_id, token)
    return JSONResponse({
        "engine": engine,
        "access": access,
        "plan": plan,
    })


async def _preflight_hf_access(engine: str, model_id: str) -> "dict | None":
    """Pre-flight HuggingFace gated/not-found check for mlx/gguf engines.

    Returns an error event dict if access is denied or model not found, else None.
    Extracted from download_model.generate to reduce CCN.
    """
    if engine not in ("mlx", "gguf"):
        return None
    # gguf model_ids are raw .gguf URLs; HF probes need the repo_id (B257). A
    # gguf URL on a non-HF host has no HF gated concept → fall through to download.
    repo_id = _preflight_repo_id(model_id)
    if repo_id is None:
        return None
    # Falls back to the Keychain (re-injecting into the env) so a token handed
    # over before a mid-flow sidecar restart still authenticates the retry (B253).
    token = await _ensure_hf_token_in_env()
    loop = asyncio.get_event_loop()
    access = await loop.run_in_executor(_dl_executor, _check_model_access, repo_id, token)
    status = access.get("status")
    if status == "gated_no_access":
        return {
            "type": "error",
            "code": "GATED_NO_TOKEN",
            "message": (
                "This model requires accepting a Hugging Face "
                "license and a connected HF token. Open the URL, "
                "accept the terms, paste your token in the model "
                "download step and retry — or switch this model's "
                "engine to Ollama, which needs no token."
            ),
            "url": access.get("url"),
        }
    if status == "not_found":
        return {"type": "error", "code": "NOT_FOUND", "message": f"Model not found on Hugging Face: {model_id}"}
    return None  # network_error / ok → fall through to download


async def _sha256_check(engine: str, model_id: str) -> "dict | None":
    """Run SHA256 integrity check.

    Returns:
      - ``None`` when the weights were verified against a pinned digest.
      - a ``{"type": "warning", "code": "SHA256_NOT_PINNED", ...}`` event when
        the model has no pin in the catalog (INST-002: the GUI/SSE path must
        surface the same ⚠️ notice the CLI already prints, per the
        download_verify contract — the caller yields it but does NOT abort).
      - a ``{"type": "error", "code": "SHA256_FAIL", ...}`` event on a digest
        mismatch or an unexpected verification error (fail-closed, INST-003).
    """
    try:
        from installer.download_verify import verify_download_integrity  # type: ignore[import]
        loop = asyncio.get_event_loop()
        if engine == "ollama":
            # ADR B251: Ollama integrity is delegated to its content-addressed
            # pull; verify_download_integrity short-circuits to True (the target
            # path is unused for Ollama).
            matched = await loop.run_in_executor(
                None, verify_download_integrity, engine, model_id, Path("."),
            )
        else:
            target_path = Path(_resolve_model_path(engine, model_id))
            matched = await loop.run_in_executor(None, verify_download_integrity, engine, model_id, target_path)
        if not matched:
            logger.info("installer: SHA256 not pinned for %s/%s — install continues", engine, model_id)
            # INST-002: surface the missing-pin condition to the user instead of
            # only logging it. The CLI prints a yellow ⚠️ and the download_verify
            # contract requires the caller to make it visible. This is a warning,
            # not an error: the install continues (the caller does not abort).
            return {
                "type": "warning",
                "code": "SHA256_NOT_PINNED",
                "message": (
                    f"{model_id}: installed without weight verification "
                    "(no SHA256 pin in the catalog)."
                ),
            }
        return None
    except DownloadIntegrityError as exc:
        logger.error("installer: SHA256 mismatch for %s/%s: %s", engine, model_id, exc)
        return {"type": "error", "code": "SHA256_FAIL", "message": f"Integrity check failed: {exc}"}
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        logger.error("installer: SHA256 verify hard error for %s/%s: %s", engine, model_id, exc)
        return {"type": "error", "code": "SHA256_FAIL", "message": f"Integrity check error: {exc}"}
    except Exception as exc:  # noqa: BLE001
        # Fail-CLOSED. This is a security check: an unexpected error in the
        # verification path (a bug in the hashing chain, an unforeseen runtime
        # error) must NOT be silently treated as "skip → continue". Doing so
        # would disable integrity enforcement without anyone noticing. The
        # download library already returns None/False for legitimate
        # infrastructure conditions (digest not pinned, ollama unavailable,
        # older daemon) — those reach the `if not matched` branch above and
        # continue. Anything that reaches HERE is genuinely unexpected, so we
        # abort the install rather than ship an unverified model.
        logger.error("installer: SHA256 verify unexpected error for %s/%s: %s", engine, model_id, exc)
        return {"type": "error", "code": "SHA256_FAIL", "message": f"Integrity check error: {exc}"}


@router.get("/download", operation_id="installer_download_model")
async def download_model(engine: str, model_id: str, request: Request) -> StreamingResponse:
    """Stream model download progress as SSE events.

    Query params:
      engine   — one of: mlx, ollama, gguf
      model_id — e.g. "mlx-community/gemma-3-4b-it-4bit" or "gemma3:4b"
    """
    if engine not in _VALID_ENGINES:
        async def _err() -> AsyncIterator[str]:
            yield await _sse({"type": "error", "message": f"Unknown engine: {engine!r}"})
        return StreamingResponse(_err(), media_type="text/event-stream", headers=_SSE_HEADERS)

    # Reject pathological model_id values up front so the streamers below
    # never see a basename of "..", "." or "" that would escape models_dir.
    # Ollama identifiers ("gemma3:4b") are not file paths so the basename
    # rule does not apply.
    if engine in ("mlx", "gguf"):
        try:
            _safe_model_basename(model_id)
        except ValueError as exc:
            err_msg = str(exc)
            async def _err_basename() -> AsyncIterator[str]:
                yield await _sse({"type": "error", "code": "INVALID_MODEL_ID", "message": err_msg})
            return StreamingResponse(_err_basename(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def generate() -> AsyncIterator[str]:
        try:
            # Pre-flight gated/not-found check for HF-hosted engines (mlx/gguf).
            preflight_err = await _preflight_hf_access(engine, model_id)
            if preflight_err is not None:
                yield await _sse(preflight_err)
                return

            if engine == "mlx":
                async for ev in _stream_mlx(model_id, request):
                    yield await _sse(ev)
            elif engine == "ollama":
                async for ev in _stream_ollama(model_id, request):
                    yield await _sse(ev)
            elif engine == "embedder":
                # download the fastembed embedding model. The
                # wizard supplies model_id explicitly (or the default
                # constant via _EMBEDDER_MODEL_ID).
                effective_id = model_id or _EMBEDDER_MODEL_ID
                async for ev in _stream_embedder(effective_id, request):
                    yield await _sse(ev)
            else:
                async for ev in _stream_gguf(model_id, request):
                    yield await _sse(ev)

            # SHA256 integrity check post-download (mlx/ollama/gguf only, not embedder).
            if engine in ("mlx", "ollama", "gguf"):
                ev = await _sha256_check(engine, model_id)
                if ev is not None:
                    yield await _sse(ev)
                    # INST-002: only a hard integrity failure aborts the install.
                    # A SHA256_NOT_PINNED warning is surfaced but the download
                    # still completes (then falls through to the done event).
                    if ev.get("type") == "error":
                        return

            yield await _sse({"type": "done", "model_id": model_id})
        except Exception as exc:
            logger.exception("installer: download error for %s/%s", engine, model_id)
            yield await _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


class HfTokenBody(BaseModel):
    """Body for POST /installer/hf-token.

    Carries the Hugging Face access token the user pasted in the model-
    selection step so a GATED model can be downloaded in the SAME onboarding
    run. The token travels in a POST body (never a query param), so — unlike
    the GET /installer/download — it stays out of the uvicorn access log.
    Length capped like FinalizeBody (HF tokens are ~40 chars; the cap guards
    against an accidental paste of a huge blob).

    Caveat (B054 follow-up E): a paste OVER ``max_length`` raises a Pydantic
    validation error whose payload echoes the offending value, which the
    shared validation handler logs + returns in the 422 body. Real HF tokens
    are far under the cap, so this needs a deliberate oversized paste; the
    global redaction fix is tracked as a follow-up.
    """

    token: str = Field(..., min_length=1, max_length=200)


@router.post("/hf-token", operation_id="installer_set_hf_token")
async def set_hf_token(body: HfTokenBody) -> JSONResponse:
    """Load the HF token into the live sidecar env so a gated-model download
    in this same onboarding run can authenticate.

    Why this exists (B054): the token input previously lived only in the
    Advanced zone (which skips the catalog download), and the only path that
    persisted the token — POST /installer/finalize (step 5) — runs AFTER the
    download (step 3). So a first-run user could never download a gated MLX
    model. This endpoint lets step 3 hand the token over BEFORE the download:
    it sets ``os.environ['HF_TOKEN']`` (read by ``_preflight_hf_access`` and
    ``snapshot_download``) and best-effort persists it to the Keychain so a
    restart between step 3 and step 5 does not lose it. The token value is
    never logged.
    """
    token = body.token.strip()
    if not token:
        return JSONResponse(status_code=400, content={"detail": "empty token"})
    # The env var is what the gated preflight + snapshot_download read, and it is
    # set synchronously — that is the part the download needs right now.
    os.environ["HF_TOKEN"] = token
    # Keychain persistence is best-effort AND must never block the event loop nor
    # hang the wizard: a headless keyring access can trigger a blocking macOS
    # authorization dialog the sidecar cannot answer (precedent CRY-01). Run it
    # off-thread with a short timeout; on timeout/failure the token still lives
    # in the env for this run's download, and finalize (step 5) persists it later.
    persisted = False
    try:
        loop = asyncio.get_event_loop()
        persisted = await asyncio.wait_for(
            loop.run_in_executor(_dl_executor, _store_hf_token_in_keychain, token),
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001 — timeout or keyring error: never fatal
        logger.warning("installer/hf-token: Keychain persist skipped (%s)", type(exc).__name__)
    logger.info("installer/hf-token: HF_TOKEN loaded into env (persisted=%s)", persisted)
    return JSONResponse({"ok": True, "persisted": persisted})


@router.post("/ollama", operation_id="installer_ollama_install")
async def install_ollama_endpoint(request: Request) -> StreamingResponse:
    """Install Ollama if not present, streaming status as SSE.

    Replaces the placeholder "already_installed: False"
    per una crida real a ensure_ollama_installed(headless=True). Mateixes
    correccions C1-C5 de l'auditoria agèntica que _stream_ollama (cancel detection,
    lock concurrent, error UX-friendly per platform, logger.exception).
    """

    async def generate() -> AsyncIterator[str]:
        binary = _find_ollama_bin()
        if binary:
            yield await _sse({"type": "done", "already_installed": True})
            return
        # Check disconnect before starting.
        if await request.is_disconnected():
            return
        yield await _sse({"type": "progress", "stage": "Instal.lant Ollama...", "percent": 0})
        # Non-blocking lock to prevent two concurrent installations.
        if not _ollama_install_lock.acquire(blocking=False):
            yield await _sse({"type": "error", "message": "Ja s'esta instal.lant Ollama en un altre proces"})
            return
        try:
            # MC-031: share the install→locate machine with
            # _install_ollama_if_needed so the bundle fallback (CLI installed
            # but not yet on PATH) can never diverge between the two paths.
            binary = await _install_ollama_and_locate()
        except RuntimeError as exc:
            yield await _sse({"type": "error", "message": str(exc)})
            return
        finally:
            _ollama_install_lock.release()
        yield await _sse({"type": "done", "already_installed": False, "binary": binary})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


class FinalizeBody(BaseModel):
    """Body for the POST /installer/finalize endpoint.

    Validated server-side so the wizard cannot smuggle in arbitrary engines
    or oversized model identifiers (defense in depth — same allowlist as
    `_VALID_ENGINES` for /installer/download).

    optional ``hf_token`` field. When provided (non-empty),
    OnboardingState.save() stores it to the macOS Keychain — never to disk.
    Length capped at 200 chars (HF tokens are ~40 chars; the cap protects
    against accidental paste of huge blobs).
    """

    # "local" = user picked a local models folder; model_id carries the
    # absolute folder path (no fixed model — the chat UI selector chooses).
    engine: str = Field(..., pattern="^(mlx|ollama|gguf|local)$")
    # 512 chars: model ids are short, but a "local" folder path can be long.
    model_id: str = Field(..., min_length=1, max_length=512)
    hf_token: str | None = Field(default=None, max_length=200)
    # 2026-05-22: BCP-47 language code chosen at the wizard welcome step.
    # Allowlist matches the UI locales (Català/Español/English). When None
    # the OnboardingState.save() helper preserves the previous lang (or
    # falls back to "en") so a wizard variant that omits the field still
    # works.
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")


def _safe_model_basename(model_id: str) -> str:
    """Return the basename of ``model_id`` after rejecting pathological forms.

    Any pipeline that materialises a downloaded model under ``_models_dir()``
    derives the on-disk name from ``model_id.split("/")[-1]``. Three forms
    of ``model_id`` cause that basename to escape the models directory or
    overwrite the directory itself:

    - ``".."``: ``models_dir / ".."`` resolves to the parent of models_dir.
    - ``"."``: ``models_dir / "."`` is models_dir itself (overwrite root).
    - ``""`` (e.g. ``"<org>/"``): same as ``"."`` after the split.

    Raises ``ValueError`` for those cases so callers can answer 4xx. All
    other strings (including ``"<org>/<name>"``) are passed through as the
    basename.
    """
    basename = model_id.split("/")[-1]
    if basename in ("", ".", ".."):
        raise ValueError(f"invalid model_id: {model_id!r}")
    return basename


def _resolve_model_path(engine: str, model_id: str) -> str:
    """Resolve the on-disk location that matches what the engine plugin expects.

    - mlx / gguf: <models_dir>/<basename(model_id)> — wizard downloaded here.
    - ollama: the identifier IS the model handle (no path); return as-is.

    Raises ``ValueError`` when ``model_id`` is structured so that the resolved
    path would escape ``_models_dir()`` (e.g. ``".."``, ``"."``, ``""``, or
    a symlinked basename that resolves outside the models directory). The
    caller is responsible for turning that into an HTTP 4xx response.
    """
    if engine == "local":
        # model_id carries the user-picked models FOLDER (from the native
        # Tauri directory picker — trusted). It must be the container dir of
        # models (auto-discovery iterates its subdirs). Validate it exists;
        # no _safe_model_basename (that assumes a catalog model id).
        folder = Path(model_id).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"local models folder not found: {model_id!r}")
        return str(folder)
    if engine in ("mlx", "gguf"):
        basename = _safe_model_basename(model_id)
        models_root = _models_dir().resolve()
        candidate = (_models_dir() / basename).resolve()
        if not candidate.is_relative_to(models_root):
            raise ValueError(
                f"model_id resolves outside models_dir: {model_id!r}"
            )
        return str(candidate)
    return model_id  # ollama


@router.post("/finalize", operation_id="installer_finalize_post")
async def finalize_post(body: FinalizeBody) -> JSONResponse:
    """Persist onboarding state and return the local API key and server status.

    the wizard calls this after a successful download. The model_path
    is derived from `model_id` (same logic as the download streamers). The
    state is written atomically to `$NEXE_DATA_DIR/onboarding.json`; the next
    sidecar restart will pick it up and configure the right engine.
    """
    # Symmetric guard with GET /finalize (INST-001): once onboarding has
    # completed, this unauthenticated, repeatable endpoint must not keep
    # re-serving NEXE_PRIMARY_API_KEY to any local process. A clean re-install
    # wipes the data dir, which resets is_completed().
    if OnboardingState.is_completed():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    try:
        model_path = _resolve_model_path(body.engine, body.model_id)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    # if the wizard supplied an HF token, pass it to the
    # Keychain-aware save() — the token never lands on disk, only a
    # has_token=True marker in onboarding.json.
    # For "local", model_id is the folder path; persist a clear sentinel
    # instead (the chat UI selector chooses the real model). model_path keeps
    # the resolved folder so apply_to_env can set NEXE_STORAGE_PATH.
    saved_model_id = "local" if body.engine == "local" else body.model_id
    OnboardingState.save(
        engine=body.engine,
        model_id=saved_model_id,
        model_path=model_path,
        hf_token=body.hf_token,
        lang=body.lang,
    )
    # Clear runtime_state overrides for model env vars
    # for the model env vars so the freshly-saved OnboardingState is what
    # the next sidecar restart sees. Without this, a stale UI override from
    # an earlier session (set by routes_chat._switch_*_model) would shadow
    # the env var that apply_to_env() injects at startup.
    try:
        from core import runtime_state
        runtime_state.set_override("NEXE_MLX_MODEL", None)
        runtime_state.set_override("NEXE_LLAMA_CPP_MODEL", None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("installer/finalize: runtime_state cleanup failed: %s", exc)
    api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    return JSONResponse({"api_key": api_key, "status": "ready"})


def _finalize_marker_path() -> Path:
    """Return the path of the legacy GET /installer/finalize idempotency marker.

    Lives next to onboarding.json so it shares the same lifecycle (reset by
    blowing away the data dir, which is how a clean re-install is performed).
    """
    return OnboardingState._state_file().parent / ".finalize_called"


@router.get("/finalize", operation_id="installer_finalize_get")
async def finalize_get() -> JSONResponse:
    """Legacy GET endpoint — returns api_key + status without persisting state.

    The Advanced wizard flow (`engine === "local"` in step5-apikey.js) calls
    this exactly once: there is no engine/model_id to POST, so the wizard
    just fetches the api_key. Once onboarding has completed (either via the
    POST persisting OnboardingState or via this GET having been called once
    already), subsequent GETs return 404 — leaving the endpoint open would
    let any local process read NEXE_PRIMARY_API_KEY without authentication.

    The "first caller wins" race between marker check and write is resolved
    via O_CREAT | O_EXCL: only one concurrent invocation can create the
    marker; the rest receive FileExistsError and return 404. This closes
    the TOCTOU window that a simple ``exists() + touch()`` would leave open.
    """
    if OnboardingState.is_completed():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    marker = _finalize_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        # Another (or this same) caller already consumed the legacy endpoint.
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    except OSError as exc:
        # Could not create the marker (e.g. read-only filesystem). Log and
        # still serve the key — the next request will hit the same OSError
        # and re-serve, which is no worse than the pre-fix behaviour and
        # avoids breaking the wizard if the data dir is misconfigured.
        logger.warning(
            "installer/finalize: failed to write idempotency marker: %s", exc
        )

    api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    return JSONResponse({"api_key": api_key, "status": "ready"})


@router.get("/check-metal", operation_id="installer_check_metal")
async def check_metal() -> JSONResponse:
    """Check if Apple Metal/MLX is available on this system.

    El wizard usa aquest endpoint per saber si pot oferir MLX com a backend.
    A Macs Intel (sense Metal) o Linux/Windows, mlx no s'ha d'oferir.
    Validat amb agentic audit 2026-05-20 (thread executor suficient,
    no cal subprocess). Memory pressure ~200-500 MB del MLX framework
    s'acceptarà perquè el sidecar ja el carregara per chat.
    """
    def _check() -> bool:
        try:
            import mlx.core as mx  # type: ignore[import]
            return bool(mx.metal.is_available())
        except Exception:
            return False
    loop = asyncio.get_event_loop()
    metal = await loop.run_in_executor(None, _check)
    return JSONResponse({
        "metal_available": metal,
        "platform": platform.system().lower(),
    })


@router.get("/state", operation_id="installer_state")
async def installer_state() -> JSONResponse:
    """Return the current onboarding state.

    El frontend Tauri usa aquest endpoint per saber si l'onboarding s'ha
    completat sense necessitat de llegir el fitxer JSON del disc. Util quan
    el sidecar es reinicia i el frontend vol decidir si mostrar wizard o UI.
    NO retorna api_key (sensible). Validat amb agentic audit 2026-05-20.
    """
    state = OnboardingState.load()
    if state is None:
        return JSONResponse({"completed": False})
    return JSONResponse({
        "completed": True,
        "engine": state.engine,
        "model_id": state.model_id,
        "has_token": getattr(state, "has_token", False),
    })
