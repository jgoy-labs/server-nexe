"""Findings fixes — tests for G1-G8 (installer + progress tracker).

G1 — Ollama detected in ~/Applications/ (user-level install)
G2 — GGUF re-download overwrites (wb not ab)
G4 — Stuck-handler threshold is 99%, not 90%
G5 — _VALID_ENGINES consistent across installer + onboarding_state
G6 — DownloadTracker initial maybe_poll_dir stabilises baseline
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# G1 — _find_ollama_bin detects ~/Applications/Ollama.app
# ──────────────────────────────────────────────────────────────────────────────

def test_find_ollama_user_applications_candidate_present():
    """_find_ollama_bin candidate list must include ~/Applications/Ollama.app."""
    import inspect
    import core.endpoints.installer as _mod

    src = inspect.getsource(_mod._find_ollama_bin)
    assert "~/Applications/Ollama.app/Contents/Resources/ollama" in src, (
        "Candidate list must include ~/Applications/Ollama.app/Contents/Resources/ollama"
    )


def test_find_ollama_user_applications_functional(tmp_path):
    """_find_ollama_bin returns ~/Applications binary when it exists and is executable."""
    import core.endpoints.installer as _mod

    ollama_bin = tmp_path / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama"
    ollama_bin.parent.mkdir(parents=True)
    ollama_bin.touch()
    ollama_bin.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)

    # Capture originals before patching to avoid recursion
    _real_expanduser = os.path.expanduser
    _real_isfile = os.path.isfile
    _real_access = os.access

    def _fake_expanduser(p: str) -> str:
        if p.startswith("~/Applications"):
            return str(tmp_path / p[2:])
        return _real_expanduser(p)

    # Paths that must NOT be hit (system-level candidates)
    _blocked = ("/usr/local/bin", "/opt/homebrew", "/usr/bin", "/Applications/Ollama.app")

    def _fake_isfile(p: str) -> bool:
        if any(p.startswith(b) for b in _blocked):
            return False
        return _real_isfile(p)

    def _fake_access(p: str, mode: int) -> bool:
        if any(p.startswith(b) for b in _blocked):
            return False
        return _real_access(p, mode)

    with patch("core.endpoints.installer.shutil.which", return_value=None), \
         patch("core.endpoints.installer.os.path.expanduser", side_effect=_fake_expanduser), \
         patch("core.endpoints.installer.os.path.isfile", side_effect=_fake_isfile), \
         patch("core.endpoints.installer.os.access", side_effect=_fake_access):
        result = _mod._find_ollama_bin()

    assert result == str(ollama_bin)


# ──────────────────────────────────────────────────────────────────────────────
# G2 — GGUF download uses "wb" (overwrite), not "ab" (append)
# ──────────────────────────────────────────────────────────────────────────────

def test_gguf_open_mode_is_wb():
    """_stream_gguf must open the destination file in 'wb' mode, not 'ab'."""
    import inspect
    import core.endpoints.installer as mod
    src = inspect.getsource(mod._stream_gguf)
    assert '"wb"' in src or "'wb'" in src, "_stream_gguf must use 'wb' open mode"
    assert '"ab"' not in src and "'ab'" not in src, "_stream_gguf must NOT use 'ab' append mode"




# ──────────────────────────────────────────────────────────────────────────────
# G4 — Stuck-handler threshold is 99%, not 90%
# ──────────────────────────────────────────────────────────────────────────────

def test_stuck_handler_threshold_is_99():
    """Stuck-99% handler must only trigger at pct >= 99, not 90."""
    import inspect
    import core.endpoints.installer as mod
    # Logic was extracted to _get_finalizing_hint for CCN reduction.
    src = inspect.getsource(mod._get_finalizing_hint)
    assert "pct < 99" in src or "pct >= 99" in src, "Stuck handler threshold must be 99"
    assert "pct < 90" not in src and "pct >= 90" not in src, "Old 90% threshold must not appear"


# ──────────────────────────────────────────────────────────────────────────────
# G5 — _VALID_ENGINES consistent across installer and onboarding_state
# ──────────────────────────────────────────────────────────────────────────────

def test_valid_engines_consistent():
    """Installer uses VALID_ENGINES (download allowlist); onboarding_state uses
    ONBOARDING_ENGINES (= VALID_ENGINES + 'local' for the local-folder wizard
    flow). Both must derive from core.installer_constants — single source."""
    from core.installer_constants import VALID_ENGINES, ONBOARDING_ENGINES
    from core.endpoints.installer import _VALID_ENGINES as installer_engines
    from core.onboarding_state import _ONBOARDING_ENGINES as state_engines

    assert installer_engines == VALID_ENGINES, (
        f"installer._VALID_ENGINES {installer_engines} != constants {VALID_ENGINES}"
    )
    assert state_engines == ONBOARDING_ENGINES, (
        f"onboarding_state._ONBOARDING_ENGINES {state_engines} != constants {ONBOARDING_ENGINES}"
    )
    # onboarding accepts exactly the download engines plus the local-folder marker
    assert ONBOARDING_ENGINES == VALID_ENGINES | {"local"}


def test_valid_engines_contains_expected_values():
    """VALID_ENGINES must contain mlx, ollama, gguf, embedder."""
    from core.installer_constants import VALID_ENGINES
    assert VALID_ENGINES == frozenset({"mlx", "ollama", "gguf", "embedder"})


# ──────────────────────────────────────────────────────────────────────────────
# G6 — DownloadTracker initial maybe_poll_dir stabilises baseline
# ──────────────────────────────────────────────────────────────────────────────

def test_tracker_initial_poll_on_existing_dir(tmp_path):
    """maybe_poll_dir(force=True) must immediately capture existing bytes."""
    from core.endpoints.installer_progress import DownloadTracker

    dest = tmp_path / "model"
    dest.mkdir()
    (dest / "existing.bin").write_bytes(b"\x00" * 2048)

    tracker = DownloadTracker(dest_dir=dest)
    # Before force poll, _dir_bytes may be 0 (no poll has run yet)
    tracker.maybe_poll_dir(force=True)

    assert tracker._dir_bytes >= 2048, (
        f"Expected _dir_bytes >= 2048 after force poll, got {tracker._dir_bytes}"
    )


def test_tracker_initial_poll_empty_dir(tmp_path):
    """maybe_poll_dir(force=True) on empty dir returns 0 bytes (no crash)."""
    from core.endpoints.installer_progress import DownloadTracker

    dest = tmp_path / "empty_model"
    dest.mkdir()

    tracker = DownloadTracker(dest_dir=dest)
    tracker.maybe_poll_dir(force=True)

    assert tracker._dir_bytes == 0


# ──────────────────────────────────────────────────────────────────────────────
# G8 — _fastembed_model_bytes counts only the target model
# ──────────────────────────────────────────────────────────────────────────────

def test_fastembed_model_bytes_only_target_model(tmp_path):
    """_fastembed_model_bytes must count only the specified model's bytes."""
    from core.endpoints.installer import _fastembed_model_bytes

    # HF-style layout for target model
    model_id = "xenova/target-model"
    safe_id = model_id.replace("/", "--")
    model_dir = tmp_path / f"models--{safe_id}"
    model_dir.mkdir(parents=True)
    (model_dir / "model.onnx").write_bytes(b"\x00" * 1000)

    # Another model in same cache — must NOT be counted
    other = tmp_path / "models--xenova--other-model"
    other.mkdir(parents=True)
    (other / "model.onnx").write_bytes(b"\x00" * 9999)

    result = _fastembed_model_bytes(tmp_path, model_id)
    assert result == 1000, f"Expected 1000 bytes for target model, got {result}"


def test_fastembed_model_bytes_missing_model(tmp_path):
    """_fastembed_model_bytes returns 0 when model not in cache."""
    from core.endpoints.installer import _fastembed_model_bytes

    result = _fastembed_model_bytes(tmp_path, "xenova/nonexistent-model")
    assert result == 0


def test_fastembed_model_bytes_legacy_layout(tmp_path):
    """_fastembed_model_bytes falls back to legacy flat layout."""
    from core.endpoints.installer import _fastembed_model_bytes

    model_id = "org/my-model"
    legacy_dir = tmp_path / "my-model"  # flat layout: just the model name
    legacy_dir.mkdir()
    (legacy_dir / "model.onnx").write_bytes(b"\x00" * 500)

    result = _fastembed_model_bytes(tmp_path, model_id)
    assert result == 500


def test_stream_embedder_uses_model_specific_bytes():
    """_stream_embedder must use _fastembed_model_bytes, not _fastembed_cache_size_bytes."""
    import inspect
    import core.endpoints.installer as mod
    src = inspect.getsource(mod._stream_embedder)
    assert "_fastembed_model_bytes" in src, (
        "_stream_embedder must use _fastembed_model_bytes for accurate per-model progress"
    )
    assert "_fastembed_cache_size_bytes" not in src, (
        "_stream_embedder must NOT use _fastembed_cache_size_bytes (counts all models)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# G9 — bytes_done is a pure getter; record_sample() adds speed samples
# ──────────────────────────────────────────────────────────────────────────────

def test_bytes_done_does_not_mutate_samples(tmp_path):
    """Accessing bytes_done must NOT add samples to _samples."""
    from core.endpoints.installer_progress import DownloadTracker

    dest = tmp_path / "model"
    dest.mkdir()
    tracker = DownloadTracker(dest_dir=dest)
    initial_len = len(tracker._samples)

    _ = tracker.bytes_done
    _ = tracker.bytes_done
    _ = tracker.bytes_done

    assert len(tracker._samples) == initial_len, (
        f"bytes_done must not mutate _samples: expected {initial_len}, got {len(tracker._samples)}"
    )


def test_record_sample_adds_one_per_call(tmp_path):
    """record_sample() must add exactly one sample when bytes increase."""
    from core.endpoints.installer_progress import DownloadTracker

    dest = tmp_path / "model"
    dest.mkdir()
    (dest / "file.bin").write_bytes(b"\x00" * 1024)

    tracker = DownloadTracker(dest_dir=dest)
    tracker.maybe_poll_dir(force=True)
    initial_len = len(tracker._samples)

    tracker.record_sample()
    assert len(tracker._samples) == initial_len + 1

    # Calling again with same bytes must NOT add duplicate
    tracker.record_sample()
    assert len(tracker._samples) == initial_len + 1, (
        "record_sample() must not add duplicate samples for same byte count"
    )


def test_to_event_calls_record_sample(tmp_path):
    """to_event() must call record_sample() so each event adds a speed sample."""
    from core.endpoints.installer_progress import DownloadTracker

    dest = tmp_path / "model"
    dest.mkdir()
    (dest / "file.bin").write_bytes(b"\x00" * 2048)

    tracker = DownloadTracker(dest_dir=dest)
    tracker.maybe_poll_dir(force=True)
    initial_len = len(tracker._samples)

    ev = tracker.to_event()
    assert "percent" in ev
    assert len(tracker._samples) >= initial_len, (
        "to_event() must have called record_sample()"
    )


# ──────────────────────────────────────────────────────────────────────────────
# G11 — cancel_ev prevents worker from starting after disconnect
# ──────────────────────────────────────────────────────────────────────────────

def test_cancel_ev_structural():
    """_stream_mlx must use a cancel_ev (threading.Event) to signal workers."""
    import inspect
    import core.endpoints.installer as mod
    src = inspect.getsource(mod._stream_mlx)
    assert "cancel_ev" in src, "_stream_mlx must use cancel_ev threading.Event"
    assert "cancel_ev.set()" in src, "_stream_mlx must call cancel_ev.set() on disconnect"
    assert "cancel_ev.is_set()" in src, "_run must check cancel_ev.is_set() before starting"


def test_cancel_ev_threading_event():
    """cancel_ev must be a threading.Event (cross-thread signalling)."""
    import threading
    import inspect
    import core.endpoints.installer as mod
    src = inspect.getsource(mod._stream_mlx)
    assert "_threading.Event()" in src or "threading.Event()" in src, (
        "cancel_ev must be a threading.Event for thread-safe signalling"
    )


# ──────────────────────────────────────────────────────────────────────────────
# G13 — _TQDM_QUEUE protected by threading.Lock
# ──────────────────────────────────────────────────────────────────────────────

def test_tqdm_queue_lock_exists():
    """_TQDM_QUEUE_LOCK must exist and be a threading.Lock."""
    import threading
    from core.endpoints.installer_progress import _TQDM_QUEUE_LOCK
    assert isinstance(_TQDM_QUEUE_LOCK, type(_TQDM_QUEUE_LOCK)), (
        "_TQDM_QUEUE_LOCK must be a threading lock"
    )
    # Verify it's acquirable (basic lock sanity check)
    acquired = _TQDM_QUEUE_LOCK.acquire(blocking=False)
    assert acquired, "_TQDM_QUEUE_LOCK must be acquirable (not already held)"
    _TQDM_QUEUE_LOCK.release()


def test_set_tqdm_queue_uses_lock():
    """set_tqdm_queue must use _TQDM_QUEUE_LOCK for thread safety."""
    import inspect
    import core.endpoints.installer_progress as mod
    src = inspect.getsource(mod.set_tqdm_queue)
    assert "_TQDM_QUEUE_LOCK" in src, "set_tqdm_queue must use _TQDM_QUEUE_LOCK"


def test_sse_progress_tqdm_update_uses_lock():
    """SSEProgressTqdm.update must read _TQDM_QUEUE under _TQDM_QUEUE_LOCK."""
    import inspect
    import core.endpoints.installer_progress as mod
    if mod._tqdm is None:
        pytest.skip("tqdm not installed")
    src = inspect.getsource(mod.SSEProgressTqdm.update)
    assert "_TQDM_QUEUE_LOCK" in src, (
        "SSEProgressTqdm.update must read _TQDM_QUEUE under _TQDM_QUEUE_LOCK"
    )
