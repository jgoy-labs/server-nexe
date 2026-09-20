"""The context presenter is one per process, reachable from both doors.

Same shape as `tests/core/files/test_attach_file_handler.py` and
`tests/core/memory_facts/test_attach.py` — the pattern this repo uses for every
piece the core owns and the doors consume: bare state, idempotence, the mirror
onto `app.state`, a warning instead of a crash when it is missing, and the
placement guard that reads `core/lifespan.py` as text.

The last one earns its keep here as much as it did for the file handler:
without it, "drop the attach from the lifespan" passes every behavioural test,
because `frame_for` falls back to the default and every prompt still looks
right. The piece would be dead and nothing would say so.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.context_presentation import (
    ContextFraming,
    ContextPresenter,
    ContextShape,
    DefaultContextPresenter,
    attach_context_presenter,
    frame_for,
)
from core.lifespan_sessions import _expose_context_presenter

ROOT = Path(__file__).resolve().parents[3]


class _BareState:
    """A server_state with nothing on it — no modules, no plugins, no config."""


# ── the attach ───────────────────────────────────────────────────────────────

def test_attach_creates_one_and_puts_it_on_the_state():
    state = _BareState()
    presenter = attach_context_presenter(state)

    assert isinstance(presenter, DefaultContextPresenter)
    assert state.context_presenter is presenter
    assert isinstance(presenter, ContextPresenter)


def test_attach_is_idempotent_and_that_is_the_extension_point():
    """Returning what is already there is not just an economy: it is how a
    plugin's presenter survives the lifespan running after it."""
    state = _BareState()
    first = attach_context_presenter(state)
    assert attach_context_presenter(state) is first


def test_attach_respects_a_presenter_that_was_already_there():
    class _Other:
        def frame(self, shape):
            return ContextFraming(legend="other", closing="")

    state = _BareState()
    mine = _Other()
    state.context_presenter = mine

    assert attach_context_presenter(state) is mine


def test_expose_mirrors_the_same_object_never_a_second_one():
    """One registry, one brain (`core/lifespan_sessions.py:27-35`)."""
    state = _BareState()
    presenter = attach_context_presenter(state)
    app = SimpleNamespace(state=SimpleNamespace())

    _expose_context_presenter(app, state)

    assert app.state.context_presenter is presenter


def test_expose_without_attach_warns_and_leaves_app_state_alone(caplog):
    app = SimpleNamespace(state=SimpleNamespace())
    with caplog.at_level(logging.WARNING):
        _expose_context_presenter(app, SimpleNamespace(context_presenter=None))

    assert not hasattr(app.state, "context_presenter")
    assert any("not attached" in r.getMessage() for r in caplog.records)


def test_lifespan_attaches_and_exposes_the_presenter():
    """Placement guard: the attach must run, and must run before modules are
    discovered, or a plugin bringing its own would be attaching into a state
    nobody reads afterwards."""
    lines = (ROOT / "core" / "lifespan.py").read_text(encoding="utf-8").splitlines()

    def line_of(call):
        hits = [i for i, ln in enumerate(lines)
                if ln.strip().startswith(call) and not ln.strip().startswith("#")]
        assert hits, f"the lifespan never calls {call}"
        return hits[0]

    attach = line_of("await _startup_context_presenter(server_state)")
    expose = line_of("_expose_context_presenter(app, server_state)")
    modules = line_of("await _startup_module_discovery(app, server_state, _translate)")
    assert attach < expose < modules


def test_the_package_imports_nothing_from_plugins():
    """core/context_presentation/ imports only from core/ — `core → plugins` is
    zero and the layering gate keeps it that way."""
    import core.context_presentation as pkg

    pkg_dir = Path(pkg.__file__).parent
    for name in ("attach.py", "default.py", "port.py"):
        src = (pkg_dir / name).read_text(encoding="utf-8")
        assert "import plugins" not in src, f"{name} imports plugins"
        assert "from plugins" not in src, f"{name} imports from plugins"
        assert "import memory" not in src, f"{name} imports memory"


# ── the resolver ─────────────────────────────────────────────────────────────

def test_frame_for_without_a_presenter_still_frames():
    """Permissive like `gate_for`: a turn with no presenter is a plainer
    prompt, never a dead turn."""
    framing = frame_for(_BareState(), ContextShape("ca", has_document=True))

    assert "DOCUMENT ADJUNTAT" in framing.closing


def test_a_magic_mock_app_state_does_not_reach_the_prompt(caplog):
    """🔴 The trap `runtime_checkable` cannot catch on its own.

    `isinstance` against a Protocol checks that the ATTRIBUTES are there, so a
    `MagicMock` satisfies `ContextPresenter` — and
    `tests/core/test_fd_block4_budget_shared.py:150` really does pass one as
    `app_state`. Its `.frame()` answers with another Mock, and formatted into
    the prompt that is a literal `<MagicMock id=...>` sent to the model.

    Validating what comes BACK is the only check that sees it.
    """
    state = MagicMock()
    assert isinstance(state.context_presenter, ContextPresenter), (
        "this test is pointless if a MagicMock stops satisfying the Protocol"
    )

    with caplog.at_level(logging.WARNING):
        framing = frame_for(state, ContextShape("ca", has_document=True, has_rag=True))

    assert isinstance(framing, ContextFraming)
    assert "MagicMock" not in framing.legend + framing.closing
    assert "DOCUMENT ADJUNTAT" in framing.closing
    assert any("not ContextFraming" in r.getMessage() for r in caplog.records)


def test_a_presenter_that_raises_costs_the_wording_not_the_turn(caplog):
    class _Broken:
        def frame(self, shape):
            raise RuntimeError("boom")

    state = SimpleNamespace(context_presenter=_Broken())
    with caplog.at_level(logging.WARNING):
        framing = frame_for(state, ContextShape("ca", has_rag=True))

    assert "INFORMACIO RECUPERADA" in framing.legend
    assert any("failed" in r.getMessage() for r in caplog.records)


def test_a_real_presenter_is_used_as_is():
    class _Other:
        def frame(self, shape):
            return ContextFraming(legend="MEVA LLEGENDA", closing="MEU TANCAMENT")

    state = SimpleNamespace(context_presenter=_Other())
    framing = frame_for(state, ContextShape("ca", has_document=True, has_rag=True))

    assert framing.legend == "MEVA LLEGENDA"
    assert framing.closing == "MEU TANCAMENT"


# ── the default's words ──────────────────────────────────────────────────────

@pytest.mark.parametrize("lang,doc_mark,rag_mark", [
    ("ca", "DOCUMENT ADJUNTAT", "INFORMACIO RECUPERADA"),
    ("es", "DOCUMENTO ADJUNTO", "INFORMACION RECUPERADA"),
    ("en", "ATTACHED DOCUMENT", "RETRIEVED INFORMATION"),
    ("fr", "ATTACHED DOCUMENT", "RETRIEVED INFORMATION"),  # unsupported -> en
])
def test_the_default_speaks_the_turn_language(lang, doc_mark, rag_mark, monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "ca")  # contradicted by the turn's lang
    framing = DefaultContextPresenter().frame(
        ContextShape(lang, has_document=True, has_rag=True)
    )

    assert doc_mark in framing.closing
    assert rag_mark in framing.legend


def test_no_turn_language_falls_back_to_the_server(monkeypatch):
    """#1072's decision, moved and not reinvented: a caller with no turn
    language in hand keeps getting the server's voice."""
    monkeypatch.setenv("NEXE_LANG", "ca")
    framing = DefaultContextPresenter().frame(
        ContextShape(None, has_document=True, has_rag=True)
    )

    assert "DOCUMENT ADJUNTAT" in framing.closing
    assert "INFORMACIO RECUPERADA" in framing.legend


@pytest.mark.parametrize("has_document,has_rag", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_each_field_appears_only_for_its_own_kind_of_context(has_document, has_rag):
    """A turn with no document must not carry a sentence citing one — that is
    the bug this piece exists to make impossible, not merely unlikely."""
    framing = DefaultContextPresenter().frame(ContextShape("ca", has_document, has_rag))

    assert bool(framing.closing) is has_document
    assert bool(framing.legend) is has_rag


def test_the_legend_names_every_section_label():
    """🔴 The correspondence ADR-008 called deliberate, made into a gate.

    `chat_rag._format_results` emits these labels and the system prompt cites
    them by name. The legend explains them. All three were hand-copied
    literals in three places, and nothing went red when one drifted.
    """
    from core.endpoints.chat_rag import _RAG_CONTEXT_LABELS

    for lang in ("ca", "es", "en"):
        legend = DefaultContextPresenter().frame(
            ContextShape(lang, has_rag=True)
        ).legend
        for key in ("docs", "knowledge", "memory"):
            label = _RAG_CONTEXT_LABELS[lang][key]
            assert label in legend, (
                f"[{lang}] the legend does not name {label!r} — the model is shown "
                "a section label the framing never explains"
            )


def test_every_label_is_cited_by_the_system_prompt_in_all_six_keys():
    """The "six keys" of ADR-008, no longer a sentence in a document.

    `personality/server.toml` holds the prompt in `{lang}_{tier}` — three
    languages times two tiers — and every one of them must name the labels it
    expects the model to recognise. This is the gate that would have caught a
    label renamed in one tier and not the other.
    """
    import tomllib

    from core.endpoints.chat_rag import _RAG_CONTEXT_LABELS

    data = tomllib.loads(
        (ROOT / "personality" / "server.toml").read_text(encoding="utf-8")
    )
    #: `[personality.prompt]`, the path `core/turn/prompt.py:69` reads. Written
    #: out rather than searched: the first version of this test did
    #: `data.get("prompts", data)`, found nothing, and skipped every assertion
    #: while passing green — the exact theatre this repo keeps catching.
    prompts = data["personality"]["prompt"]

    checked = 0
    for lang in ("ca", "es", "en"):
        for tier in ("small", "full"):
            key = f"{lang}_{tier}"
            text = prompts[key]  # KeyError if a tier stops shipping: say so loudly
            for label_key in ("docs", "knowledge", "memory"):
                label = _RAG_CONTEXT_LABELS[lang][label_key]
                assert label in text, (
                    f"{key} never names {label!r}, but the retrieved block uses it "
                    "as a section heading"
                )
                checked += 1

    assert checked == 18, (
        f"expected 3 languages x 2 tiers x 3 labels, checked {checked} — "
        "a loop that skips is a test that lies"
    )
