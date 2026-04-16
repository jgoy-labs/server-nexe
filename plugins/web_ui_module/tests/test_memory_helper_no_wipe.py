"""
Tests per plugins/web_ui_module/core/memory_helper.py — Fix bug #19a.

Objectiu: garantir que el singleton init de MemoryAPI MAI crida
delete_collection() sobre `personal_memory` ni `user_knowledge`,
eliminant el wipe silenciós que perdia memòries de l'usuari.

Decisió arquitectònica (aprovada per Jordi):
"`DEFAULT_VECTOR_SIZE` sempre ha de ser 768. Si mai hi ha mismatch
real (corrupció, bug qdrant_client), fallar al upsert és acceptable;
esborrar dades silenciosament NO ho és."
"""

import inspect
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.web_ui_module.core import memory_helper


class TestNoSilentWipeInSingletonInit:

    def test_get_memory_api_source_has_no_delete_collection(self):
        """Verificació estàtica: dins get_memory_api() NO pot haver-hi
        cap referència a delete_collection. Aquest test protegeix la
        decisió arquitectònica contra regressions futures."""
        src = inspect.getsource(memory_helper.MemoryHelper.get_memory_api)
        assert "delete_collection" not in src, (
            "REGRESSIÓ: get_memory_api() torna a contenir delete_collection. "
            "Decisió arquitectònica: personal_memory NO es pot esborrar al "
            "singleton init. Si cal verificar dims, log ERROR i propagar, "
            "MAI delete+recreate."
        )

    def test_get_memory_api_has_no_dim_mismatch_recreate_pattern(self):
        """Protecció contra patró de codi defensiu que recrea col·leccions
        si la dimensió no coincideix. Aquest patró = bomba de rellotgeria."""
        src = inspect.getsource(memory_helper.MemoryHelper.get_memory_api)
        # Patró: if dim ... != DEFAULT_VECTOR_SIZE ... delete_collection
        assert not re.search(
            r"dim\s*[!=].*DEFAULT_VECTOR_SIZE.*\n.*delete_collection",
            src,
            re.DOTALL,
        ), "Patró dim-check-delete detectat dins get_memory_api"


class TestExistingCollectionsArePreserved:

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset del singleton per aïllar tests."""
        memory_helper._memory_api_instance = None
        memory_helper._memory_api_init_failed = False
        yield
        memory_helper._memory_api_instance = None
        memory_helper._memory_api_init_failed = False

    @pytest.mark.asyncio
    async def test_existing_collection_not_deleted_on_init(self):
        """Si `personal_memory` existeix amb qualsevol dimensió (inclús una
        que teòricament no coincideix amb DEFAULT_VECTOR_SIZE), el init
        NO l'ha d'esborrar."""
        mock_api = AsyncMock()
        mock_api.collection_exists = AsyncMock(return_value=True)
        mock_api.delete_collection = AsyncMock()
        mock_api.create_collection = AsyncMock()

        # Qdrant retorna dim anòmala — el fix ha d'ignorar-la
        fake_qdrant = MagicMock()
        fake_qdrant.get_collection.return_value.config.params.vectors.size = 999
        mock_api._qdrant = fake_qdrant

        # Mock el reuse de v1 singleton per forçar el path de creació
        with patch(
            "memory.memory.api.v1.get_memory_api",
            side_effect=RuntimeError("skip v1"),
        ), patch("memory.memory.api.MemoryAPI", return_value=mock_api):
            helper = memory_helper.MemoryHelper()
            api = await helper.get_memory_api()

        assert api is mock_api
        assert not mock_api.delete_collection.called, (
            "delete_collection NO s'hauria d'haver cridat mai al init"
        )
        # create_collection tampoc (col·lecció ja existia)
        assert not mock_api.create_collection.called

    @pytest.mark.asyncio
    async def test_missing_collection_is_created(self):
        """Si `personal_memory` NO existeix, s'ha de crear (comportament
        original preservat)."""
        mock_api = AsyncMock()
        mock_api.collection_exists = AsyncMock(return_value=False)
        mock_api.delete_collection = AsyncMock()
        mock_api.create_collection = AsyncMock()

        with patch(
            "memory.memory.api.v1.get_memory_api",
            side_effect=RuntimeError("skip v1"),
        ), patch("memory.memory.api.MemoryAPI", return_value=mock_api):
            helper = memory_helper.MemoryHelper()
            await helper.get_memory_api()

        assert not mock_api.delete_collection.called
        # create_collection cridat per cada una de les 2 col·leccions
        assert mock_api.create_collection.call_count >= 1
