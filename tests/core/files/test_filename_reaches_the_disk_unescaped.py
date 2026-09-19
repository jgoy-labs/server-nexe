"""The name a document is saved under is the name everything else calls it.

`attach_to_session` validated the filename with `allow_html` at its default
`False`, so the name was HTML-escaped on the way in. Only the disk used that
escaped name (`validate_file`, `save_file`); the session, the RAG metadata and
the HTTP response have always carried the RAW one. The injection detectors
refuse `<`, `>` and `&` in a name outright, so the one character that survived
them to be escaped was the apostrophe — and `l'informe.txt` reached the disk as
`l&#x27;informe.txt` while the chat bubble, the session and `GET /ui/files`
disagreed about what the file was called. In Catalan and Spanish an apostrophe
in a filename is ordinary, not an edge case.

The fix is the decision the project already took for the chat doors (#1043,
kickoff 31/08 §2.3): "escapar és una protecció de renderitzat, i viu on toca".
The UI escapes when painting — the file preview through `escapeHtml`
(`nexe-files.js:243`) and the chat bubble through a markdown renderer that
escapes raw HTML and refuses every scheme but http/https/mailto.

Two questions, the same pair `tests/core/turn/test_validate_shared.py` asks of
the chat doors:

* **the disk agrees with the answer** — measured with a REAL `FileHandler` over
  `tmp_path`, because a mocked `save_file` cannot tell us what name was written;
* **`check_xss` is still on** — the change flips one flag, not two. That is the
  test that goes red if "stop escaping" is ever implemented as "stop checking".
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from core.files.attach import attach_to_session
from core.files.handler import FileHandler

#: An apostrophe is the only character that reached the escaping: `<`, `>` and
#: `&` are refused by the detectors before it, so this is the whole bug.
APOSTROPHE_NAME = "l'informe.txt"

#: Refused by `detect_xss_attempt` — before the escaping, and still.
XSS_NAME = "<script>alert(1)</script>.txt"

DOC = b"Contingut de prova per a un nom amb apostrof."


@pytest.fixture()
def session():
    s = MagicMock()
    s.id = "filename-session"
    return s


@pytest.fixture()
def session_mgr(session):
    mgr = MagicMock()
    mgr.is_valid_session_id.return_value = True
    mgr.get_or_create_session.return_value = session
    return mgr


@pytest.fixture()
def file_handler(tmp_path):
    """The real one: what is under test is the name that lands on disk."""
    return FileHandler(tmp_path / "uploads")


def _healthy_helper():
    helper = MagicMock()
    helper.save_document_chunks = AsyncMock(
        return_value={"success": True, "chunks_saved": 1}
    )
    return helper


async def _attach(session_mgr, file_handler, filename):
    with patch("core.memory_facts.helper_for", return_value=_healthy_helper()):
        return await attach_to_session(
            app_state=MagicMock(),
            session_mgr=session_mgr,
            file_handler=file_handler,
            filename=filename,
            content=DOC,
            session_id="filename-session",
        )


# ── the disk agrees with everyone else ───────────────────────────────────────

@pytest.mark.asyncio
async def test_an_apostrophe_reaches_the_disk_unescaped(
    session_mgr, file_handler, session,
):
    """Disk, session and response must all call the file the same thing.

    Mutation: drop `allow_html=True` from `core/files/attach.py` and this goes
    red on the first assertion — the file on disk becomes
    `l&#x27;informe.txt` while the body keeps saying `l'informe.txt`.
    """
    body = await _attach(session_mgr, file_handler, APOSTROPHE_NAME)

    # Walked, not listed: uploads live in `<root>/<year>/<yyyymmdd>/` since
    # they moved to the storage tree (#1065).
    saved = [p for p in file_handler.upload_dir.rglob("*") if p.is_file()]
    assert len(saved) == 1, f"expected exactly one saved file, got {saved!r}"
    assert saved[0].name == APOSTROPHE_NAME, (
        f"the filename was escaped on its way to the disk: {saved[0].name!r} "
        "(#1043 — escaping is a rendering protection and lives at the UI)"
    )
    assert "&#x27;" not in saved[0].name, saved[0].name

    # The response never escaped it, which is the half of the split that was
    # already right — it is here so the two halves are pinned together.
    assert body["filename"] == APOSTROPHE_NAME, body["filename"]

    # And so is the name the conversation will use for it.
    session.attach_document.assert_called_once()
    assert session.attach_document.call_args.args[0] == APOSTROPHE_NAME
    session.add_context_file.assert_called_once_with(APOSTROPHE_NAME)


@pytest.mark.asyncio
async def test_an_ordinary_name_is_untouched(session_mgr, file_handler):
    """Convergence is not a swap: the common case must not move."""
    body = await _attach(session_mgr, file_handler, "informe.txt")

    saved = [p for p in file_handler.upload_dir.rglob("*") if p.is_file()]
    assert [p.name for p in saved] == ["informe.txt"]
    assert body["filename"] == "informe.txt"


# ── check_xss was not part of the decision ───────────────────────────────────

@pytest.mark.asyncio
async def test_xss_in_a_filename_is_still_refused(session_mgr, file_handler):
    """`allow_html=True` stops the ESCAPING, not the XSS detector.

    A `<script>` payload in a filename must still be refused with a 400, and
    nothing may reach the disk. This is the test that goes red if "stop
    escaping" is ever implemented as "stop checking".
    """
    with pytest.raises(HTTPException) as exc:
        await _attach(session_mgr, file_handler, XSS_NAME)

    assert exc.value.status_code == 400, exc.value.detail
    assert not [p for p in file_handler.upload_dir.rglob("*") if p.is_file()], (
        "a refused upload left a file on disk"
    )


@pytest.mark.asyncio
async def test_path_traversal_in_a_filename_is_still_refused(
    session_mgr, file_handler,
):
    """The other detector that matters for a path: it raises, as it always did."""
    with pytest.raises(HTTPException) as exc:
        await _attach(session_mgr, file_handler, "../../etc/passwd.txt")

    assert exc.value.status_code == 400, exc.value.detail
    assert not [p for p in file_handler.upload_dir.rglob("*") if p.is_file()]
