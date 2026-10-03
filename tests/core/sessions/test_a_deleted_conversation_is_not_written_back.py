"""Review 04/10: a background job (the image description, the compaction)
holds the session object for seconds — a compaction for up to ~100 s. A
conversation the user deleted meanwhile was written back to disk, and came
back after a restart. `save_session_if_live` writes only a session that is
still the manager's."""
from unittest.mock import MagicMock

from core.sessions.session_manager import SessionManager


def _files(manager, sid):
    return list(manager._storage_path.glob(f"*{sid}*"))


def test_a_live_session_is_saved(tmp_path):
    manager = SessionManager(storage_path=str(tmp_path), crypto_provider=None)
    session = manager.get_or_create_session("live-1")
    assert manager.save_session_if_live(session) is True
    assert _files(manager, "live-1")


def test_a_deleted_session_is_not_written_back(tmp_path):
    manager = SessionManager(storage_path=str(tmp_path), crypto_provider=None)
    session = manager.get_or_create_session("gone-1")
    manager.save_session_if_live(session)
    manager.delete_session("gone-1")
    assert manager.save_session_if_live(session) is False
    assert not _files(manager, "gone-1")


async def test_a_compaction_that_ends_after_the_delete_leaves_it_deleted(tmp_path, monkeypatch):
    from core.sessions import compactor

    manager = SessionManager(storage_path=str(tmp_path), crypto_provider=None)
    session = manager.get_or_create_session("gone-2")
    for i in range(30):
        session.add_message("user" if i % 2 == 0 else "assistant", f"missatge {i} " * 20)
    manager.save_session_if_live(session)

    class _OllamaSummariser:  # the compactor tells Ollama by the class name
        asked = False

        def chat(self, model, messages, stream=False, **_):
            self.asked = True
            manager.delete_session("gone-2")  # the user deletes it while the summary is written

            async def _gen():
                yield {"message": {"content": "Resum."}}
            return _gen()

    monkeypatch.setattr("core.context_window.ask_engine_window", lambda engine: 2048)
    monkeypatch.setattr(session, "needs_compaction", MagicMock(return_value=True))
    summariser = _OllamaSummariser()
    await compactor.compact_session(session, summariser, manager)
    assert summariser.asked, "the summary was asked for: the delete happened mid-compaction"
    assert manager.get_session("gone-2") is None
    assert not _files(manager, "gone-2")
