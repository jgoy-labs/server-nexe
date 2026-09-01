"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/test_897_forget_everything.py
Description: #897 — "clear all memory" told the user «ja no recordo res sobre
            tu» while only the Qdrant RAG collection was dropped. Writes through
            MemoryService (CLI, /memory/store, workflow nodes) live in
            memory_v1.db, so what survived was precisely what had really been
            stored: profile facts, episodes and staging rows.

            Decision (Jordi, 26/08/2026): erase everything, so the sentence
            becomes true.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from memory.memory.memory_service import MemoryService


@pytest.fixture
def svc(tmp_path):
    return MemoryService(db_path=tmp_path / "m.db", qdrant_path=None)


async def _remember_two(svc):
    await svc.initialize()
    await svc.remember(
        user_id="default", text="El meu gos es diu Bocs.",
        source="chat_interaction", trust_level="untrusted", force=True,
    )
    await svc.remember(
        user_id="default", text="Visc a Barcelona.",
        source="chat_interaction", trust_level="untrusted", force=True,
    )


class TestForgetEverything:
    @pytest.mark.asyncio
    async def test_every_user_scoped_store_is_emptied(self, svc):
        await _remember_two(svc)
        before = await svc.stats("default")
        assert before.profile_count and before.episodic_count and before.staging_count, (
            "the fixture must actually store something, or this test proves nothing"
        )

        await svc.forget_everything("default")

        after = await svc.stats("default")
        assert (after.profile_count, after.episodic_count, after.staging_count) == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_recall_returns_nothing_afterwards(self, svc):
        """The user-visible claim: «ja no recordo res sobre tu»."""
        await _remember_two(svc)
        assert await svc.recall(user_id="default", query="gos")

        await svc.forget_everything("default")

        assert await svc.recall(user_id="default", query="gos") == []
        assert await svc.recall(user_id="default", query="Barcelona") == []

    @pytest.mark.asyncio
    async def test_no_tombstone_is_left_behind(self, svc):
        """A tombstone of a full wipe would be a record of what we were told to
        forget. `forget()` leaves one by design; `forget_everything` must not."""
        await _remember_two(svc)
        await svc.forget_everything("default")
        assert (await svc.stats("default")).tombstone_count == 0

    @pytest.mark.asyncio
    async def test_profile_history_does_not_outlive_the_profile(self, svc):
        """profile_history has no user_id and is reachable only through
        profile_id, and its FK has NO ON DELETE CASCADE — so it must be deleted
        explicitly, and BEFORE the profile rows it points at.

        It only gets written when an attribute is UPDATED, so the value is
        overwritten here on purpose: `remember()` alone leaves this table empty
        and the assertion would be 0 == 0, proving nothing.
        """
        await svc.initialize()
        svc._store.upsert_profile(user_id="default", attribute="ciutat", value="Girona")
        svc._store.upsert_profile(user_id="default", attribute="ciutat", value="Barcelona")

        conn = svc._store._connect()
        assert conn.execute("SELECT COUNT(*) FROM profile_history").fetchone()[0] > 0, (
            "the fixture must really create history, or this test is theatre"
        )

        report = await svc.forget_everything("default")

        assert report["profile_history"] > 0, "the wipe must report what it removed"
        left = conn.execute(
            "SELECT COUNT(*) FROM profile_history"
        ).fetchone()[0]
        assert left == 0, "the user's old values must not survive on disk"

    @pytest.mark.asyncio
    async def test_another_user_is_untouched(self, svc):
        """The wipe is scoped: it must not become a global reset."""
        await svc.initialize()
        await svc.remember(user_id="default", text="Sóc en Jordi.",
                           source="chat_interaction", force=True)
        await svc.remember(user_id="altre", text="Sóc una altra persona.",
                           source="chat_interaction", force=True)

        await svc.forget_everything("default")

        assert (await svc.stats("default")).profile_count == 0
        other = await svc.stats("altre")
        assert other.profile_count + other.episodic_count + other.staging_count > 0

    @pytest.mark.asyncio
    async def test_a_broken_vector_index_still_wipes_the_readable_copy(self, svc, monkeypatch):
        """A partial forget must still remove what a recall can read, and say so."""
        await _remember_two(svc)

        class Boom:
            def delete(self, ids):
                raise RuntimeError("qdrant down")

        monkeypatch.setattr(svc, "_vector_index", Boom())
        report = await svc.forget_everything("default")

        assert report["vectors"] == -1, "the caller must be able to see what did not go"
        assert (await svc.stats("default")).profile_count == 0

    @pytest.mark.asyncio
    async def test_wiping_an_empty_store_is_harmless(self, svc):
        await svc.initialize()
        report = await svc.forget_everything("default")
        assert all(count == 0 for key, count in report.items() if key != "vectors")
