#!/usr/bin/env python3
"""
Lint i18n keys used in code against modular translation JSON files.

Checks for keys used via:
- t_modular("...")
- _translate(i18n, "...")
- get_message(i18n, "...")
- i18n.t("...") / self.i18n.t("...") / get_i18n().t("...")
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "storage",
    "snapshots",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

PATTERNS = [
    re.compile(r"\bt_modular\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\b_translate\(\s*[^,]+,\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\bget_message\(\s*[^,]+,\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\b(?:self\.)?i18n\.t\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\bget_i18n\(\)\.t\(\s*['\"]([^'\"]+)['\"]"),
]


def _iter_code_files() -> Iterable[Path]:
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def _extract_keys(path: Path) -> Set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return set()

    keys: Set[str] = set()
    for pattern in PATTERNS:
        for match in pattern.findall(text):
            if isinstance(match, tuple):
                key = match[0]
            else:
                key = match
            if key:
                keys.add(key)
    return keys


def _flatten_keys(data: Dict, prefix: str = "") -> Set[str]:
    keys: Set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            keys |= _flatten_keys(value, f"{prefix}{key}.")
        elif isinstance(value, str):
            keys.add(f"{prefix}{key}")
    return keys


def _collect_languages() -> Set[str]:
    langs: Set[str] = set()
    for path in ROOT.rglob("messages_*.json"):
        parts = list(path.parts)
        if "languages" not in parts:
            continue
        idx = parts.index("languages")
        if idx + 1 < len(parts):
            langs.add(parts[idx + 1])
    return langs


def _load_translations(langs: Iterable[str]) -> Dict[str, Set[str]]:
    keys_by_lang: Dict[str, Set[str]] = {}
    for lang in langs:
        keys: Set[str] = set()
        pattern = f"languages/{lang}/messages_*.json"
        for file_path in ROOT.rglob(pattern):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if isinstance(data, dict) and "_meta" in data:
                data = dict(data)
                data.pop("_meta", None)

            stem = file_path.stem
            prefix = stem[len("messages_") :] if stem.startswith("messages_") else stem
            if isinstance(data, dict) and prefix in data and isinstance(data[prefix], dict):
                payload = data[prefix]
            else:
                payload = data if isinstance(data, dict) else {}

            for item in _flatten_keys(payload):
                keys.add(f"{prefix}.{item}")

        keys_by_lang[lang] = keys
    return keys_by_lang


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint i18n keys used in code.")
    parser.add_argument("--langs", nargs="*", help="Languages to check (default: auto-detect)")
    parser.add_argument("--strict", action="store_true", help="Fail on unknown components")
    args = parser.parse_args()

    langs = set(args.langs or []) or _collect_languages()
    if not langs:
        print("No languages detected.")
        return 1

    keys_in_code: Set[str] = set()
    for path in _iter_code_files():
        keys_in_code |= _extract_keys(path)

    if not keys_in_code:
        print("No i18n keys detected in code.")
        return 0

    keys_by_lang = _load_translations(sorted(langs))
    all_known_components: Set[str] = set()
    for lang_keys in keys_by_lang.values():
        for key in lang_keys:
            component = key.split(".", 1)[0]
            all_known_components.add(component)

    missing_by_lang: Dict[str, List[str]] = {lang: [] for lang in sorted(langs)}
    unknown_components: Set[str] = set()

    for key in sorted(keys_in_code):
        if "." not in key:
            unknown_components.add(key)
            continue
        component = key.split(".", 1)[0]
        if component not in all_known_components:
            unknown_components.add(key)
            continue
        for lang in sorted(langs):
            if key not in keys_by_lang.get(lang, set()):
                missing_by_lang[lang].append(key)

    print(f"Languages: {', '.join(sorted(langs))}")
    print(f"Found {len(keys_in_code)} i18n key(s) in code.")

    missing_total = 0
    for lang, missing in missing_by_lang.items():
        if missing:
            missing_total += len(missing)
            print(f"\nMissing in {lang} ({len(missing)}):")
            for key in missing:
                print(f"  - {key}")

    if unknown_components:
        print(f"\nUnknown or non-modular keys ({len(unknown_components)}):")
        for key in sorted(unknown_components):
            print(f"  - {key}")

    if missing_total > 0:
        return 1
    if unknown_components and args.strict:
        return 2

    print("\nOK: All detected modular keys are present in all languages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
