"""INST-002 — la via GUI/SSE ha d'avisar quan el model no té pin SHA256.

El CLI ja imprimeix un ⚠️ groc i el contracte de download_verify exigeix que el
cridador faci visible l'avís. La via GUI/SSE només feia logger.info + return
None. Ara emet un event `warning` (SHA256_NOT_PINNED) que NO avorta la
instal·lació (només els `error` avorten).
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _sse_events(text):
    events = []
    for chunk in text.split("\n\n"):
        line = next((l for l in chunk.splitlines() if l.startswith("data: ")), None)
        if line:
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError:
                pass
    return events


@pytest.fixture
def installer_app():
    from core.endpoints.installer import router
    app = FastAPI()
    app.include_router(router)
    return app


def test_inst002_unpinned_download_emits_warning_and_completes(installer_app, monkeypatch, tmp_path):
    """An unpinned model emits a SHA256_NOT_PINNED warning event and, even so,
    the installation reaches `done` (the warning does not abort)."""
    from core.endpoints import installer as inst
    import installer.download_verify as dv

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(inst, "_models_dir", lambda: tmp_path)
    monkeypatch.setattr(inst, "_check_model_access", lambda repo_id, token=None: {"status": "ok"})

    def fake_snap(repo_id, local_dir, tqdm_class=None, **kw):
        from pathlib import Path as _P
        (_P(local_dir) / "config.json").write_bytes(b"{}")

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snap)
    # no pin → verify retorna False
    monkeypatch.setattr(dv, "verify_download_integrity", lambda *a, **k: False)

    with TestClient(installer_app) as client:
        with client.stream("GET", "/installer/download",
                           params={"engine": "mlx", "model_id": "ns/unpinned-model"}) as r:
            body = "".join(chunk for chunk in r.iter_text())

    events = _sse_events(body)
    warnings = [e for e in events if e.get("type") == "warning"]
    assert any(e.get("code") == "SHA256_NOT_PINNED" for e in warnings), (
        "INST-002: un model sense pin ha d'emetre un warning SHA256_NOT_PINNED"
    )
    assert not any(e.get("type") == "error" for e in events), "el warning no és un error"
    assert any(e.get("type") == "done" for e in events), "la instal·lació ha de completar (done)"
