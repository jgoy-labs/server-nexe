"""Golden master for the #969 split of core/endpoints/installer.py.

Written against the UNSPLIT module and green before every move. The split is
supposed to be a move: same code, different file. These tests hold the parts
that a move can break silently — the wiring nothing else asserts.

Assertions here are not to be edited while the split runs. A move that needs
one of them changed is not a move: it changed behaviour.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from core.endpoints import installer

ENDPOINTS_DIR = Path(installer.__file__).parent


def _installer_modules() -> list:
    """Every core.endpoints.installer* module that exists right now.

    One module today, seven when the split lands — which is the point: the
    invariants below are stated over the family, not over one file.
    """
    mods = []
    for path in sorted(ENDPOINTS_DIR.glob("installer*.py")):
        if path.stem == "installer_progress":
            continue  # its own subsystem (SSE progress sources), not part of #969
        mods.append(importlib.import_module(f"core.endpoints.{path.stem}"))
    return mods


class TestTheRouterSurface:
    """The eight routes are the contract with the wizard. A decorator lost in a
    move takes an endpoint off the air, and no unit test of the moved function
    would notice."""

    EXPECTED = {
        ("GET", "/installer/preflight", "installer_preflight"),
        ("GET", "/installer/download", "installer_download_model"),
        ("POST", "/installer/hf-token", "installer_set_hf_token"),
        ("POST", "/installer/ollama", "installer_ollama_install"),
        ("POST", "/installer/finalize", "installer_finalize_post"),
        ("GET", "/installer/finalize", "installer_finalize_get"),
        ("GET", "/installer/check-metal", "installer_check_metal"),
        ("GET", "/installer/state", "installer_state"),
    }

    def test_the_eight_routes_are_registered_with_their_operation_ids(self) -> None:
        actual = {
            (method, route.path, route.operation_id)
            for route in installer.router.routes
            for method in route.methods
            if method != "HEAD"
        }
        assert actual == self.EXPECTED


class TestTheLoadBearingSingletons:
    """Two module globals carry a guarantee, not just a value.

    `_dl_executor` is max_workers=1 on purpose: it serialises the blocking
    download work. `_ollama_install_lock` stops two `zip_extract` runs from
    landing on /Applications/Ollama.app at once and corrupting it.

    Split the file and each new module can quietly build its own. Nothing
    would fail — the serialisation and the mutual exclusion would just stop
    existing. So the invariant is stated over the whole family: exactly one
    construction site, and one object shared by everyone who uses it.
    """

    def test_the_download_executor_serialises(self) -> None:
        # Looked up across the family, not on one module: the executor moves
        # during the split and the FACT asserted here must not move with it.
        owners = [m for m in _installer_modules() if hasattr(m, "_dl_executor")]
        assert owners, "the download executor disappeared in the split"
        assert all(m._dl_executor._max_workers == 1 for m in owners)

    @staticmethod
    def _construction_sites(pattern: str) -> list[str]:
        """Where the family builds this thing, one entry per occurrence."""
        return [
            f"{m.__name__}:{i}"
            for m in _installer_modules()
            for i, line in enumerate(Path(m.__file__).read_text(encoding="utf-8").splitlines(), 1)
            if re.search(pattern, line)
        ]

    def test_the_executor_is_built_exactly_once_across_the_family(self) -> None:
        sites = self._construction_sites(r"ThreadPoolExecutor\s*\(")
        assert len(sites) == 1, f"the download executor must have ONE home, found: {sites}"

    def test_the_ollama_lock_is_built_exactly_once_across_the_family(self) -> None:
        sites = self._construction_sites(r"_ollama_install_lock\s*=\s*\w*\.?Lock\s*\(")
        assert len(sites) == 1, f"the install lock must have ONE home, found: {sites}"

    def test_everyone_who_uses_them_uses_the_same_object(self) -> None:
        executors = {id(m._dl_executor) for m in _installer_modules() if hasattr(m, "_dl_executor")}
        locks = {id(m._ollama_install_lock) for m in _installer_modules() if hasattr(m, "_ollama_install_lock")}
        assert len(executors) == 1, "two executors is two queues: the serialisation is gone"
        assert len(locks) == 1, "two locks is no lock"


class TestEachNameHasOneHome:
    """The split MOVES definitions; it must never copy them.

    Two live copies of `_models_dir` is the worst outcome of a split: both
    importable, one stale, and every test still green. This asserts one
    definition per name across the whole family.

    It deliberately says nothing about imports. `from installer_shared import
    _models_dir` binds the name in the importing module, which is correct and
    necessary — and it means a test must patch the module that CALLS the
    function, not the one that defines it. Patching the definition site leaves
    the caller's binding untouched: green, and testing nothing.
    """

    MOVED = [
        "_sse", "_models_dir", "_safe_model_basename", "_resolve_model_path",
        "_finalize_marker_path", "_client_is_loopback",
        "_is_hf_hub_url", "_hf_repo_id_from_url", "_preflight_repo_id",
        "_ensure_hf_token_in_env", "_check_model_access", "_preflight_hf_access",
        "_dry_run_plan", "_hf_download_with_retry",
        "_stream_mlx", "_stream_gguf", "_stream_ollama", "_stream_embedder",
        "_is_allowed_gguf_url", "_sha256_check",
        "_find_ollama_bin", "_install_ollama_and_locate", "_install_ollama_if_needed",
        "_fastembed_cache_dir", "_fastembed_model_bytes", "_embedder_model_present",
    ]

    def test_each_name_lives_in_exactly_one_module(self) -> None:
        homes = {}
        for name in self.MOVED:
            # one entry per DEFINITION, not per module: a copy left behind in
            # the same file has to fail here too, or "moved" is unverified.
            owners = [
                f"{m.__name__}:{i}"
                for m in _installer_modules()
                for i, line in enumerate(Path(m.__file__).read_text(encoding="utf-8").splitlines(), 1)
                if re.match(rf"(async def|def|class) {re.escape(name)}\b", line)
            ]
            homes[name] = owners
        multiple = {n: o for n, o in homes.items() if len(o) > 1}
        missing = {n: o for n, o in homes.items() if not o}
        assert not multiple, f"defined twice — the move copied instead of moving: {multiple}"
        assert not missing, f"defined nowhere — lost in the move: {missing}"
