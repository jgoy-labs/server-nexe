"""Lectura tolerant del JSON d'un model, compartida pel camí de text i pel VLM.

Extret de `chat.py` a #966 (Tros A) sense cap canvi de cos: era l'únic símbol que
necessitaven les dues bandes, i deixar-lo a `chat.py` hauria obligat el mòdul VLM a
importar-lo d'allà, tancant un cicle d'imports.
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
