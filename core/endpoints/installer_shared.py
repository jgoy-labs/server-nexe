"""Plumbing shared by every installer path.

Split out of ``core.endpoints.installer`` (finding #969: 880 NLOC against a
hard limit of 500). This is the bottom of the family — it imports from no
other ``installer_*`` module, so the per-engine modules and the endpoints can
all depend on it without a cycle.

Two of these globals carry a guarantee rather than a value, and they live here
precisely so there is ONE of each:

- ``_dl_executor`` is ``max_workers=1``: it serialises the blocking download
  work. Two executors would be two queues, and the serialisation would be gone
  with nothing failing.
- ``_ollama_install_lock`` stops two ``zip_extract`` runs from landing on
  /Applications/Ollama.app at the same time and corrupting it. Two locks is no
  lock.

``tests/core/endpoints/test_f969_installer_split_golden_master.py`` asserts
both invariants over the whole ``installer*`` family.
"""

from __future__ import annotations

import json
import os
import threading as _threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Request

from core.onboarding_state import OnboardingState

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

def _client_is_loopback(request: Request) -> bool:
    """True when the request originates from the local machine.

    WS1-01: /installer/finalize returns NEXE_PRIMARY_API_KEY without auth
    (the wizard runs before the key exists client-side). Even when the
    operator deliberately binds non-loopback (NEXE_ALLOW_PUBLIC_BIND), the
    primary key must never be served across the network.
    """
    import ipaddress
    client = request.client
    if client is None or not client.host:
        return False
    host = client.host.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def _finalize_marker_path() -> Path:
    """Return the path of the legacy GET /installer/finalize idempotency marker.

    Lives next to onboarding.json so it shares the same lifecycle (reset by
    blowing away the data dir, which is how a clean re-install is performed).
    """
    return OnboardingState._state_file().parent / ".finalize_called"
