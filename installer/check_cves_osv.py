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
    ("mlx-lm", "0.31.3"),
    ("mlx-vlm", "0.4.4"),
    ("llama-cpp-python", "0.3.19"),
    # transformers is transitive via mlx-lm/mlx-vlm but now explicitly pinned in
    # requirements-macos.txt to ==5.12.1 (unpinned it resolved to 5.13.0, which
    # breaks mlx-lm 0.31.3 at import — finding 820). Audit the pinned version.
    ("transformers", "5.12.1"),
]

# requirements-windows.txt pins win_arm64-only wheels (pywin32, lingua 2.2.0)
# that pip-audit cannot resolve on the Linux CI runner, so its pins are audited
# here by (name, version) instead (WS8-04).
WINDOWS_REQUIREMENTS_PATH = Path(__file__).parent.parent / "requirements-windows.txt"


def _parse_pinned_requirements(path: Path) -> list[tuple[str, str]]:
    """Extract exact ``name==version`` pins from a requirements file.

    Environment markers are stripped (OSV audits the package regardless of
    platform). Non-exact specs (ranges) are skipped with a notice — the only
    one today, huggingface_hub, carries the same range as requirements.txt,
    which pip-audit already resolves and scans in CI.
    """
    pins: list[tuple[str, str]] = []
    if not path.exists():
        print(f"NOTICE: {path.name} not found; skipping its pins", file=sys.stderr)
        return pins
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        if "==" in line:
            name, _, version = line.partition("==")
            pins.append((name.strip(), version.strip()))
        else:
            print(f"NOTICE: skipping non-pinned spec (covered by pip-audit): {line}",
                  file=sys.stderr)
    return pins

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
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310  # nosemgrep: dynamic-urllib-use-detected — hardcoded HTTPS OSV API endpoint
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"ERROR: OSV query failed for {name}=={version}: {exc}", file=sys.stderr)
        sys.exit(2)
    return data.get("vulns", [])


def evaluate_package_vulns(name: str, version: str, vulns: list[dict], ignored: set[str]) -> tuple[int, list[dict]]:
    """Score one package's OSV vulns → (unexpected_count, result rows).

    Pure (no network) so the dedup + alias-aware ignore logic is testable
    without hitting OSV. Rules:
      * a vuln OSV returns under multiple ids (GHSA + PYSEC) is deduped
        WITHIN the package via the id∪aliases group, so it is neither
        double-counted nor double-reported;
      * an ignore-list entry matches the canonical id OR any alias.
    """
    unexpected = 0
    rows: list[dict] = []
    seen_ids: set[str] = set()
    for v in vulns:
        vid = v.get("id", "?")
        id_group = {vid, *v.get("aliases", [])}
        if id_group & seen_ids:
            continue
        seen_ids |= id_group
        is_ignored = bool(id_group & ignored)
        if not is_ignored:
            unexpected += 1
        summary = (v.get("summary") or v.get("details", "") or "").split("\n")[0][:200]
        rows.append({
            "package": name,
            "version": version,
            "id": vid,
            "aliases": v.get("aliases", []),
            "ignored": is_ignored,
            "summary": summary,
        })
    return unexpected, rows


def main() -> int:
    json_output = "--json" in sys.argv

    ignored = _load_ignore_list(IGNORE_LIST_PATH)
    results: list[dict] = []
    unexpected_count = 0

    windows_pins = _parse_pinned_requirements(WINDOWS_REQUIREMENTS_PATH)
    # dedupe: a pin present in both lists is queried once
    all_pins = list(dict.fromkeys(BUNDLE_PINS + windows_pins))

    for name, version in all_pins:
        vulns = _query_osv(name, version)
        pkg_unexpected, pkg_rows = evaluate_package_vulns(name, version, vulns, ignored)
        unexpected_count += pkg_unexpected
        results.extend(pkg_rows)

    if json_output:
        print(json.dumps(
            {"unexpected_count": unexpected_count, "results": results},
            indent=2,
            ensure_ascii=False,
        ))
    else:
        print(f"OSV check — {len(all_pins)} pinned packages, "
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
