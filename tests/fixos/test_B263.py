"""
Test fix B263 (finding #851): la regla de seguretat RAG condicional partia el
namespace del trie de la caché de prefix.

El sufix `rag_security_rule` només s'afegia al system quan el torn portava
context (`if _ctx_injected`), i a la ruta OpenAI dins la injecció mateixa.
`compute_system_hash` cobreix el system SENCER → torns amb/sense RAG de la
MATEIXA sessió tenien identity_hash diferent → 2 nodes de trie a MLX i, a
llama.cpp, `_destroy` + recàrrega del GGUF (model_pool decideix només pel
hash). La branca `continue` forçava `_ctx_injected=False` → un continue d'un
torn amb RAG també queia fora del prefix acabat de construir.

Fix: la regla és ESTÀTICA (chat_sanitization.py:206 ja ho argumentava) i ara
INCONDICIONAL a les DUES rutes via el helper compartit
`append_rag_security_rule` — el cost fix de ~400 chars és el preu d'un
namespace de caché estable.
"""
import inspect
import re

import pytest

import core.endpoints.chat as openai_chat
import plugins.web_ui_module.api.routes_chat as rc
from core.endpoints.chat_sanitization import (
    _RAG_SECURITY_RULE,
    append_rag_security_rule,
    rag_security_rule,
)
from core.utils import compute_system_hash


class TestSharedHelper:
    def test_appends_localised_rule(self):
        for lang in ("ca", "es", "en"):
            out = append_rag_security_rule("BASE", lang)
            assert out.startswith("BASE")
            assert out.endswith(_RAG_SECURITY_RULE[lang])

    def test_unknown_lang_falls_back_to_english(self):
        assert append_rag_security_rule("BASE", "fr").endswith(_RAG_SECURITY_RULE["en"])

    def test_idempotent_shape(self):
        """El helper separa amb \\n\\n exactament com feia el codi inline."""
        assert append_rag_security_rule("BASE", "ca") == "BASE\n\n" + rag_security_rule("ca")


class TestWebUiUnconditional:
    def test_finalize_always_arms_the_rule(self):
        out = rc._finalize_system_prompt("BASE", "ca")
        assert _RAG_SECURITY_RULE["ca"] in out

    def test_finalize_with_collections_keeps_rule_last(self):
        out = rc._finalize_system_prompt("BASE", "ca", rag_collections=None)
        assert out.endswith(_RAG_SECURITY_RULE["ca"])

    def test_tripwire_no_conditional_rule_in_handler(self):
        """Contra HEAD: el handler feia `if _ctx_injected: system_prompt +=
        rag_security_rule(...)`. Cap resta d'aquest patró pot sobreviure."""
        src = inspect.getsource(rc)
        assert not re.search(
            r"if _ctx_injected:\s*\n\s*system_prompt", src
        ), "la regla RAG torna a ser condicional (#851 reobert)"
        # I la regla s'arma via el helper compartit (paritat entre rutes).
        assert "append_rag_security_rule" in src


def _capturing_engine():
    """Fake engine in-process que captura el system de cada torn."""

    class _Eng:
        def __init__(self):
            self.systems = []

        async def chat(self, messages, system="", session_id="default",
                       stream_callback=None, **kwargs):
            self.systems.append(system)
            if callable(stream_callback):
                stream_callback("ok")
            return {
                "response": "ok", "tokens": 1, "prompt_tokens": 0,
                "context_used": 0, "tokens_per_second": 0.0, "system_tokens": 0,
                "elapsed_ms": 1, "model_used": "fake", "session_id": session_id,
                "cache_hit": False, "timing": {},
            }

        async def is_model_loaded(self, model_name):
            return True

    return _Eng()


@pytest.mark.asyncio
class TestWebUiHandlerEndToEnd:
    """FLAGSHIP #851 (reescrit per la review: la versió anterior era
    tautològica): el HANDLER real, executat amb i sense context RAG, ha de
    produir el MATEIX system (armat amb la regla) — el hash és la unitat que
    decideix el trie MLX i el _destroy de llama.cpp."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limiter(self):
        """Mateix guard que test_chat_inner_behavior: sense això, el handler
        real tomba amb RateLimitExceeded quan corre en batch."""
        from core.dependencies import limiter

        original = limiter.enabled
        limiter.enabled = False
        yield
        limiter.enabled = original

    async def _run_turn(self, harness, state, body, rag_context=""):
        from unittest.mock import patch as _patch
        from tests.plugins.web_ui_module.test_chat_inner_behavior import _drain

        async def _fake_rag(memory_helper, message, body_arg, attached_doc):
            return rag_context, (1 if rag_context else 0), []

        with _patch.object(rc, "_build_rag_context", _fake_rag):
            result = await harness.call(body, server_state=state)
            await _drain(result)

    async def test_rule_armed_and_hash_stable_with_and_without_rag(self):
        from tests.plugins.web_ui_module.test_chat_inner_behavior import (
            _Harness,
            _make_server_state,
        )

        engine = _capturing_engine()
        state = _make_server_state(engine, module_name="mlx_module")
        h = _Harness()
        body_base = {"stream": True, "backend": "mlx", "session_id": "b263-e2e"}

        await self._run_turn(
            h, state, {**body_base, "message": "explica'm la memòria de sessions, va"},
        )
        await self._run_turn(
            h, state,
            {**body_base, "message": "i ara amb documents recuperats, sisplau"},
            rag_context="[CONTEXT] fets recuperats de la memòria [FI]",
        )

        assert len(engine.systems) == 2, "el fake engine ha de rebre els 2 torns"
        for system in engine.systems:
            assert _RAG_SECURITY_RULE["ca"] in system, (
                "el handler ha d'armar la regla SEMPRE (esborrar la línia de "
                "_finalize_system_prompt deixaria això RED)"
            )
            assert system.count(_RAG_SECURITY_RULE["ca"]) == 1, "regla duplicada"
        assert compute_system_hash(engine.systems[0]) == compute_system_hash(
            engine.systems[1]
        ), "torn amb RAG i torn sense han de compartir node de trie (#851)"

    async def test_continue_turn_shares_the_namespace(self):
        """Review #851 (major): el body de continue NO porta rag_collections —
        el handler ha de reutilitzar els toggles persistits a la sessió o el
        continue cau fora del prefix acabat de construir."""
        from tests.plugins.web_ui_module.test_chat_inner_behavior import (
            _Harness,
            _make_server_state,
        )

        engine = _capturing_engine()
        state = _make_server_state(engine, module_name="mlx_module")
        h = _Harness()
        cols = ["personal_memory"]  # documents/knowledge OFF → notes al system

        await self._run_turn(
            h, state,
            {"stream": True, "backend": "mlx", "session_id": "b263-cont",
             "message": "explica-m'ho amb els documents apagats, sisplau",
             "rag_collections": cols},
        )
        session = h.session_mgr.get_or_create_session("b263-cont")
        assert session.rag_collections == cols, "els toggles s'han de persistir a la sessió"
        session.messages.append({"role": "user", "content": "explica-m'ho"})
        session.messages.append({"role": "assistant", "content": "una resposta tallada"})

        await self._run_turn(
            h, state,
            {"stream": True, "backend": "mlx", "session_id": "b263-cont",
             "continue": True},  # com el frontend: SENSE rag_collections
        )

        assert len(engine.systems) == 2
        assert compute_system_hash(engine.systems[0]) == compute_system_hash(
            engine.systems[1]
        ), "el continue ha de quedar DINS el prefix del torn que continua"

    async def test_continue_does_not_advance_lang_hysteresis(self):
        """Review transversal: el continue re-alimenta _last_user — si avança
        la màquina d'estats del #850, 1 missatge anglès + 1 clic de Continue
        confirmaria la histèresi i fliparia a MIG continue (fora del prefix i
        amb directiva anglesa sobre una frase catalana tallada)."""
        pytest.importorskip("lingua", reason="cal lingua per la detecció real")
        from tests.plugins.web_ui_module.test_chat_inner_behavior import (
            _Harness,
            _make_server_state,
        )

        engine = _capturing_engine()
        state = _make_server_state(engine, module_name="mlx_module")
        h = _Harness()
        sid = "b263-hyst"
        base = {"stream": True, "backend": "mlx", "session_id": sid}

        # Torn 1: català llarg → sembra sticky ca
        await self._run_turn(h, state, {**base, "message": "explica'm com funciona la memòria de sessions, si us plau"})
        session = h.session_mgr.get_or_create_session(sid)
        assert session.lang == "ca"

        # Torn 2: anglès llarg (candidat a pending) — resposta "tallada"
        await self._run_turn(h, state, {**base, "message": "please explain the whole session memory system in detail"})
        assert session.lang == "ca", "1 sol torn anglès no pot flipar (histèresi)"
        assert session.lang_pending == "en"
        session.messages.append({"role": "user", "content": "please explain the whole session memory system in detail"})
        session.messages.append({"role": "assistant", "content": "una resposta catalana tallada a mig"})

        # Continue: NO pot confirmar la histèresi ni flipar
        await self._run_turn(h, state, {**base, "continue": True})
        assert session.lang == "ca", "el continue ha flipat l'sticky (transversal reobert)"
        assert session.lang_pending == "en", "el continue ha de deixar la histèresi INTACTA"
        assert compute_system_hash(engine.systems[1]) == compute_system_hash(
            engine.systems[2]
        ), "el system del continue ha de compartir prefix amb el torn que continua"


class TestOpenAiRouteParity:
    def test_injection_no_longer_arms_the_rule_itself(self):
        """La regla surt de _inject_rag_context_into_messages (que només corre
        amb context) i puja a _build_rag_and_system_prompt (sempre)."""
        src = inspect.getsource(openai_chat._inject_rag_context_into_messages)
        assert "rag_security_rule" not in src

    def test_build_arms_rule_unconditionally(self):
        src = inspect.getsource(openai_chat._build_rag_and_system_prompt)
        assert "append_rag_security_rule" in src

    @pytest.mark.asyncio
    async def test_build_produces_armed_system_WITH_context(self, monkeypatch):
        """Review B030: la direcció crítica de seguretat — torn AMB context
        untrusted → system armat — ha de seguir assertada enlloc."""

        async def _ctx(body, app_state, server_lang):
            return "fets recuperats del document"

        monkeypatch.setattr(openai_chat, "_fetch_rag_context", _ctx)
        monkeypatch.setattr(
            openai_chat,
            "_ensure_system_message",
            lambda messages, app_state, server_lang: messages.insert(
                0, {"role": "system", "content": "You are Nexe."}
            ),
        )
        body = type(
            "B",
            (),
            {
                "messages": [
                    type("M", (), {"model_dump": lambda self: {"role": "user", "content": "hola"}})()
                ]
            },
        )()
        messages, ctx = await openai_chat._build_rag_and_system_prompt(
            body, app_state=None, server_lang="ca"
        )
        assert ctx
        assert _RAG_SECURITY_RULE["ca"] in messages[0]["content"]
        assert any(
            "fets recuperats" in m.get("content", "") for m in messages[1:]
        ), "el context untrusted ha de viatjar als torns, no al system"

    @pytest.mark.asyncio
    async def test_build_produces_armed_system_without_context(self, monkeypatch):
        """Behavioral: sense cap context RAG, el system de la ruta OpenAI DUU la
        regla igualment (contra HEAD: només amb context → RED)."""

        async def _no_ctx(body, app_state, server_lang):
            return ""

        monkeypatch.setattr(openai_chat, "_fetch_rag_context", _no_ctx)
        monkeypatch.setattr(
            openai_chat,
            "_ensure_system_message",
            lambda messages, app_state, server_lang: messages.insert(
                0, {"role": "system", "content": "You are Nexe."}
            ),
        )
        body = type(
            "B",
            (),
            {
                "messages": [
                    type("M", (), {"model_dump": lambda self: {"role": "user", "content": "hola"}})()
                ]
            },
        )()
        messages, ctx = await openai_chat._build_rag_and_system_prompt(
            body, app_state=None, server_lang="ca"
        )
        assert ctx == ""
        assert messages[0]["role"] == "system"
        assert _RAG_SECURITY_RULE["ca"] in messages[0]["content"]
