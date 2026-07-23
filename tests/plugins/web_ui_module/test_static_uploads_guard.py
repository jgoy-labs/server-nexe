"""
WS5-01 gate — user uploads live under ui_dir (ui_dir/uploads) but must NOT be served
by the unauthenticated serve_static endpoint. /ui/upload and /ui/files require the
X-API-Key; /ui/static/{path} has no auth, so without a guard a peer on an opt-in remote
binding (Tailscale/LAN) could exfiltrate an uploaded document by name.

RED→GREEN: before the guard, the probe file (which really exists under ui_dir) is served
with 200; after the guard, /ui/static/uploads/<name> returns 404 regardless of existence.
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("NEXE_PRIMARY_API_KEY", "nexe-integration-test")
    os.environ.setdefault("NEXE_ENV", "testing")
    os.environ.setdefault("NEXE_DEV_MODE", "true")
    from core.app import app
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def _upload_dir() -> Path:
    import plugins.web_ui_module.module as m
    return Path(m.__file__).parent / "ui" / "uploads"


def test_uploaded_file_not_served_by_unauth_static(client):
    """A real file under ui_dir/uploads must not leak via unauthenticated /static/."""
    ud = _upload_dir()
    ud.mkdir(parents=True, exist_ok=True)
    probe = ud / "ws5-01-secret-probe.txt"
    probe.write_text("TOP-SECRET-UPLOAD-CONTENTS")
    try:
        # No X-API-Key header: serve_static is unauthenticated by design (it serves the
        # UI's own CSS/JS). The uploads subtree must be refused here.
        r = client.get("/ui/static/uploads/ws5-01-secret-probe.txt")
        assert r.status_code == 404, f"upload leaked via /static (status {r.status_code})"
        assert "TOP-SECRET-UPLOAD-CONTENTS" not in r.text
    finally:
        probe.unlink(missing_ok=True)


def test_uploads_path_is_404_even_when_absent(client):
    """The guard must not confirm existence: a non-existent upload is also 404."""
    r = client.get("/ui/static/uploads/does-not-exist-xyz.txt")
    assert r.status_code == 404


def test_normal_static_asset_still_served(client):
    """Regression: guarding uploads must not break normal (public) static serving."""
    r = client.get("/ui/static/app.js")
    assert r.status_code == 200
    # ties the two WS5 fixes together: the served asset carries the WS5-02 escapeAttr fix
    assert "escapeAttr" in r.text
