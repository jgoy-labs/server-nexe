#!/usr/bin/env python3
"""
bootstrap_catalog_pins.py — populate provider-published pins (ADR B046b).

For every catalog artefact that lacks a self-computed tier-1 pin in
``MODEL_WEIGHT_SHA256``, fetch the checksum the provider already publishes —
metadata only, NO model bytes are downloaded:

  * MLX (HF snapshot)  → per-LFS-file sha256 from the HF Hub API.
  * Ollama             → skipped (content-addressed pull; not pinned, ADR B251).
  * GGUF               → skipped (those carry self-computed file hashes already).

Results are merged into ``installer/provider_pins.json`` (existing entries are
preserved). Run from the repo root:

    venv/bin/python -m installer.bootstrap_catalog_pins         # populate
    venv/bin/python -m installer.bootstrap_catalog_pins --dry-run

A model whose provider exposes no usable checksum is left unpinned (it falls to
the explicit-consent path at install time, never a silent fail-open).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from installer.installer_catalog_data import (
    get_expected_sha256,
    iter_catalog_model_ids,
)
from installer.provider_hashes import fetch_hf_lfs_hashes

logger = logging.getLogger("bootstrap_catalog_pins")

_PINS_PATH = Path(__file__).with_name("provider_pins.json")


def _load() -> dict:
    try:
        return json.loads(_PINS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "mlx_file_hashes": {}}


def bootstrap(*, dry_run: bool = False) -> dict:
    """Fetch and merge provider pins for every unpinned catalog artefact.

    Returns a summary dict ``{pinned: [...], skipped: [...]}``.
    """
    data = _load()
    data.setdefault("mlx_file_hashes", {})

    pinned: list[str] = []
    skipped: list[str] = []

    # Deduplicate (engine, model_id) — the embeddings model appears twice.
    seen: set[tuple[str, str]] = set()
    for engine, model_id in iter_catalog_model_ids():
        if (engine, model_id) in seen:
            continue
        seen.add((engine, model_id))

        # Tier-1 self-computed pin already present → leave it (it is stronger).
        if get_expected_sha256(engine, model_id) is not None:
            continue

        if engine == "mlx":
            files = fetch_hf_lfs_hashes(model_id)
            if files:
                data["mlx_file_hashes"][model_id] = files
                pinned.append(f"mlx:{model_id} ({len(files)} files)")
            else:
                skipped.append(f"mlx:{model_id}")
        elif engine == "ollama":
            # ADR B251: Ollama is content-addressed by its own pull — not pinned.
            skipped.append(f"ollama:{model_id} (content-addressed, not pinned)")
        else:  # gguf — self-computed only, nothing to fetch via metadata
            skipped.append(f"{engine}:{model_id} (self-computed only)")

    if not dry_run:
        _PINS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {"pinned": pinned, "skipped": skipped, "dry_run": dry_run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report but do not write provider_pins.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    summary = bootstrap(dry_run=args.dry_run)
    print(f"\n{'(dry-run) ' if args.dry_run else ''}Pinned {len(summary['pinned'])}:")
    for line in summary["pinned"]:
        print(f"  ✓ {line}")
    if summary["skipped"]:
        print(f"\nSkipped {len(summary['skipped'])}:")
        for line in summary["skipped"]:
            print(f"  – {line}")
    if not args.dry_run:
        print(f"\nWrote {_PINS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
