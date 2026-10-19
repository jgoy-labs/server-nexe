"""How many billions of parameters the model that answers has (pla-comportament-segons-mida-model, A).

The model carries its own size; each engine keeps it in a different place:

- Ollama says it (`/api/show` → `details.parameter_size`, «9.0B»).
- MLX writes `total_parameters` in `model.safetensors.index.json` — some do — and
  always the bytes of the weights, which with the bits of `config.json` give an
  estimate (good enough to tell a 4B from a 9B from a 27B, not to print).
- A name that carries it («Qwen3.5-9B-MLX-4bit», «35b-a3b») is the last resort.
- A cloud API says nothing, and is always read as a big model.

Nothing here raises: a size that cannot be read is `unknown`, and the caller
decides what that means (`model_tier`).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NAME_B = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)
_NAME_ACTIVE = re.compile(r"(?<![a-z0-9])a(\d+(?:\.\d+)?)b(?![a-z0-9])", re.IGNORECASE)
_OLLAMA_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmbt])\s*$", re.IGNORECASE)
_UNIT_TO_B = {"k": 1e-6, "m": 1e-3, "b": 1.0, "t": 1e3}

#: Ollama answers in well under a second; a slow one must not hold up the turn.
_OLLAMA_TIMEOUT_S = 2.0
#: A size that could not be read is tried again after this long.
_RETRY_AFTER_S = 60.0


@dataclass(frozen=True)
class ModelSize:
    #: Billions of parameters, or None when nothing says.
    params_b: Optional[float]
    #: Billions ACTIVE per token, for a mixture-of-experts name («35b-a3b»); else None.
    active_b: Optional[float]
    #: Where it came from, most to least reliable: ollama, index, estimated, name; or api / unknown.
    source: str

    def effective_b(self) -> Optional[float]:
        """What the model weighs when it thinks: the active parameters if known."""
        return self.active_b if self.active_b else self.params_b


UNKNOWN = ModelSize(None, None, "unknown")
API = ModelSize(None, None, "api")


def from_name(name: str) -> ModelSize:
    """«Qwen3.5-9B-MLX-4bit» → 9; «qwen3.5:35b-a3b» → 35 total, 3 active."""
    text = str(name or "")
    active = _NAME_ACTIVE.search(text)
    # The active figure must not be read as the model's own size.
    total = _NAME_B.search(text[: active.start()] if active else text) or _NAME_B.search(text)
    if not total:
        return UNKNOWN
    return ModelSize(float(total.group(1)), float(active.group(1)) if active else None, "name")


def from_ollama_details(details: Any, name: str = "") -> ModelSize:
    """`details.parameter_size` of `/api/show` or `/api/tags` («9.0B», «751.63M»)."""
    raw = (details or {}).get("parameter_size") if isinstance(details, dict) else None
    match = _OLLAMA_SIZE.match(str(raw or ""))
    if not match:
        return from_name(name)
    params = round(float(match.group(1)) * _UNIT_TO_B[match.group(2).lower()], 2)
    return ModelSize(params, from_name(name).active_b, "ollama")


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _positive_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _bits_per_weight(folder: Path) -> float:
    """What one weight costs on disk: its bits plus its share of the group's scale and bias."""
    quant = _read_json(folder / "config.json").get("quantization") or {}
    bits = _positive_int(quant.get("bits")) if isinstance(quant, dict) else None
    if bits is None:
        return 16.0  # not quantised: bf16/fp16
    group = _positive_int(quant.get("group_size"))
    # Each group of weights also stores a scale and a bias (two fp16).
    return bits + (32.0 / group if group else 0.0)


def from_mlx_dir(path: Path, name: str = "") -> ModelSize:
    """A model folder of MLX: the index's own count, else weights ÷ bits, else the name."""
    meta = _read_json(path / "model.safetensors.index.json").get("metadata") or {}
    by_name = from_name(name or path.name)
    counted = _positive_int(meta.get("total_parameters"))
    if counted:
        return ModelSize(round(counted / 1e9, 2), by_name.active_b, "index")
    weights = _positive_int(meta.get("total_size"))
    if weights:
        return ModelSize(round(weights * 8 / _bits_per_weight(path) / 1e9, 1), by_name.active_b, "estimated")
    return by_name


def _mlx_dir(model: str) -> Optional[Path]:
    """The folder of an MLX model given as a path or as a name under storage/models."""
    if not model:
        return None
    direct = Path(model).expanduser()
    if direct.is_dir():
        return direct
    from core.paths.helpers import get_models_dir  # deferred: pulls the paths module

    candidate = get_models_dir() / model
    return candidate if candidate.is_dir() else None


async def _ollama_show(model: str) -> ModelSize:
    import httpx  # deferred: only Ollama turns pay for it

    from core.ollama_utils import resolve_ollama_url

    async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_S) as client:
        resp = await client.post(f"{resolve_ollama_url()}/api/show", json={"model": model})
        resp.raise_for_status()
        return from_ollama_details(resp.json().get("details"), model)


_cache: dict[tuple[str, str], tuple[ModelSize, float]] = {}


def forget_cache() -> None:
    _cache.clear()


async def model_size(engine: Optional[str], model: Optional[str]) -> ModelSize:
    """The size of `model` as served by `engine`. Never raises; cached per process."""
    kind = (engine or "").lower().replace(".", "").replace("_", "")
    name = str(model or "")
    if kind == "api":
        return API
    key = (kind, name)
    hit = _cache.get(key)
    if hit and (hit[0].source != "unknown" or time.monotonic() - hit[1] < _RETRY_AFTER_S):
        return hit[0]
    try:
        if kind == "ollama" and name:
            size = await _ollama_show(name)
        elif kind == "mlx" and (folder := _mlx_dir(name)) is not None:
            size = from_mlx_dir(folder, name)
        else:
            size = from_name(name)
    except Exception as exc:  # noqa: BLE001 — a size we cannot read is "unknown", never a failed turn
        logger.debug("model_size(%s, %s) fell back to the name: %s", engine, name, exc)
        size = from_name(name)
    _cache[key] = (size, time.monotonic())
    return size
