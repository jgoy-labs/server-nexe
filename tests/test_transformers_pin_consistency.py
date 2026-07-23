"""
────────────────────────────────────
Server Nexe
Location: tests/test_transformers_pin_consistency.py
Description: Anti-regression guard for the transformers pin (finding 820 /
             nexe-8gb-fix, 2026-07-13).

             transformers is a transitive dep of mlx-lm 0.31.3 (>=5.0.0) and
             mlx-vlm 0.4.4 (>=5.1.0) — both UNCAPPED, so pip/uv resolves the
             latest (5.13.0), which breaks mlx-lm 0.31.3 at import:
             transformers/models/auto/auto_factory.py:680 does key.__module__
             unconditionally, but mlx_lm/tokenizer_utils.py:505 registers the
             STRING 'NewlineTokenizer' -> AttributeError. The 8 GB M1 VLM
             crash (2026-07-13) was this. Fixed by pinning transformers==5.12.1
             (last tag before the breaking change) in requirements-macos.txt.

             These tests keep the pin present, below 5.13.0, and aligned with
             the CVE-audited version (declared == audited, the B069 pattern).

             Pure text parsing — no pip, no network, no install.
────────────────────────────────────
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_REQ_MACOS = _ROOT / "requirements-macos.txt"
_CHECK_CVES = _ROOT / "installer" / "check_cves_osv.py"


def _ver_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _pin_in_requirements(text: str, pkg: str) -> str | None:
    """Parse `<pkg>==X.Y.Z` from a pip requirements file (one spec per line)."""
    m = re.search(rf"^\s*{re.escape(pkg)}==([0-9][^\s#]*)", text, re.MULTILINE)
    return m.group(1) if m else None


def _pin_in_bundle_pins(text: str, pkg: str) -> str | None:
    """Parse `("<pkg>", "X.Y.Z")` from check_cves_osv.py BUNDLE_PINS tuples."""
    m = re.search(
        rf'\(\s*["\']{re.escape(pkg)}["\']\s*,\s*["\']([0-9][^"\']*)["\']\s*\)',
        text,
    )
    return m.group(1) if m else None


def test_transformers_pinned_in_requirements_macos() -> None:
    """transformers MUST be explicitly pinned (==) in requirements-macos.txt.

    Unpinned it resolves to 5.13.0, which breaks mlx-lm 0.31.3 at import
    (finding 820). Belongs in requirements-macos.txt (Apple-only), NOT the base
    requirements.txt (Linux/Windows are Ollama-only, no MLX, fastembed does not
    declare transformers).
    """
    ver = _pin_in_requirements(_REQ_MACOS.read_text(encoding="utf-8"), "transformers")
    assert ver is not None, (
        "transformers must be pinned (==) in requirements-macos.txt — unpinned "
        "it resolves to 5.13.0 and breaks mlx-lm 0.31.3 at import (finding 820)."
    )


def test_transformers_pin_below_5_13() -> None:
    """The pin must stay < 5.13.0.

    5.13.x hardened _LazyAutoMapping.register (key.__module__ unconditional),
    which mlx-lm 0.31.3's string-based AutoTokenizer.register cannot survive.
    """
    ver = _pin_in_requirements(_REQ_MACOS.read_text(encoding="utf-8"), "transformers")
    assert ver is not None and _ver_tuple(ver) < (5, 13, 0), (
        f"transformers pinned at {ver!r} — must be < 5.13.0. 5.13.x makes "
        f"key.__module__ unconditional, breaking mlx-lm 0.31.3's string register."
    )


def test_transformers_declared_matches_audited() -> None:
    """Declared pin (requirements-macos.txt) must equal CVE-audited (BUNDLE_PINS).

    B069 pattern extended to transformers: declared == audited so the OSV audit
    never vets a version the product does not actually run.
    """
    declared = _pin_in_requirements(_REQ_MACOS.read_text(encoding="utf-8"), "transformers")
    audited = _pin_in_bundle_pins(_CHECK_CVES.read_text(encoding="utf-8"), "transformers")
    assert declared is not None and audited is not None and declared == audited, (
        f"transformers declared ({declared}) must match CVE-audited ({audited}) "
        f"in check_cves_osv.py BUNDLE_PINS — else the audit vets a phantom "
        f"version (B069)."
    )
