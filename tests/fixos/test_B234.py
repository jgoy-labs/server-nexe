"""
Test fix B234: Ingest mega-batch reporta chunks CONSTRUITS, no els EMMAGATZEMATS.
El resum és mentider en cas de fallada parcial d'emmagatzematge.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


async def _make_mock_memory(fail_on_store=False, fail_on_batch=False):
    """Crea un mock de memory que pot simular fallades parcials."""
    memory = MagicMock()
    memory.close = AsyncMock()
    memory.get_perf_snapshot = MagicMock(return_value=None)

    if fail_on_batch:
        memory.store_batch = AsyncMock(side_effect=Exception("Qdrant error: timeout"))
        if fail_on_store:
            memory.store = AsyncMock(side_effect=Exception("store also failed"))
        else:
            memory.store = AsyncMock(return_value=None)
    else:
        memory.store_batch = AsyncMock(return_value=None)
        memory.store = AsyncMock(return_value=None)

    return memory


def test_flush_mega_batch_returns_stored_count_on_success():
    """
    _flush_mega_batch ha de retornar el nombre de chunks emmagatzemats correctament.
    En cas d'èxit total, ha de retornar len(items).
    """
    from core.ingest.ingest_knowledge import _flush_mega_batch

    async def _run():
        memory = await _make_mock_memory(fail_on_batch=False)
        items_a = [{"text": f"text_{i}", "metadata": {}} for i in range(3)]
        items_b = [{"text": f"text_b_{i}", "metadata": {}} for i in range(2)]
        mega = {"col_a": items_a, "col_b": items_b}
        log_messages = []
        stored = await _flush_mega_batch(memory, mega, log_messages.append)
        return stored

    stored = asyncio.run(_run())
    # En èxit total: stored = 3 + 2 = 5
    assert stored == 5, (
        f"_flush_mega_batch ha de retornar 5 (tots emmagatzemats), però va retornar {stored}"
    )


def test_flush_mega_batch_returns_partial_count_on_failure():
    """
    En fallada parcial (store_batch falla, store individual falla per alguns),
    _flush_mega_batch ha de retornar el recompte real d'items emmagatzemats.
    """
    from core.ingest.ingest_knowledge import _flush_mega_batch

    async def _run():
        memory = await _make_mock_memory(fail_on_batch=True, fail_on_store=True)
        # 3 items, tots fal·laran
        items = [{"text": f"text_{i}", "metadata": {}} for i in range(3)]
        mega = {"col_a": items}
        log_messages = []
        stored = await _flush_mega_batch(memory, mega, log_messages.append)
        return stored, log_messages

    stored, logs = asyncio.run(_run())
    # No item stored: stored must be 0
    assert stored == 0, (
        f"En fallada total ha de retornar 0 items emmagatzemats, però va retornar {stored}"
    )


def test_flush_mega_batch_partial_store_success():
    """
    On batch failure but individual success, it must count the individually stored items.
    """
    from core.ingest.ingest_knowledge import _flush_mega_batch

    async def _run():
        memory = MagicMock()
        memory.close = AsyncMock()
        # store_batch fails, but individual store succeeds for 2 of 3
        store_call_count = [0]

        async def store_individual(**kwargs):
            store_call_count[0] += 1
            if store_call_count[0] == 2:
                raise Exception("item 2 falla")

        memory.store_batch = AsyncMock(side_effect=Exception("batch fail"))
        memory.store = AsyncMock(side_effect=store_individual)

        items = [{"text": f"text_{i}", "metadata": {}} for i in range(3)]
        mega = {"col_a": items}
        log_messages = []
        stored = await _flush_mega_batch(memory, mega, log_messages.append)
        return stored

    stored = asyncio.run(_run())
    # 2 de 3 emmagatzemats
    assert stored == 2, (
        f"Amb 2 de 3 items emmagatzemats, stored ha de ser 2, però va retornar {stored}"
    )
