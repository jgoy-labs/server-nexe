"""Anti-regression for the MLX pre-load RAM guard (findings 822/841 + Fase D).

History: a flat ``avail_gb < 1.5`` let a ~2.9 GB model OOM an 8 GB machine
(822). The derived threshold (×1.2+0.6) then over-corrected: field measurement
(M1 8 GB, 2026-07-23) showed it demanded 3.99 GB available while the load ran
fine at 1.91 — macOS compresses/swaps pages ``available`` ignores. Since then:

- default mode is **warn** (log the whole picture, load anyway);
- the estimate is the field-verified formula weights + KV window + runtime,
  via the SAME helpers as the B004 budget (never a local copy);
- the only refusal the default mode keeps is the physically-impossible case
  (weights + minimum KV window > TOTAL RAM);
- ``strict`` still exists via NEXE_MLX_RAM_GUARD for operators.
"""

from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.chat import (
    MLXChatNode,
    _estimate_required_ram,
)
from plugins.mlx_module.core.config import _RUNTIME_GB

_GB = 1024 ** 3
# No config.json in these fixtures → kv/token falls back to 256 KB;
# with max_kv_size=4096 that is exactly 1.0 GB of KV window.
_KV_4096_FALLBACK_GB = 4096 * 256 * 1024 / _GB  # == 1.0


def _write_sparse(path, size_bytes):
    """Create a sparse file of `size_bytes` without using real disk."""
    with open(path, "wb") as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(b"\0")


class TestEstimate:
    """The estimate is weights + KV(max_kv_size) + runtime — measurable parts."""

    def test_single_safetensors(self, tmp_path):
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        est = _estimate_required_ram(str(tmp_path), max_kv_size=4096)
        assert est["weights"] == pytest.approx(3.0, abs=0.05)
        assert est["required"] == pytest.approx(
            3.0 + _KV_4096_FALLBACK_GB + _RUNTIME_GB, abs=0.05
        )

    def test_sums_shards(self, tmp_path):
        _write_sparse(tmp_path / "model-00001-of-00002.safetensors", 1 * _GB)
        _write_sparse(tmp_path / "model-00002-of-00002.safetensors", 1 * _GB)
        est = _estimate_required_ram(str(tmp_path), max_kv_size=4096)
        assert est["weights"] == pytest.approx(2.0, abs=0.05)

    def test_kv_scales_with_window(self, tmp_path):
        """Mutation control of the formula: doubling the window adds exactly
        one more KV block — a regression to ×1.2+0.6 (which ignores
        max_kv_size) fails this assert."""
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        small = _estimate_required_ram(str(tmp_path), max_kv_size=4096)
        big = _estimate_required_ram(str(tmp_path), max_kv_size=8192)
        assert big["required"] - small["required"] == pytest.approx(
            _KV_4096_FALLBACK_GB, abs=0.01
        )

    @pytest.mark.parametrize("model_path", ["", "/does/not/exist/anywhere"])
    def test_unmeasurable_weights_are_none_with_35_fallback(self, model_path):
        est = _estimate_required_ram(model_path, max_kv_size=4096)
        assert est["weights"] is None  # a guess, must never hard-refuse
        assert est["required"] == pytest.approx(
            3.5 + _KV_4096_FALLBACK_GB + _RUNTIME_GB, abs=0.05
        )

    def test_no_safetensors_is_unmeasurable(self, tmp_path):
        (tmp_path / "config.json").write_text("{}")
        assert _estimate_required_ram(str(tmp_path), 4096)["weights"] is None

    def test_kv_min_is_capped_by_the_window(self, tmp_path):
        _write_sparse(tmp_path / "model.safetensors", 1 * _GB)
        est = _estimate_required_ram(str(tmp_path), max_kv_size=2048)
        assert est["kv_min"] == pytest.approx(est["kv"], abs=0.01)


def _make_config(model_path):
    config = MagicMock()
    config.model_path = model_path
    config.max_kv_size = 4096
    return config


@pytest.fixture(autouse=True)
def _deterministic_guard_env(monkeypatch):
    """Pin the guard's two environment inputs.

    NEXE_LANG must be pinned or the refusal message comes out in the ambient
    locale and a test that greps for the English text passes even when the
    guard *did* refuse — a false green. NEXE_MLX_RAM_GUARD is cleared so a stray
    value in the shell cannot silently change the mode under test.
    """
    monkeypatch.setenv("NEXE_LANG", "en")
    monkeypatch.delenv("NEXE_MLX_RAM_GUARD", raising=False)


def _fake_vm(avail_gb, total_gb=8):
    """A psutil vmem stand-in with every macOS field the diagnostic reads."""
    vm = MagicMock()
    vm.available = int(avail_gb * _GB)
    vm.total = int(total_gb * _GB)
    vm.free = int(0.5 * _GB)
    vm.active = int(3.0 * _GB)
    vm.inactive = int(1.5 * _GB)
    vm.wired = int(2.0 * _GB)
    return vm


def _invoke_guard(tmp_path, avail_gb, total_gb=8):
    """Drive ``_get_model()`` and return whatever it raised (or None).

    Past the guard the real weight load is expected to blow up (the fixture is a
    sparse file, not a model); that failure is not what these tests assert on —
    they only care whether the *guard* refused, identified by its message.
    """
    MLXChatNode._model = None
    node = MLXChatNode(config=_make_config(str(tmp_path)))
    try:
        with patch("psutil.virtual_memory", return_value=_fake_vm(avail_gb, total_gb)):
            node._get_model()
    except BaseException as exc:  # noqa: BLE001 — post-guard failure is expected
        return exc
    finally:
        MLXChatNode._model = None
    return None


_OOM_FRAGMENT = "Not enough memory to load the model with MLX"      # strict msg
_HARD_FRAGMENT = "Not enough memory: this model cannot fit"          # hard msg


class TestModes:
    def test_default_mode_is_warn(self, tmp_path, caplog):
        """No env var set: below-threshold LOADS with a warning (2026-07-23).

        Mutation control: reverting the default to strict makes this raise
        the OOM refusal (see test_strict_still_refuses for the strict pin).
        """
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        with caplog.at_level("WARNING"):
            exc = _invoke_guard(tmp_path, avail_gb=2.0)
        assert _OOM_FRAGMENT not in str(exc), f"default mode refused: {exc!r}"
        assert any("loading anyway" in r.getMessage() for r in caplog.records)

    def test_unknown_mode_falls_back_to_warn(self, tmp_path, monkeypatch):
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "yolo")
        exc = _invoke_guard(tmp_path, avail_gb=2.0)
        assert _OOM_FRAGMENT not in str(exc), f"unknown mode refused: {exc!r}"

    def test_strict_still_refuses_by_available(self, tmp_path, monkeypatch):
        """Mutation control of the mode plumbing: if someone removes the
        strict branch, this fails."""
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "strict")
        exc = _invoke_guard(tmp_path, avail_gb=2.0)
        assert isinstance(exc, RuntimeError) and _OOM_FRAGMENT in str(exc)

    def test_warn_mode_does_not_refuse(self, tmp_path, monkeypatch, caplog):
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "warn")
        with caplog.at_level("WARNING"):
            exc = _invoke_guard(tmp_path, avail_gb=2.0)
        assert _OOM_FRAGMENT not in str(exc), f"guard refused in warn mode: {exc!r}"
        assert any("loading anyway" in r.getMessage() for r in caplog.records)

    def test_off_mode_skips_the_check(self, tmp_path, monkeypatch, caplog):
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "off")
        with caplog.at_level("INFO"):
            exc = _invoke_guard(tmp_path, avail_gb=2.0)
        assert _OOM_FRAGMENT not in str(exc), f"guard refused in off mode: {exc!r}"
        assert not any("loading anyway" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("value", ["0", "false", "no", "disabled", "FALSE"])
    def test_disable_synonyms_are_honoured(self, tmp_path, monkeypatch, value):
        """What an operator actually types to turn a guard off must turn it
        off — a silent fallback would make a field measurement look like the
        guard was calibrated when the operator believed it was disabled."""
        _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", value)
        exc = _invoke_guard(tmp_path, avail_gb=2.0)
        assert _OOM_FRAGMENT not in str(exc)
        assert _HARD_FRAGMENT not in str(exc)


class TestHardRefusal:
    """weights + minimum KV window > TOTAL RAM → refuse even in warn."""

    def test_impossible_refuses_even_in_warn(self, tmp_path, monkeypatch):
        """10 GB of weights on an 8 GB machine: thrash/jetsam guaranteed.

        Mutation control: removing the _impossible block loads instead."""
        _write_sparse(tmp_path / "model.safetensors", 10 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "warn")
        exc = _invoke_guard(tmp_path, avail_gb=2.0, total_gb=8)
        assert isinstance(exc, RuntimeError) and _HARD_FRAGMENT in str(exc)

    def test_impossible_refuses_in_default_mode(self, tmp_path):
        _write_sparse(tmp_path / "model.safetensors", 10 * _GB)
        exc = _invoke_guard(tmp_path, avail_gb=2.0, total_gb=8)
        assert isinstance(exc, RuntimeError) and _HARD_FRAGMENT in str(exc)

    def test_off_skips_even_the_hard_refusal(self, tmp_path, monkeypatch):
        """The escape hatch stays absolute — field measurements need it."""
        _write_sparse(tmp_path / "model.safetensors", 10 * _GB)
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "off")
        exc = _invoke_guard(tmp_path, avail_gb=2.0, total_gb=8)
        assert _HARD_FRAGMENT not in str(exc)

    def test_skipped_when_weights_not_measurable(self, tmp_path):
        """The 3.5 GB fallback is a guess — a guess must never refuse."""
        (tmp_path / "config.json").write_text("{}")  # no safetensors
        exc = _invoke_guard(tmp_path, avail_gb=0.5, total_gb=2)
        assert _HARD_FRAGMENT not in str(exc)

    def test_message_contract_with_routes_chat(self, tmp_path, monkeypatch):
        """The hard message MUST be detectable by routes_chat's streaming
        handler or the UI shows a generic error instead of the Ollama advice.

        Cross-reference (keep in sync): routes_chat.py `_is_oom` substrings
        ("Memòria insuficient", "Memoria insuficiente", "Not enough memory",
        "Insufficient Memory", "OutOfMemory") and `_oom_notice`, which keeps
        the switch-engine advice only when "MLX" appears in the text.
        """
        _is_oom_keys = (
            "Insufficient Memory", "OutOfMemory",
            "Memòria insuficient", "Memoria insuficiente",
            "Not enough memory",
        )
        for lang in ("ca", "es", "en"):
            monkeypatch.setenv("NEXE_LANG", lang)
            _write_sparse(tmp_path / "model.safetensors", 10 * _GB)
            exc = _invoke_guard(tmp_path, avail_gb=2.0, total_gb=8)
            msg = str(exc)
            assert any(k in msg for k in _is_oom_keys), (
                f"[{lang}] hard message not detectable by _is_oom: {msg}"
            )
            assert "MLX" in msg, f"[{lang}] no 'MLX' → no Ollama advice: {msg}"
            assert "Ollama" in msg, f"[{lang}] advice missing: {msg}"


def test_diagnostic_logs_full_memory_picture(tmp_path, monkeypatch, caplog):
    """The log must carry total/free/inactive/active/wired, not just `available`.

    That is the whole point of the instrumentation: `psutil.available` on macOS
    is inactive+free and cannot by itself settle whether a refusal was fair.
    """
    _write_sparse(tmp_path / "model.safetensors", 3 * _GB)
    monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "off")
    with caplog.at_level("INFO"):
        _invoke_guard(tmp_path, avail_gb=2.0)
    line = next(
        (r.getMessage() for r in caplog.records if "MLX RAM guard [" in r.getMessage()),
        None,
    )
    assert line is not None, "the guard emitted no diagnostic line"
    for field in ("total", "free", "inactive", "active", "wired", "available",
                  "weights", "kv"):
        assert field in line, f"{field} missing from the diagnostic: {line}"
    assert "[off]" in line, f"mode not reported: {line}"
