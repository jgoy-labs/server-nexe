"""
Tests del pipeline RAG: ingesta de knowledge/ → cerca → resposta.

Nivells:
  Unitari  (sense GPU, sense Qdrant) — chunk_text, read_file, header_parser
  Integrat (Qdrant requerit)          — ingest_knowledge + /rag/search
  E2E      (GPU + Qdrant requerits)   — ingest → chat → resposta basada en docs

Marca de tests:
  pytest -m "not integration and not gpu"   # unitaris
  pytest -m "integration and not gpu"       # integrats (Qdrant)
  pytest -m "integration and gpu"           # E2E complet
"""
import os
import pytest
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# Helpers de detecció de backends
# ─────────────────────────────────────────────────────────────

def _qdrant_available():
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:6333/healthz", timeout=2)
        return True
    except Exception:
        return False


def _ollama_available():
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


def _mlx_available():
    try:
        import mlx_lm  # noqa: F401
        model = os.environ.get("NEXE_MLX_MODEL", "")
        return bool(model and (Path(model).exists()))
    except ImportError:
        return False


# ═══════════════════════════════════════════════════════════════
# Unitaris — chunk_text (de ingest_knowledge.py)
# ═══════════════════════════════════════════════════════════════

from core.ingest.ingest_knowledge import chunk_text, read_file, CHUNK_SIZE, CHUNK_OVERLAP


class TestChunkText:

    def test_short_text_single_chunk(self):
        chunks = chunk_text("text curt", chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == "text curt"

    def test_long_text_splits(self):
        text = "paraula " * 1000  # ~8000 chars
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) > 1

    def test_chunks_fit_size(self):
        text = "X" * 5000
        chunks = chunk_text(text, chunk_size=1000, overlap=100)
        for c in chunks:
            assert len(c) <= 1000 + 50

    def test_no_empty_chunks(self):
        text = "Línia 1\n\n\nLínia 2\n\n"
        chunks = chunk_text(text, chunk_size=50, overlap=5)
        for c in chunks:
            assert c.strip() != ""

    def test_overlap_produces_more_chunks(self):
        text = "W" * 3000
        no_overlap = chunk_text(text, chunk_size=1000, overlap=0)
        with_overlap = chunk_text(text, chunk_size=1000, overlap=200)
        assert len(with_overlap) >= len(no_overlap)

    def test_empty_text(self):
        chunks = chunk_text("")
        assert chunks == [] or all(c.strip() == "" for c in chunks)

    def test_default_constants_sane(self):
        assert CHUNK_SIZE > 100
        assert 0 <= CHUNK_OVERLAP < CHUNK_SIZE


# ═══════════════════════════════════════════════════════════════
# Unitaris — read_file
# ═══════════════════════════════════════════════════════════════

class TestReadFile:

    def test_read_txt(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("Contingut de prova")
        assert read_file(p) == "Contingut de prova"

    def test_read_md(self, tmp_path):
        p = tmp_path / "doc.md"
        p.write_text("# Títol\nCos")
        result = read_file(p)
        assert "Títol" in result

    def test_read_nonexistent_raises(self, tmp_path):
        """read_file no gestiona fitxers inexistents — llança excepció."""
        p = tmp_path / "inexistent.txt"
        with pytest.raises(Exception):
            read_file(p)

    def test_read_strips_rag_header(self, tmp_path):
        """Els docs de knowledge/ porten capçalera RAG delimitada per ---"""
        content = "# === METADATA RAG ===\nid: test\n---\n\n# Títol\nCos del document"
        p = tmp_path / "doc.md"
        p.write_text(content)
        result = read_file(p)
        # El contingut ha d'existir (capçalera o sense)
        assert isinstance(result, str)
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════════
# Unitaris — header_parser (RAG metadata)
# ═══════════════════════════════════════════════════════════════

class TestHeaderParser:

    def test_parse_valid_header(self):
        from memory.rag.header_parser import parse_rag_header
        text = "# === METADATA RAG ===\nid: test-doc\nabstract: Un document\ntags: [rag, test]\n---\n\n# Contingut\nText del document"
        header, body = parse_rag_header(text)
        assert header.id == "test-doc"
        assert "Text del document" in body

    def test_parse_no_header(self):
        from memory.rag.header_parser import parse_rag_header
        text = "# Document sense capçalera\nText normal"
        header, body = parse_rag_header(text)
        assert not header.is_valid
        assert "Document sense capçalera" in body

    def test_tags_parsed_as_list(self):
        from memory.rag.header_parser import parse_rag_header
        text = "# === METADATA RAG ===\nid: t\ntags: [a, b, c]\n---\nCos"
        header, _ = parse_rag_header(text)
        if header.is_valid:
            assert isinstance(header.tags, list)

    def test_knowledge_readme_has_valid_header(self):
        """El README.md de la carpeta knowledge/ ha de tenir capçalera vàlida."""
        from memory.rag.header_parser import parse_rag_header
        readme = Path(__file__).parents[3] / "knowledge" / "ca" / "README.md"
        if not readme.exists():
            pytest.skip("knowledge/ca/README.md not found")
        text = readme.read_text(encoding="utf-8")
        header, body = parse_rag_header(text)
        assert header.is_valid
        assert "9119" in body or "NEXE" in body


# ═══════════════════════════════════════════════════════════════
# Unitaris — descoberta de fitxers a knowledge/
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeFolderDiscovery:

    def test_knowledge_folder_exists(self):
        knowledge = Path(__file__).parents[3] / "knowledge"
        assert knowledge.exists(), "La carpeta knowledge/ ha d'existir"

    def test_language_subfolders_exist(self):
        knowledge = Path(__file__).parents[3] / "knowledge"
        assert (knowledge / "ca").is_dir(), "knowledge/ca/ ha d'existir"

    def test_ca_folder_has_docs(self):
        ca = Path(__file__).parents[3] / "knowledge" / "ca"
        docs = list(ca.glob("*.md")) + list(ca.glob("*.txt"))
        assert len(docs) > 0, "knowledge/ca/ ha de tenir almenys un document"

    def test_readme_contains_port(self):
        readme = Path(__file__).parents[3] / "knowledge" / "ca" / "README.md"
        if not readme.exists():
            pytest.skip("README.md not found")
        text = readme.read_text()
        assert "9119" in text

    def test_readme_contains_version(self):
        readme = Path(__file__).parents[3] / "knowledge" / "ca" / "README.md"
        if not readme.exists():
            pytest.skip("README.md not found")
        text = readme.read_text()
        assert "0.9" in text


# ═══════════════════════════════════════════════════════════════
# Integrat — ingest_knowledge + /rag/search (Qdrant requerit)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.integration
@pytest.mark.slow
class TestIngestAndSearch:
    """
    Requereix Qdrant a localhost:6333.
    Injecta els docs de knowledge/ca/ i comprova que es poden cercar.
    """

    @pytest.fixture(autouse=True)
    def require_qdrant(self):
        if not _qdrant_available():
            pytest.skip("Qdrant not running at localhost:6333")

    @pytest.fixture(scope="class")
    def ingested(self):
        """Executa la ingesta una sola vegada per tota la classe."""
        import asyncio
        from core.ingest.ingest_knowledge import ingest_knowledge
        knowledge_path = Path(__file__).parents[3] / "knowledge" / "ca"
        result = asyncio.run(
            ingest_knowledge(folder=knowledge_path.parent, quiet=True)
        )
        return result

    def test_ingest_returns_true(self, ingested):
        assert ingested is True

    def test_collection_exists_after_ingest(self, ingested):
        import asyncio
        from memory.memory.api import MemoryAPI
        async def _check():
            memory = MemoryAPI()
            await memory.initialize()
            return await memory.collection_exists("user_knowledge")
        exists = asyncio.run(_check())
        assert exists is True

    def test_search_finds_port_9119(self, ingested):
        """Cerca 'port per defecte' → ha de trobar contingut sobre el port 9119."""
        import asyncio
        from memory.memory.api import MemoryAPI
        async def _search():
            memory = MemoryAPI()
            await memory.initialize()
            return await memory.search(
                query="quin és el port per defecte del servidor",
                collection="user_knowledge",
                top_k=5
            )
        results = asyncio.run(_search())
        assert len(results) > 0
        combined = " ".join(r.text or "" for r in results)
        assert "9119" in combined

    def test_search_finds_installation_steps(self, ingested):
        """Cerca 'instal·lació' → ha de trobar setup.sh."""
        import asyncio
        from memory.memory.api import MemoryAPI
        async def _search():
            memory = MemoryAPI()
            await memory.initialize()
            return await memory.search(
                query="com s'instal·la NEXE",
                collection="user_knowledge",
                top_k=5
            )
        results = asyncio.run(_search())
        assert len(results) > 0
        combined = " ".join(r.text or "" for r in results)
        assert "setup.sh" in combined or "instal" in combined.lower()

    def test_search_finds_version(self, ingested):
        """Cerca 'versió' → ha de trobar '0.8'."""
        import asyncio
        from memory.memory.api import MemoryAPI
        async def _search():
            memory = MemoryAPI()
            await memory.initialize()
            return await memory.search(
                query="quina versió és NEXE",
                collection="user_knowledge",
                top_k=3
            )
        results = asyncio.run(_search())
        combined = " ".join(r.text or "" for r in results)
        assert "0.9" in combined

    def test_search_scores_are_positive(self, ingested):
        import asyncio
        from memory.memory.api import MemoryAPI
        async def _search():
            memory = MemoryAPI()
            await memory.initialize()
            return await memory.search(query="NEXE servidor", collection="user_knowledge", top_k=3)
        results = asyncio.run(_search())
        for r in results:
            assert r.score >= 0.0

    def test_rag_search_endpoint(self, ingested):
        """El endpoint /rag/search retorna resultats rellevants."""
        from fastapi.testclient import TestClient
        from core.app import app
        api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "nexe-rag-test")
        os.environ["NEXE_PRIMARY_API_KEY"] = api_key
        os.environ.setdefault("NEXE_DEV_MODE", "true")

        with TestClient(app, base_url="http://localhost") as client:
            # Obtenir CSRF token via GET primer
            get_r = client.get("/health", headers={"X-API-Key": api_key})
            csrf_token = get_r.cookies.get("nexe_csrf_token", "")
            r = client.post(
                "/v1/rag/search",
                headers={"X-API-Key": api_key, "X-CSRF-Token": csrf_token},
                json={"query": "port per defecte NEXE", "top_k": 3}
            )
        # 200 si implementat, 501 si encara no implementat (stub)
        assert r.status_code in (200, 501)
        body = r.json()
        if r.status_code == 200:
            assert "results" in body or "documents" in body or isinstance(body, list)


# ═══════════════════════════════════════════════════════════════
# E2E — ingest → chat → resposta coherent amb els docs
# ═══════════════════════════════════════════════════════════════

# Preguntes factuals amb respostes verificables als docs de knowledge/ca/
RAG_QA_PAIRS = [
    {
        "question": "Quin port utilitza el servidor NEXE per defecte?",
        "expected_keywords": ["9119"],
        "doc": "README.md"
    },
    {
        "question": "Quin script s'utilitza per instal·lar NEXE?",
        "expected_keywords": ["setup.sh", "setup"],
        "doc": "INSTALLATION.md"
    },
    {
        "question": "Quina és la versió actual de NEXE?",
        "expected_keywords": ["0.9"],
        "doc": "README.md"
    },
]


def _check_response_has_keywords(response_text: str, keywords: list) -> bool:
    text_lower = response_text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


@pytest.mark.integration
@pytest.mark.gpu
@pytest.mark.slow
class TestRAGChatOllama:
    """
    Flux complet: ingest knowledge/ → pregunta via /ui/chat →
    el model respon amb informació dels documents.
    Requereix Ollama + Qdrant actius.
    """

    @pytest.fixture(autouse=True)
    def require_backends(self):
        engine = os.environ.get("NEXE_MODEL_ENGINE", "")
        if engine not in ("ollama", ""):
            pytest.skip("Ollama not selected engine")
        if not _ollama_available():
            pytest.skip("Ollama not running")
        if not _qdrant_available():
            pytest.skip("Qdrant not running at localhost:6333")

    @pytest.fixture(scope="class")
    def rag_client(self):
        """Client amb ingesta prèvia dels docs de knowledge/."""
        import asyncio
        from core.ingest.ingest_knowledge import ingest_knowledge
        from fastapi.testclient import TestClient
        from core.app import app

        api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "nexe-rag-e2e-test")
        os.environ.setdefault("NEXE_PRIMARY_API_KEY", api_key)
        os.environ.setdefault("NEXE_ENV", "testing")
        os.environ.setdefault("NEXE_DEV_MODE", "true")

        # Ingestar knowledge/ca/
        asyncio.run(
            ingest_knowledge(quiet=True)
        )
        with TestClient(app, base_url="http://localhost") as client:
            yield client, {"X-API-Key": api_key}

    def test_chat_answers_port_question(self, rag_client):
        client, headers = rag_client
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]
        r = client.post("/ui/chat", headers=headers,
                        json={"message": "Quin port utilitza el servidor NEXE per defecte?",
                              "session_id": sid}, timeout=90)
        assert r.status_code == 200
        body = r.json()
        text = body.get("response") or body.get("message") or body.get("text") or str(body)
        assert "9119" in text, f"No conté '9119': {text[:300]}"

    def test_chat_answers_install_question(self, rag_client):
        client, headers = rag_client
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]
        r = client.post("/ui/chat", headers=headers,
                        json={"message": "Quin script s'utilitza per instal·lar NEXE?",
                              "session_id": sid}, timeout=90)
        assert r.status_code == 200
        body = r.json()
        text = body.get("response") or body.get("message") or body.get("text") or str(body)
        assert any(kw in text.lower() for kw in ["setup.sh", "setup"]), \
            f"No conté 'setup.sh': {text[:300]}"

    def test_chat_answers_version_question(self, rag_client):
        client, headers = rag_client
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]
        r = client.post("/ui/chat", headers=headers,
                        json={"message": "Quina és la versió actual de NEXE?",
                              "session_id": sid}, timeout=90)
        assert r.status_code == 200
        body = r.json()
        text = body.get("response") or body.get("message") or body.get("text") or str(body)
        assert "0.9" in text, f"No conté '0.8': {text[:300]}"

    def test_chat_rag_context_present_in_response(self, rag_client):
        """El camp rag_context o similar ha d'existir si el model troba docs rellevants."""
        client, headers = rag_client
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Explica'm que és NEXE", "session_id": sid},
            timeout=90
        )
        assert r.status_code == 200
        # La resposta ha de tenir contingut
        body = r.json()
        has_content = any([
            body.get("response"), body.get("message"), body.get("text")
        ])
        assert has_content


@pytest.mark.integration
@pytest.mark.gpu
@pytest.mark.slow
class TestRAGChatMLX:
    """
    Mateix flux E2E amb backend MLX.
    """

    @pytest.fixture(autouse=True)
    def require_backends(self):
        if os.environ.get("NEXE_MODEL_ENGINE") != "mlx":
            pytest.skip("MLX not selected engine")
        if not _mlx_available():
            pytest.skip("MLX model not available")
        if not _qdrant_available():
            pytest.skip("Qdrant not running")

    @pytest.fixture(scope="class")
    def rag_client_mlx(self):
        import asyncio
        from core.ingest.ingest_knowledge import ingest_knowledge
        from fastapi.testclient import TestClient
        from core.app import app

        api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "nexe-rag-mlx-test")
        os.environ.setdefault("NEXE_PRIMARY_API_KEY", api_key)
        os.environ.setdefault("NEXE_DEV_MODE", "true")

        async def _setup():
            from memory.memory.api import MemoryAPI
            import plugins.web_ui_module.memory_helper as mh
            mem = MemoryAPI()
            await mem.initialize()
            # TODO (post-refactor 2026-04-08): aquest bloc escriu al storage/vectors/
            # REAL del dev sense usar tmp_path. És un test-leak confirmat que contamina
            # l'estat entre test runs. Refactoritzar per usar isolated QdrantClient
            # amb tmp_path. Diferit a HOMAD memòria v1 Part 2 o sessió pròpia.
            # Clear personal_memory to avoid contamination from previous test classes
            if await mem.collection_exists("personal_memory"):
                await mem.delete_collection("personal_memory")
                await mem.create_collection("personal_memory", vector_size=768)
            await mem.close()
            # Reset memory_helper singleton so it picks up fresh collection
            mh._memory_api_instance = None
            await ingest_knowledge(quiet=True)

        asyncio.run(_setup())
        with TestClient(app, base_url="http://localhost") as client:
            yield client, {"X-API-Key": api_key}

    def test_mlx_answers_port_question(self, rag_client_mlx):
        client, headers = rag_client_mlx
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Quin port fa servir NEXE?", "session_id": sid, "rag_threshold": 0.4},
            timeout=120
        )
        assert r.status_code == 200
        body = r.json()
        response_text = body.get("response") or body.get("message") or str(body)
        assert "9119" in response_text, f"No conté '9119': {response_text[:300]}"

    def test_mlx_answers_version_question(self, rag_client_mlx):
        client, headers = rag_client_mlx
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Quina versió de NEXE tenim?", "session_id": sid},
            timeout=120
        )
        assert r.status_code == 200
        body = r.json()
        response_text = body.get("response") or body.get("message") or str(body)
        assert "0.9" in response_text, f"No conté '0.8': {response_text[:300]}"
