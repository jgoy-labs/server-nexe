"""
WS8-04 — OSV gate logic: Windows-pin parsing, alias-aware ignore, and
within-package dedup. These are the three behaviors the gate commit added;
they had zero direct coverage (the pre-existing tests only string-matched
ci.yml), so a regression re-breaking any of them shipped green.
"""

from pathlib import Path

from installer.check_cves_osv import (
    _parse_pinned_requirements,
    evaluate_package_vulns,
)

WINDOWS_REQS = Path(__file__).resolve().parents[2] / "requirements-windows.txt"


class TestParsePinnedRequirements:
    def test_extracts_exact_pins_and_skips_ranges(self, tmp_path):
        f = tmp_path / "reqs.txt"
        f.write_text(
            "# comment\n"
            "fastapi==0.136.3\n"
            "pywin32==312 ; sys_platform == 'win32'\n"  # marker stripped
            "huggingface_hub>=1.13.0,<1.14\n"  # range -> skipped
            "\n"
        )
        pins = _parse_pinned_requirements(f)
        assert ("fastapi", "0.136.3") in pins
        assert ("pywin32", "312") in pins
        assert all(name != "huggingface_hub" for name, _ in pins)

    def test_missing_file_returns_empty(self, tmp_path):
        assert _parse_pinned_requirements(tmp_path / "nope.txt") == []

    def test_real_windows_requirements_are_scanned(self):
        pins = _parse_pinned_requirements(WINDOWS_REQS)
        names = {n for n, _ in pins}
        # the win-only pins the gate must now cover
        assert "pywin32" in names
        assert "cryptography" in names


class TestAliasAwareIgnore:
    def test_ignore_matches_via_alias_not_just_canonical_id(self):
        # torch case: OSV returns GHSA-* whose alias is the ignored PYSEC id
        vulns = [{"id": "GHSA-rrmf-rvhw-rf47", "aliases": ["CVE-2025-3000", "PYSEC-2025-194"]}]
        ignored = {"PYSEC-2025-194"}
        unexpected, rows = evaluate_package_vulns("torch", "2.11.0", vulns, ignored)
        assert unexpected == 0, "an alias in the ignore-list must suppress the vuln"
        assert rows[0]["ignored"] is True

    def test_unignored_vuln_counts(self):
        vulns = [{"id": "GHSA-real", "aliases": ["CVE-9999"]}]
        unexpected, _ = evaluate_package_vulns("p", "1.0", vulns, set())
        assert unexpected == 1


class TestWithinPackageDedup:
    def test_same_vuln_two_ids_counted_once(self):
        # OSV returns the same vuln as two entries (GHSA + PYSEC)
        vulns = [
            {"id": "GHSA-m959-cc7f-wv43", "aliases": ["CVE-2026-34073", "PYSEC-2026-35"]},
            {"id": "PYSEC-2026-35", "aliases": ["CVE-2026-34073", "GHSA-m959-cc7f-wv43"]},
        ]
        unexpected, rows = evaluate_package_vulns("cryptography", "46.0.3", vulns, set())
        assert unexpected == 1, "the same vuln under two ids must not double-count"
        assert len(rows) == 1

    def test_dedup_ignored_pair_stays_zero(self):
        vulns = [
            {"id": "GHSA-x", "aliases": ["PYSEC-IGN"]},
            {"id": "PYSEC-IGN", "aliases": ["GHSA-x"]},
        ]
        unexpected, rows = evaluate_package_vulns("p", "1.0", vulns, {"PYSEC-IGN"})
        assert unexpected == 0
        assert len(rows) == 1

    def test_distinct_vulns_both_counted(self):
        vulns = [
            {"id": "GHSA-a", "aliases": ["CVE-1"]},
            {"id": "GHSA-b", "aliases": ["CVE-2"]},
        ]
        unexpected, _ = evaluate_package_vulns("p", "1.0", vulns, set())
        assert unexpected == 2
