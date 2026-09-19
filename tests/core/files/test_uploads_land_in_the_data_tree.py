"""Uploads are user data: they live in the data tree, filed by date (#1065).

They used to be written to `plugins/web_ui_module/ui/uploads`, inside the
plugin's own code tree. The packaged app extracts that tree fresh on every
version, and uploads survived an update only by an accident of how `tar`
unpacks — nothing in the code guaranteed it, and nothing said so. The data
tree (`get_data_dir`, which resolves to `NEXE_DATA_DIR` in sidecar mode) is
the one place that exists precisely to be segregated from updates.

Two things are pinned here:

* **the layout** — `<root>/<year>/<yyyymmdd>/<name>`, a year folder so the root
  does not grow without bound and one folder per day named with the whole date,
  so it means something when read on its own;
* **the listing and the cleanup follow** — they used to `iterdir()` a flat
  directory, which after the move would have reported every upload as missing
  while the files sat one level down.

The half of this change that protects something is in
`tests/plugins/web_ui_module/test_static_uploads_guard.py`: the unauthenticated
static route must keep refusing the OLD path too, because a document left there
by an install from before the move is still a document.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core.files.handler import FileHandler


@pytest.fixture()
def handler(tmp_path):
    return FileHandler(tmp_path / "uploads")


@pytest.mark.asyncio
async def test_an_upload_is_filed_under_year_and_day(handler):
    """Mutation: write to `self.upload_dir` directly in `save_file` and the
    two `parts` assertions below go red."""
    today = datetime.now()
    path = await handler.save_file("informe.txt", b"contingut")

    assert path.name == "informe.txt"
    assert path.parent.name == today.strftime("%Y%m%d"), path
    assert path.parent.parent.name == today.strftime("%Y"), path
    assert path.parent.parent.parent == handler.upload_dir, path


@pytest.mark.asyncio
async def test_two_files_with_the_same_name_still_do_not_overwrite(handler):
    """The anti-overwrite counter has to keep working inside the dated folder."""
    first = await handler.save_file("informe.txt", b"un")
    second = await handler.save_file("informe.txt", b"dos")

    assert first != second
    assert first.read_bytes() == b"un"
    assert second.read_bytes() == b"dos"
    assert second.parent == first.parent, "the second landed in another folder"


@pytest.mark.asyncio
async def test_the_listing_walks_the_dated_folders(handler):
    """`get_uploaded_files` listed a flat directory; after the move that would
    have reported an empty upload area with the files one level down."""
    await handler.save_file("informe.txt", b"contingut")

    listed = handler.get_uploaded_files()

    assert [f["filename"] for f in listed] == ["informe.txt"], listed


@pytest.mark.asyncio
async def test_the_cleanup_walks_the_dated_folders(handler):
    """Same for the cleanup: a file it cannot see is a file it never deletes,
    and the uploads would have grown for ever."""
    path = await handler.save_file("vell.txt", b"contingut")
    import os
    old = datetime.now().timestamp() - (48 * 3600)
    os.utime(path, (old, old))

    deleted = handler.cleanup_old_files(max_age_hours=24)

    assert deleted == 1, "the cleanup did not reach inside the dated folder"
    assert not path.exists()


@pytest.mark.asyncio
async def test_a_file_left_in_the_flat_root_is_still_seen(handler):
    """An install from before the move has files sitting in the root itself.
    The listing and the cleanup must still find them, or they become
    invisible AND undeletable."""
    stray = handler.upload_dir / "antic.txt"
    stray.write_bytes(b"d'abans de la mudanca")

    assert "antic.txt" in [f["filename"] for f in handler.get_uploaded_files()]


@pytest.mark.asyncio
async def test_two_uploads_with_one_name_on_different_days_are_tellable_apart(handler):
    """Regression found reviewing this very change (#1065).

    The flat layout made `filename` unique by itself: `save_file` appends `_1`
    on a clash. That uniqueness is per FOLDER, and folders are per day now — so
    `informe.txt` uploaded today and `informe.txt` uploaded next month are two
    different files sharing one name, and the listing showed two identical rows
    with nothing to separate them.

    Mutation: drop the `day` key from `get_uploaded_files` and this goes red.
    """
    old = handler.upload_dir / "2026" / "20260101"
    old.mkdir(parents=True)
    (old / "informe.txt").write_bytes(b"el de gener")
    await handler.save_file("informe.txt", b"el d'avui")

    listed = handler.get_uploaded_files()

    assert len(listed) == 2, listed
    assert {f["filename"] for f in listed} == {"informe.txt"}, "premissa del test"
    days = {f["day"] for f in listed}
    assert len(days) == 2, f"les dues files son indistingibles: {listed}"
    assert "20260101" in days


@pytest.mark.asyncio
async def test_a_file_in_the_flat_root_reports_no_day(handler):
    """An upload from before the move sits in the root and belongs to no day.
    It must say so, not borrow the root's name."""
    (handler.upload_dir / "antic.txt").write_bytes(b"d'abans")

    listed = handler.get_uploaded_files()

    assert [f["day"] for f in listed] == [""]


@pytest.mark.asyncio
async def test_the_cleanup_does_not_leave_the_dated_folders_behind(handler):
    """Otherwise the tree keeps one empty folder per day for ever, and the
    layout stops being the tidy thing it was introduced to be."""
    import os
    path = await handler.save_file("vell.txt", b"contingut")
    old = datetime.now().timestamp() - (48 * 3600)
    os.utime(path, (old, old))

    handler.cleanup_old_files(max_age_hours=24)

    leftover = [p for p in handler.upload_dir.rglob("*") if p.is_dir()]
    assert not leftover, f"carpetes buides abandonades: {leftover}"
    assert handler.upload_dir.exists(), "l'arrel no s'ha de tocar mai"
