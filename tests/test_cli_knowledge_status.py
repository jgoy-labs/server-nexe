"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: tests/test_cli_knowledge_status.py
Description: B108 — `nexe knowledge status` ha de mirar la col·lecció on l'ingest
escriu (DOCUMENTATION_COLLECTION='nexe_documentation'), no 'user_knowledge'.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from unittest.mock import patch, AsyncMock

from click.testing import CliRunner

from core.cli.cli import app


class TestKnowledgeStatusCollection:
    """B108 — el status mira la col·lecció real de l'ingest."""

    def _mock_memory(self, existing_collection: str, count: int = 7):
        """MemoryAPI on només `existing_collection` existeix."""
        mem = AsyncMock()
        mem.initialize = AsyncMock(return_value=True)
        mem.close = AsyncMock()

        async def _exists(name):
            return name == existing_collection
        mem.collection_exists = AsyncMock(side_effect=_exists)

        async def _count(collection):
            return count if collection == existing_collection else 0
        mem.count = AsyncMock(side_effect=_count)
        return mem

    def test_status_reports_active_when_documentation_collection_exists(self):
        """Amb 'nexe_documentation' poblada (i 'user_knowledge' inexistent),
        el status ha de dir Active i mostrar el count — no 'does not exist'."""
        from core.ingest.ingest_knowledge import DOCUMENTATION_COLLECTION
        mem = self._mock_memory(existing_collection=DOCUMENTATION_COLLECTION, count=7)
        runner = CliRunner()

        with patch("memory.memory.api.MemoryAPI", return_value=mem):
            result = runner.invoke(app, ["knowledge", "status"])

        assert result.exit_code == 0, result.output
        checked = [c.args[0] for c in mem.collection_exists.call_args_list]
        assert DOCUMENTATION_COLLECTION in checked, (
            f"status no ha comprovat {DOCUMENTATION_COLLECTION!r}; ha comprovat {checked!r}"
        )
        assert "does not exist" not in result.output, result.output
        assert "✅" in result.output and "7" in result.output, result.output

    def test_status_does_not_check_only_user_knowledge(self):
        """Mutació-resistent: el count s'ha de fer sobre la col·lecció que SÍ existeix."""
        from core.ingest.ingest_knowledge import DOCUMENTATION_COLLECTION
        mem = self._mock_memory(existing_collection=DOCUMENTATION_COLLECTION, count=3)
        runner = CliRunner()

        with patch("memory.memory.api.MemoryAPI", return_value=mem):
            result = runner.invoke(app, ["knowledge", "status"])

        assert result.exit_code == 0, result.output
        counted = [c.args[0] for c in mem.count.call_args_list]
        assert counted == [DOCUMENTATION_COLLECTION], (
            f"count s'ha fet sobre {counted!r}, esperat [{DOCUMENTATION_COLLECTION!r}]"
        )
