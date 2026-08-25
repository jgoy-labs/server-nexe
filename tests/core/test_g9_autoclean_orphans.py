"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_g9_autoclean_orphans.py
Description: G9 gate (#886) — no manifest in the repo may declare an auto-clean
    that no code executes, and no core/lifespan* module may call auto-clean.

    Background: core/lifespan_auto_clean.py imported
    personality.auto_clean.core.auto_clean, which does not exist in this repo,
    and the failure was swallowed by `except ImportError` with a debug log. The
    user could switch auto-clean on and nothing was ever cleaned. Decision of
    23/08/2026 (finding #886): the feature leaves the core and is documented as
    the future `trasher` plugin
    (plugins-nexe/plugins/1 - DRAFT/trasher/DISSENY-auto-clean.md).

    Scope of the gate: the `auto_clean` key is the one that CLAIMS an engine
    runs the policy. The descriptive retention spec that surrounds it
    (retention_days, action, max_files, protected_patterns) stays in the
    manifests on purpose — it is the specification the trasher plugin will
    implement, and removing it was not part of the decision.

    A1-bis (23/08/2026): the gate used to name a single key, `auto_clean`, which
    is the G1 hole of the night before — a gate that ENUMERATES can be walked
    around by the side door. It now judges by READER, not by name: every key
    declared under [module.storage] of every discovered manifest, and every
    NEXE_* declared in .env.example, must have production code that reads it.
    Zero readers = orphan.

    Keys that are orphans today but sit OUTSIDE the #886 decision are not
    deleted: they are listed as dated, motivated exceptions, and the gate turns
    red if that list GROWS (scope control, inverted).

    Rule §1.7: the manifests are DISCOVERED, never listed by hand, and the
    discovery carries its own scope control (see test_discovery_scope_control).

    Mutation targets, all documented in resultats/dev1_result.md:
      1. re-add one orphan `auto_clean` line to any manifest -> RED
      2. narrow the discovery (e.g. to memory/ only) -> RED
      3. re-add `cooldown_minutes = 60` to any manifest -> RED
      4. grow the exception list with an invented key -> RED

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import ast
import functools
import importlib.util
import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "g9_surviving_orphans_baseline.json"

# Directories the discovery must never walk into.
# - venv/ and .git/: third-party and history, not our declarations.
# - _tmp/, node_modules/: scratch.
# - worktrees/server-nexe-win/: §8 of the night plan — the Windows worktree is
#   explicitly out of scope tonight, so its copy of these manifests must not
#   turn this gate red for work nobody was asked to do.
# - InstallNexe.app/, Install Nexe.app/, Nexe.app/ (#945): build artefacts
#   .gitignore already excludes — bundled Python 3.12 stdlib + vendored pip.
#   _has_reader walking into tempfile.py's own cleanup() method is how an
#   invented `cleanup` manifest key found a "reader" that has nothing to do
#   with this repo's storage keys.
EXCLUDED_DIRS = {
    "venv", ".git", "_tmp", "node_modules", "worktrees",
    "InstallNexe.app", "Install Nexe.app", "Nexe.app",
}

# VERSIONED manifest.toml files outside the exclusions: 16, measured on
# 23/08/2026 with `git ls-tree -r --name-only HEAD | grep -c 'manifest\.toml$'`.
#
# It was 17 until the Phase C audit caught why: the machine this gate was
# written on also had InstallNexe.app/Contents/Resources/.../manifest.toml on
# disk — a BUILD ARTEFACT that .gitignore:39 excludes. A clean checkout (which
# is exactly what CI does: actions/checkout + pytest tests, ci.yml:145) finds
# 16 and the gate went red on work nobody had touched.
#
# The lesson is in the number, so it stays written here: a gate that counts
# files on disk must be calibrated in a CLEAN tree, never in the working
# directory of whoever wrote it.
#
# It is a floor, not an equality: adding a plugin must not break the gate,
# but a discovery that silently stops finding files must.
MIN_MANIFESTS = 16

# Every top-level directory that holds manifests today. A discovery narrowed to
# a subtree loses one of these and fails.
EXPECTED_ROOTS = {"core", "memory", "plugins"}

AUTO_CLEAN_KEY = "auto_clean"

ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Orphan storage keys measured on 23/08/2026 that survive ON PURPOSE, each with
# the reason it is still there. They are NOT covered by the #886 decision, so
# deleting them would be scope nobody asked for (§6). They are candidates for
# Phase C / a decision by Jordi, not silent debt.
SURVIVING_ORPHANS = {
    ("memory/embeddings/manifest.toml", "max_size_gb"):
        "cache size ceiling (5.0); outside the six keys #886 names — pending a decision by Jordi",
    ("memory/embeddings/manifest.toml", "protected_patterns"):
        "a PROTECTION, not a cleanup policy: it says what must never be touched",
    ("memory/memory/manifest.toml", "max_files"):
        "ledger rotation ceiling (100); outside the six keys #886 names — pending a decision by Jordi",
    ("memory/memory/manifest.toml", "protected_patterns"):
        "a PROTECTION, not a cleanup policy: it says what must never be touched",
    ("memory/rag/manifest.toml", "protected_patterns"):
        "a PROTECTION, not a cleanup policy; RAG declares to protect itself, never to be cleaned",
    ("plugins/security/manifest.toml", "archive_to"):
        "compliance archive target; file outside Dev1's A1-bis scope",
    ("plugins/security/manifest.toml", "protected_patterns"):
        "a PROTECTION, not a cleanup policy; file outside Dev1's A1-bis scope",
}

# Frozen on 23/08/2026, and read from g9_surviving_orphans_baseline.json —
# NOT a sibling constant in this file (#945: MUT-M5b grew SURVIVING_ORPHANS
# and bumped a same-file ceiling in one edit, invisible to review). Adding an
# exception without consciously bumping the separate baseline file still
# turns the gate red. The night-before hole was a discovery that SHRANK;
# here the hole would be a list that GROWS.
SURVIVING_ORPHANS_FROZEN = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["storage_orphans_count"]

# Same idea for .env.example: NEXE_* names nothing reads, kept on purpose.
ENV_SURVIVING_ORPHANS = {
    "NEXE_RATE_LIMIT_CHAT": "no reader today; outside #886 — Phase C candidate",
    "NEXE_RATE_LIMIT_MEMORY": "no reader today; outside #886 — Phase C candidate",
    "NEXE_RATE_LIMIT_RAG": "no reader today; outside #886 — Phase C candidate",
    "NEXE_RATE_LIMIT_UPLOAD": "no reader today; outside #886 — Phase C candidate",
    "NEXE_RATE_LIMIT_DEFAULT": "no reader today; outside #886 — Phase C candidate",
}
ENV_SURVIVING_ORPHANS_FROZEN = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["env_orphans_count"]


def _discover_manifests() -> list:
    """Discover every manifest.toml in the repo, minus the excluded subtrees."""
    return sorted(
        path for path in REPO_ROOT.rglob("manifest.toml")
        if not EXCLUDED_DIRS & set(path.relative_to(REPO_ROOT).parts)
    )


def _discover_lifespan_modules() -> list:
    """Discover every core/lifespan*.py module."""
    return sorted((REPO_ROOT / "core").glob("lifespan*.py"))


def _keys_with(data, key: str, trail: str = "") -> list:
    """Walk a parsed TOML document and return the dotted paths holding `key`."""
    found = []
    if isinstance(data, dict):
        for name, value in data.items():
            here = f"{trail}.{name}" if trail else name
            if name == key:
                found.append(here)
            found.extend(_keys_with(value, key, here))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            found.extend(_keys_with(value, key, f"{trail}[{index}]"))
    return found


@functools.lru_cache(maxsize=1)
def _production_sources() -> tuple:
    """Every .py that is PRODUCTION code: no venv, no worktrees, no test trees.

    A test that mentions a key does not execute it, so test files must not count
    as readers — otherwise this gate would happily accept a key whose only
    "reader" is the assertion that checks it.
    """
    sources = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = set(path.relative_to(REPO_ROOT).parts)
        if EXCLUDED_DIRS & parts or "tests" in parts:
            continue
        sources.append((path, path.read_text(encoding="utf-8", errors="replace")))
    return tuple(sources)


@functools.lru_cache(maxsize=1)
def _production_trees() -> tuple:
    """Every production source, pre-parsed. AST, not text (#945): a comment or
    a module-header docstring must never count as a reader."""
    trees = []
    for path, text in _production_sources():
        try:
            trees.append((path, ast.parse(text, filename=str(path))))
        except SyntaxError:
            continue
    return tuple(trees)


def _has_reader(name: str) -> bool:
    """True when some production module reads `name` as a real identifier —
    a Name, an attribute, a parameter/keyword, a def/class name, an import, or
    a dict/env key looked up by its EXACT string value (config.get("name")).

    #945: NOT a substring match over the raw file text. That accepted a
    comment or a docstring as proof of a reader — every .py in this repo opens
    with a header docstring, and `core/lifespan_sessions.py`'s says "Session
    cleanup task", which alone kept an invented `cleanup` key alive. AST
    walking drops comments for free (they never reach the tree); the string
    case below requires the WHOLE literal to equal `name`, so a sentence that
    merely contains the word — a docstring, a log message — can't forge a hit
    the way a `\\bname\\b` search over free text could.

    Deliberately generous within CODE: a loose identifier or exact-string match
    can only ever keep a key alive, never delete one. Being wrong here means
    leaving a key in place, which is the safe direction.

    Known cost of that choice, measured on 23/08/2026: a HOMONYM counts as a
    reader. `retention_days` looks alive because config_validator.py reads
    `storage.logging.retention_days` from the BASE config, and `ttl_hours` looks
    alive because of `l2_ttl_hours` elsewhere — neither reads these manifests.
    Both are Phase C candidates, written up in the trasher design doc.
    """
    for _path, tree in _production_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name:
                return True
            if isinstance(node, ast.Attribute) and node.attr == name:
                return True
            if isinstance(node, ast.arg) and node.arg == name:
                return True
            if isinstance(node, ast.keyword) and node.arg == name:
                return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                return True
            if isinstance(node, ast.ImportFrom) and name in {node.module or ""} | {a.name for a in node.names}:
                return True
            if isinstance(node, ast.Import) and name in {a.name for a in node.names}:
                return True
            if isinstance(node, ast.Constant) and node.value == name:
                return True
    return False


def _storage_keys(data: dict) -> dict:
    """Discover every key declared under [module.storage], with its dotted path.

    Scalar lists (protected_patterns) count as keys, not as containers to walk
    into — otherwise they slip through the discovery unseen.
    """
    found = {}
    storage = data.get("module", {}).get("storage")
    if not isinstance(storage, dict):
        return found

    def walk(node, trail):
        if isinstance(node, dict):
            for name, value in node.items():
                here = f"{trail}.{name}" if trail else name
                scalar_list = isinstance(value, list) and not any(
                    isinstance(item, (dict, list)) for item in value
                )
                if isinstance(value, (dict, list)) and not scalar_list:
                    walk(value, here)
                else:
                    found.setdefault(name, []).append((here, value))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, (dict, list)):
                    walk(value, f"{trail}[{index}]")

    walk(storage, "module.storage")
    return found


def _declared_env_names() -> list:
    """Discover the NEXE_* names declared in .env.example (commented ones too)."""
    if not ENV_EXAMPLE.is_file():
        return []
    return [
        match.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (match := re.match(r"^\s*#?\s*(NEXE_[A-Z0-9_]+)\s*=", line))
    ]


def _env_names_bound_to_config() -> set:
    """The NEXE_* names that core/config.py or the D-P catalog actually bind."""
    from core.config import NexeSettings
    from core.config_catalog import CATALOG

    bound = {f.alias for f in NexeSettings.model_fields.values() if f.alias}
    bound |= {key.env for key in CATALOG if key.env}
    return bound


def _orphan_storage_keys() -> dict:
    """Every discovered storage key with zero production readers: {(manifest, key): paths}."""
    orphans = {}
    for manifest in _discover_manifests():
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        relative = str(manifest.relative_to(REPO_ROOT))
        for key, occurrences in _storage_keys(data).items():
            if not _has_reader(key):
                orphans[(relative, key)] = occurrences
    return orphans


def _orphan_env_names() -> list:
    """Every NEXE_* in .env.example with no config binding and no production reader."""
    bound = _env_names_bound_to_config()
    return [
        name for name in _declared_env_names()
        if name not in bound and not _has_reader(name)
    ]


def test_discovery_scope_control():
    """Scope control (§1.7): the gate goes red on its own if the discovery shrinks."""
    assert (REPO_ROOT / "core" / "app.py").is_file() and (REPO_ROOT / "pyproject.toml").is_file(), (
        f"discovery is not anchored at the repo root: {REPO_ROOT}"
    )

    manifests = _discover_manifests()
    assert len(manifests) >= MIN_MANIFESTS, (
        f"discovery found {len(manifests)} manifests, fewer than the {MIN_MANIFESTS} "
        f"measured on 23/08/2026 — someone narrowed it. Found: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in manifests]}"
    )

    roots = {p.relative_to(REPO_ROOT).parts[0] for p in manifests}
    missing = EXPECTED_ROOTS - roots
    assert not missing, (
        f"discovery no longer reaches {sorted(missing)}; a manifest there could "
        f"re-declare auto-clean unseen. Roots reached: {sorted(roots)}"
    )

    assert _discover_lifespan_modules(), "no core/lifespan*.py module discovered at all"


def test_no_manifest_declares_an_orphan_auto_clean():
    """#886: nothing in the tree may claim an auto-clean engine that does not exist."""
    offenders = {}
    for manifest in _discover_manifests():
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        declarations = _keys_with(data, AUTO_CLEAN_KEY)
        if declarations:
            offenders[str(manifest.relative_to(REPO_ROOT))] = declarations

    assert not offenders, (
        f"manifests still declare `{AUTO_CLEAN_KEY}` while no code in the core runs it: "
        f"{offenders}. The retention policy belongs to the future `trasher` plugin "
        f"(see plugins-nexe/plugins/1 - DRAFT/trasher/DISSENY-auto-clean.md)."
    )


def test_no_lifespan_module_calls_auto_clean():
    """No core/lifespan* module may import or call auto-clean any more."""
    offenders = {}
    for module in _discover_lifespan_modules():
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        hits = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and "auto_clean" in node.id:
                hits.add(node.id)
            elif isinstance(node, ast.Attribute) and "auto_clean" in node.attr:
                hits.add(node.attr)
            elif isinstance(node, ast.ImportFrom) and "auto_clean" in (node.module or ""):
                hits.add(node.module)
            elif isinstance(node, ast.Import):
                hits.update(a.name for a in node.names if "auto_clean" in a.name)
        if hits:
            offenders[module.name] = sorted(hits)

    assert not offenders, (
        f"lifespan modules still reference auto-clean: {offenders}"
    )


def test_the_dead_auto_clean_module_is_gone():
    """The module whose import never resolved must not be importable any more."""
    assert importlib.util.find_spec("core.lifespan_auto_clean") is None, (
        "core.lifespan_auto_clean is back; it imported personality.auto_clean.core.auto_clean, "
        "which does not exist in this repo, and hid the failure in `except ImportError`."
    )


def test_no_orphan_storage_key_in_manifests():
    """#886, by reader and not by name: no manifest may declare retention nothing runs.

    This is the A1-bis widening. Naming a single key (`auto_clean`) was the G1
    hole: the policy could come back through `cooldown_minutes` or any sibling
    with the gate still green.
    """
    unexpected = {
        f"{manifest}::{key}": [f"{path} = {value!r}" for path, value in occurrences]
        for (manifest, key), occurrences in _orphan_storage_keys().items()
        if (manifest, key) not in SURVIVING_ORPHANS
    }
    assert not unexpected, (
        f"storage keys declared with no production code reading them: {unexpected}. "
        f"Either something reads them, or they belong in the `trasher` design doc "
        f"(plugins-nexe/plugins/1 - DRAFT/trasher/DISSENY-auto-clean.md), not in a manifest."
    )


def test_exception_list_cannot_grow():
    """Inverted scope control: the list of tolerated orphans may shrink, never grow.

    Yesterday's hole was a discovery that shrank. Here the hole would be an
    exception list quietly gaining entries until the gate guards nothing.
    """
    assert len(SURVIVING_ORPHANS) <= SURVIVING_ORPHANS_FROZEN, (
        f"the exception list grew to {len(SURVIVING_ORPHANS)} entries, over the "
        f"{SURVIVING_ORPHANS_FROZEN} frozen on 23/08/2026. An orphan key is not "
        f"fixed by being added here."
    )
    assert len(ENV_SURVIVING_ORPHANS) <= ENV_SURVIVING_ORPHANS_FROZEN, (
        f"the .env.example exception list grew to {len(ENV_SURVIVING_ORPHANS)} entries, "
        f"over the {ENV_SURVIVING_ORPHANS_FROZEN} frozen on 23/08/2026."
    )

    for entry, reason in {**SURVIVING_ORPHANS, **ENV_SURVIVING_ORPHANS}.items():
        assert reason and reason.strip(), f"exception {entry} carries no reason"

    # An exception that is no longer an orphan (someone wrote a reader, or the key
    # is gone) must be removed from the list, not left to rot.
    live_orphans = set(_orphan_storage_keys())
    stale = sorted(entry for entry in SURVIVING_ORPHANS if entry not in live_orphans)
    assert not stale, (
        f"these exceptions are no longer orphan storage keys and must leave the list: {stale}"
    )

    live_env = set(_orphan_env_names())
    stale_env = sorted(name for name in ENV_SURVIVING_ORPHANS if name not in live_env)
    assert not stale_env, (
        f"these .env.example exceptions are no longer orphans and must leave the list: {stale_env}"
    )


def test_env_example_declares_nothing_orphan():
    """.env.example is the side door: a name can survive there long after its field is gone.

    Discovered, not listed: every NEXE_* in the file that neither core/config.py
    nor the D-P catalog binds, and that no production module reads.
    """
    unexpected = [name for name in _orphan_env_names() if name not in ENV_SURVIVING_ORPHANS]
    assert not unexpected, (
        f".env.example still offers {unexpected} to the user while nothing reads them; "
        f"setting one of these does nothing at all."
    )
