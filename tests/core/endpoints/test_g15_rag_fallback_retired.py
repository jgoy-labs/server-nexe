"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/endpoints/test_g15_rag_fallback_retired.py
Description: #899 — `_rag_module_fallback` era un camí estructuralment buit
             (ADR-002:68 / B114): el RAG legacy (PersonalityRAG) va quedar
             superat per MemoryAPI/Qdrant i la seva cerca ja no torna mai res.
             Es retira. El que NO pot passar en retirar-lo és que l'`except` on
             queia es quedi MUT: quan MemoryAPI no va, el torn es respon sense
             context, i això s'ha de sentir al log — que és precisament el que
             B114 va anar a buscar quan va pujar aquell buit a WARNING.

             Gate: (a) MemoryAPI que cau → context buit i WARNING audible;
             (b) el camí legacy no torna per cap porta a `chat_rag`.
             Mutació que l'ha de matar: reintroduir `_rag_module_fallback` i la
             seva crida → el WARNING nou desapareix i (a) es posa vermell.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints import chat_rag


@pytest.mark.asyncio
class TestG15NoSilentRagDegradation:

    async def test_memory_api_down_is_audible_and_returns_no_context(self, caplog):
        """#899: sense MemoryAPI no hi ha context — i s'ha de sentir."""
        with patch("memory.memory.api.v1.get_memory_api",
                   new=AsyncMock(side_effect=RuntimeError("api down"))):
            with caplog.at_level(logging.WARNING, logger="core.endpoints.chat_rag"):
                result, _rag_items = await chat_rag.build_rag_context("hola", MagicMock(), "ca")

        assert result == ""
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, (
            "#899: MemoryAPI ha caigut i el torn s'ha respost sense context "
            "sense dir-ho enlloc — l'except s'ha quedat mut (B114 al revés)"
        )
        assert any("context" in r.getMessage().lower() for r in warnings), (
            f"el WARNING no diu que es continua sense context: "
            f"{[r.getMessage() for r in warnings]}"
        )

    async def test_a_healthy_memory_api_says_nothing(self):
        """Control invers: el WARNING només surt quan hi ha degradació.
        Sense això, el gate passaria igual amb un warning incondicional."""
        memory = MagicMock()
        memory.embed_query = AsyncMock(return_value=[0.0])
        # `collection_exists` ha de ser awaitable de debò: si es deixa MagicMock,
        # `_search_collection` peta i emet el seu propi WARNING (MC-017), que no
        # és el que aquest control mira — i el test passaria per la raó dolenta.
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=[])

        with patch("memory.memory.api.v1.get_memory_api",
                   new=AsyncMock(return_value=memory)):
            with patch.object(chat_rag.logger, "warning") as warned:
                result, _rag_items = await chat_rag.build_rag_context("hola", MagicMock(), "ca")

        assert result == ""
        assert not warned.called, (
            "amb MemoryAPI sana no hi ha degradació que anunciar"
        )


class TestG15LegacyRagPathIsGone:
    """El camí legacy no pot tornar per cap porta d'aquest mòdul."""

    def test_no_fallback_helper_survives(self):
        survivors = [n for n in dir(chat_rag) if "fallback" in n.lower()]
        assert not survivors, (
            f"#899: el camí de fallback legacy ha tornat a chat_rag: {survivors}"
        )

    def test_the_module_does_not_reach_for_the_legacy_rag_sources(self):
        """Descoberta, no llista: qualsevol via cap a `memory.rag_sources` o cap
        a `app_state.modules['rag']` dins d'aquest fitxer torna a obrir-lo."""
        from pathlib import Path
        src = Path(chat_rag.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        )
        for needle in ("memory.rag_sources", "modules.get('rag')", 'modules.get("rag")'):
            assert needle not in code, (
                f"#899: `{needle}` ha tornat a core/endpoints/chat_rag.py — "
                "el RAG legacy està retirat (ADR-002:68)"
            )
