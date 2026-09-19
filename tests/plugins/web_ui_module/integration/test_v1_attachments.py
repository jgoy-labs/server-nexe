"""
Integration tests for POST /v1/attachments (C4.3-b).

Lives next to test_web_ui_endpoints.py, not under tests/core/endpoints/,
because it needs the same real lifespan boot (FULL mode, real
SessionManager/FileHandler on app.state) that this directory's conftest
(completed_onboarding_env, autouse) already provides — the endpoint itself
is core/endpoints/attachments.py, not a web UI route.

api_key/client/headers are duplicated from test_web_ui_endpoints.py rather
than imported: cross-file fixture imports read as an unused-import redefined
by every test method's same-named parameter (ruff F811), which the CI ruff
gate rejects.

pytest -m integration  (always runnable, no GPU needed)
"""
import io
import os

import pytest
from fastapi.testclient import TestClient

from core.app import app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def api_key():
    return os.environ.get("NEXE_PRIMARY_API_KEY", "nexe-integration-test")


@pytest.fixture(scope="module")
def client(api_key):
    os.environ.setdefault("NEXE_PRIMARY_API_KEY", api_key)
    os.environ.setdefault("NEXE_ENV", "testing")
    os.environ.setdefault("NEXE_DEV_MODE", "true")
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture(scope="module")
def headers(api_key):
    return {"X-API-Key": api_key}


class TestV1Attachments:

    def _upload(self, client, headers, *, session_id=None, content="Test document content for ingestion.", filename="test_doc.txt", content_type="text/plain"):
        h = dict(headers)
        if session_id is not None:
            h["X-Session-Id"] = session_id
        return client.post(
            "/v1/attachments",
            headers=h,
            files={"file": (filename, io.BytesIO(content.encode()), content_type)},
        )

    def test_upload_valid_txt(self, client, headers):
        """The happy path, asserted as the happy path.

        This read `in [200, 400, 503]` — success, the client's fault and the
        service being down, all three accepted — under a comment saying the
        memory backend might be missing here. Audit 19/09: it is not missing,
        this boot ingests for real (`chunks: 1, ingested: true`), and the
        tolerance made the test unfailable. Measured: raising 503 on the
        endpoint's FIRST line, so nothing whatsoever runs, left this test green
        along with five of its seven neighbours.
        """
        r = self._upload(client, headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ingested"] is True
        assert body["chunks"] >= 1
        assert body["filename"] == "test_doc.txt"

    def test_upload_invalid_extension_rejected(self, client, headers):
        """Rejected BY THE ALLOWLIST, which is what this test is named after.

        The bare `== 400` passed with the extension allowlist disabled
        entirely (measured: `if not valid:` → `if False:` → 8 passed): a `.exe`
        falls over later anyway, on text extraction, and returns 400 for that
        other reason. The body says which of the two happened.
        """
        r = self._upload(client, headers, filename="malware.exe", content="MZ", content_type="application/octet-stream")
        assert r.status_code == 400
        assert "format" in r.json()["detail"].lower(), (
            "a .exe was refused, but not by the format allowlist — this test "
            f"passes for the wrong reason: {r.json()['detail']!r}"
        )

    def test_upload_empty_txt_rejected(self, client, headers):
        r = self._upload(client, headers, filename="empty.txt", content="")
        assert r.status_code == 400, r.text

    def test_upload_without_api_key_401(self, client):
        r = client.post(
            "/v1/attachments",
            files={"file": ("a.txt", io.BytesIO(b"hola"), "text/plain")},
        )
        assert r.status_code == 401

    def test_upload_with_x_session_id_reuses_session(self, client, headers):
        sid = "v1-attachments-test-session"
        r1 = self._upload(client, headers, session_id=sid, content="doc u")
        r2 = self._upload(client, headers, session_id=sid, content="doc dos")
        for r in (r1, r2):
            assert r.status_code == 200, r.text
            assert r.json()["session_id"] == sid

    def test_upload_without_x_session_id_creates_new_session(self, client, headers):
        """Named for creating a session, and now it checks one is created.

        Everything here used to sit under `if r.status_code == 200:`, so a
        non-200 asserted NOTHING — the test passed on an endpoint that answered
        503 to everything. And even at 200 it only checked the id was truthy,
        never that it differed from the caller's, which is the whole claim.
        """
        r1 = self._upload(client, headers, session_id="an-explicit-one", content="doc u")
        r2 = self._upload(client, headers, content="doc dos")
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r2.json()["session_id"]
        assert r2.json()["session_id"] != r1.json()["session_id"]

    def test_upload_invalid_x_session_id_400(self, client, headers):
        r = self._upload(client, headers, session_id="../etc/passwd")
        assert r.status_code == 400
        assert r.json()["detail"] == "invalid_session_id"

    #: attach_to_session's contract (core/files/attach.py) — the exact set,
    #: not "whatever the other door happens to return": both /ui/upload and
    #: /v1/attachments call attach_to_session with zero transformation, so
    #: comparing their two responses to EACH OTHER can never fail — a broken
    #: response shape breaks both identically and the sets still match. This
    #: pins the shape both doors are meant to honour, so a change to either
    #: one alone is what this test exists to catch.
    _ATTACH_RESPONSE_KEYS = {
        "filename", "size", "text_length", "chunks", "preview",
        "ingested", "chunks_saved", "session_id", "has_rag_header",
    }

    def test_response_matches_ui_upload_shape(self, client, headers):
        ui = client.post(
            "/ui/upload",
            headers=headers,
            files={"file": ("parity.txt", io.BytesIO(b"contingut de prova"), "text/plain")},
            data={},
        )
        v1 = self._upload(client, headers, content="contingut de prova", filename="parity.txt")
        if ui.status_code == 200:
            assert set(ui.json().keys()) == self._ATTACH_RESPONSE_KEYS
        if v1.status_code == 200:
            assert set(v1.json().keys()) == self._ATTACH_RESPONSE_KEYS
