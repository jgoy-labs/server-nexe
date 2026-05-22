#!/usr/bin/env python3
"""
check_cves_osv.py — Query OSV API for known CVEs in transitive deps.

Reasons for not using `pip-audit` directly:
  - pip-audit needs to *install* the package to resolve its environment.
  - torch wheels are Python-version + platform specific (e.g. torch==2.11.0
    only available for Python 3.12 macosx_14_0_arm64). On a host Python 3.9,
    pip-audit fails with "No matching distribution found".
  - We want a portable check that works against the *bundle pinned versions*
    (build-wheels-bundle.sh) regardless of host Python.

This script queries https://api.osv.dev/v1/query directly with
{package, version} pairs and applies the ignore-list at
installer/pip-audit-ignore.txt.

Exit codes:
  0  — no unexpected CVEs (all known are in ignore-list)
  1  — UNEXPECTED CVE found (not in ignore-list) — manual analysis required
  2  — usage / network error

Usage:
  python3 installer/check_cves_osv.py
  python3 installer/check_cves_osv.py --json    # machine-readable
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ── Bundle pinned versions (must match installer/build-wheels-bundle.sh) ──
# Source of truth: installer/build-wheels-bundle.sh ENGINES array.
# Update this list when bumping any of these pins.
BUNDLE_PINS: list[tuple[str, str]] = [
    ("torch", "2.11.0"),
    ("torchvision", "0.26.0"),
    ("mlx-lm", "0.31.2"),
    ("mlx-vlm", "0.4.4"),
    ("llama-cpp-python", "0.3.19"),
    # transformers is transitive; we audit the version mlx-lm 0.31.2 resolves.
    # Pinned manually after empirical check (pip show transformers).
    ("transformers", "5.8.1"),
]

IGNORE_LIST_PATH = Path(__file__).parent / "pip-audit-ignore.txt"


def _load_ignore_list(path: Path) -> set[str]:
    """Parse ignore-list, one CVE per line (after stripping comments)."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def _query_osv(name: str, version: str) -> list[dict]:
    """Query OSV API for known vulns affecting (name, version)."""
    body = json.dumps(
        {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.osv.dev/v1/query",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"ERROR: OSV query failed for {name}=={version}: {exc}", file=sys.stderr)
        sys.exit(2)
    return data.get("vulns", [])


def main() -> int:
    json_output = "--json" in sys.argv

    ignored = _load_ignore_list(IGNORE_LIST_PATH)
    results: list[dict] = []
    unexpected_count = 0

    for name, version in BUNDLE_PINS:
        vulns = _query_osv(name, version)
        for v in vulns:
            vid = v.get("id", "?")
            is_ignored = vid in ignored
            if not is_ignored:
                unexpected_count += 1
            summary = (v.get("summary") or v.get("details", "") or "").split("\n")[0][:200]
            aliases = v.get("aliases", [])
            results.append(
                {
                    "package": name,
                    "version": version,
                    "id": vid,
                    "aliases": aliases,
                    "ignored": is_ignored,
                    "summary": summary,
                }
            )

    if json_output:
        print(json.dumps(
            {"unexpected_count": unexpected_count, "results": results},
            indent=2,
            ensure_ascii=False,
        ))
    else:
        print(f"OSV check — {len(BUNDLE_PINS)} pinned packages, "
              f"{len(results)} vulnerabilities total, "
              f"{unexpected_count} UNEXPECTED (not in ignore-list)")
        print("-" * 100)
        for r in sorted(results, key=lambda x: (x["package"], x["id"])):
            mark = "OK " if r["ignored"] else "❗ "
            print(f"{mark} {r['package']:18} {r['version']:10} {r['id']:20} "
                  f"{r['summary']}")
        if unexpected_count:
            print()
            print(f"❗ {unexpected_count} UNEXPECTED CVE(s) — review and either:")
            print("   (a) add to installer/pip-audit-ignore.txt with justification, or")
            print("   (b) bump the dependency to a fixed version.")

    return 1 if unexpected_count else 0


if __name__ == "__main__":
    sys.exit(main())
