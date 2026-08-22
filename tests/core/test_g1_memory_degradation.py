"""G1 (#888) — break memory/ and the server still comes up.

memory/ is DEGRADABLE by decision: "sense memoria" means "sense records vells",
never "sense conversa" (the conversation lives in the web_ui session store and
is written to disk before memory/ is ever touched). The product must therefore
survive a memory/ that does not even import.

It did not. A single module-level import — core/endpoints/chat_memory.py ->
memory.memory.constants — was reached from create_app() through
factory.py -> factory_state.py -> endpoints/__init__.py -> v1.py -> chat.py,
with no guard, while the OPTIONAL routers three screens below in the same v1.py
were all wrapped in `except ImportError`. The structural import was left bare
and the optional ones were protected. Result: no /health, no /ui, no installer.

The check runs in a SUBPROCESS on purpose: the blocker has to be on
sys.meta_path before core is imported, and by the time pytest runs the whole
tree is loaded already. It also keeps the poisoned sys.modules out of the suite.

Deliberately NOT asserted here: that a chat request returns 200. That needs a
mocked engine, and a mock is exactly what could hide the path we are testing.
401 proves the route is registered and answering.
"""
from __future__ import annotations

import os
import subprocess  # nosec B404: fixed argv, no shell, test-only
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PROBE = '''
import sys, os, importlib.abc

sys.path.insert(0, os.environ["NEXE_G1_ROOT"])

# The WHOLE package, not a list of subpackages. The first version of this gate
# named four of them and left memory.shared out; a bare
# `from memory.shared.cache import *` added to core/endpoints/chat.py — inside
# the very chain this gate exists to protect — kept the gate green. A hand-kept
# list of what may break is a list of doors someone has to remember to close.
# A broken install does not break four subpackages: it breaks memory/.
BLOCKED = ("memory",)
blocked_names = []


class _Blocker(importlib.abc.MetaPathFinder):
    """Make every memory/ import fail, the way a broken install would."""

    def find_spec(self, fullname, path=None, target=None):
        for prefix in BLOCKED:
            if fullname == prefix or fullname.startswith(prefix + "."):
                blocked_names.append(fullname)
                raise ImportError("G1: memory/ is broken: " + fullname)
        return None


sys.meta_path.insert(0, _Blocker())

from fastapi.testclient import TestClient
from core.server.factory import create_app

app = create_app()
print("G1-CREATE-APP-OK routes=%d" % len(app.routes))

# TrustedHostMiddleware rejects TestClient's default "testserver" host with a
# 400, which would look like a failure of this test instead of a wrong Host.
client = TestClient(app, base_url="http://127.0.0.1")

for path in ("/health", "/ui/", "/v1"):
    r = client.get(path)
    print("G1-GET %s -> %d" % (path, r.status_code))

r = client.post(
    "/v1/chat/completions",
    json={"model": "x", "messages": [{"role": "user", "content": "hola"}]},
)
print("G1-POST /v1/chat/completions -> %d" % r.status_code)

# Control: if nothing was actually blocked, everything above passes for the
# wrong reason — a green gate that never touched memory/ at all.
print("G1-BLOCKED-COUNT %d" % len(blocked_names))

# Second control: the reach of the blocker itself. memory.shared was NOT in the
# original BLOCKED list, so an import of it went straight through while the gate
# reported success. Ask the blocker about a subpackage nobody listed and about
# the package root, and prove it says no to both.
for probe_name in ("memory.shared.cache", "memory"):
    try:
        __import__(probe_name)
        print("G1-REACH %s -> WENT-THROUGH" % probe_name)
    except ImportError:
        print("G1-REACH %s -> blocked" % probe_name)

print("G1-DONE")
'''


def _run_probe(tmp_path: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "g1_probe.py"
    script.write_text(PROBE)
    env = dict(os.environ)
    env["NEXE_G1_ROOT"] = str(REPO_ROOT)
    # NEXE_SIDECAR=1 makes create_app() fail fast on missing sidecar env vars,
    # which has nothing to do with memory/.
    env.pop("NEXE_SIDECAR", None)
    return subprocess.run(  # nosec B603: sys.executable + generated script, no shell
        [sys.executable, str(script)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> subprocess.CompletedProcess:
    return _run_probe(tmp_path_factory.mktemp("g1"))


def _fail_message(proc: subprocess.CompletedProcess) -> str:
    return (
        f"G1 probe exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n"
        f"--- stderr ---\n{proc.stderr[-3000:]}"
    )


def test_create_app_survives_a_broken_memory_package(probe):
    """The whole point: create_app() returns an app, not an ImportError."""
    assert probe.returncode == 0, _fail_message(probe)
    assert "G1-CREATE-APP-OK" in probe.stdout, _fail_message(probe)


def test_the_blocker_actually_blocked_something(probe):
    """Control against a gate that is green because it tested nothing."""
    line = [ln for ln in probe.stdout.splitlines()
            if ln.startswith("G1-BLOCKED-COUNT")]
    assert line, _fail_message(probe)
    assert int(line[0].split()[-1]) > 0, (
        "no memory/ import was blocked — the probe never exercised the "
        "degraded path" + _fail_message(probe)
    )


@pytest.mark.parametrize("name", ["memory.shared.cache", "memory"])
def test_the_blocker_reaches_the_whole_package(probe, name):
    """A subpackage nobody listed must break too (found 2026-08-22).

    The gate shipped with a four-name BLOCKED list. Adding
    `from memory.shared.cache import *` to core/endpoints/chat.py — a file
    create_app() imports — left it green: the broken install it simulated was
    not broken where it mattered. What this gate claims is "memory/ does not
    import", so the blocker has to cover memory/, not a list someone maintains.
    """
    assert f"G1-REACH {name} -> blocked" in probe.stdout, _fail_message(probe)


@pytest.mark.parametrize("path", ["/health", "/ui/", "/v1"])
def test_core_endpoints_answer_with_memory_broken(probe, path):
    """/health, the UI and the v1 root are the product coming up at all."""
    assert f"G1-GET {path} -> 200" in probe.stdout, _fail_message(probe)


def test_chat_completions_route_is_registered_with_memory_broken(probe):
    """401 = the route exists and answers. 404/500 would mean it does not."""
    line = [ln for ln in probe.stdout.splitlines()
            if ln.startswith("G1-POST /v1/chat/completions")]
    assert line, _fail_message(probe)
    status = int(line[0].split()[-1])
    assert status in (401, 403), (
        f"expected an auth answer from a live route, got {status}"
        + _fail_message(probe)
    )
