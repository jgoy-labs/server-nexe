"""The embedder install path of the wizard: the fastembed ONNX model.

Split out of ``core.endpoints.installer`` (finding #969). The embedder is the
auxiliary download — it always comes alongside the primary engine and never
becomes the persisted ``engine`` of the onboarding state (see
``core.installer_constants``).

The download is blocking, so it runs on the shared single-worker executor of
``installer_shared``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import Request

from core.endpoints import installer_shared

logger = logging.getLogger(__name__)

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

    loop.run_in_executor(installer_shared._dl_executor, _run)

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
