"""Tolerant read of a model's JSON, shared by the text path and the VLM.

Extracted from `chat.py` in #966 (slice A) with no body change: it was the only
symbol both sides needed, and leaving it in `chat.py` would have forced the VLM
module to import it from there, closing an import cycle.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON from path. Returns None if missing or unparseable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # nosec B110: optional VLM inspection — fail-closed (return None)
        return None
