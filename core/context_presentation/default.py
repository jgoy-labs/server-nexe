"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/context_presentation/default.py
Description: The framing server-nexe ships with, one text per kind of context.

ADR-008 (presentation half). The two dictionaries below are MOVED, not
rewritten: they are byte-for-byte the ones that lived at
`core/context_budget.py` (`_doc_framing`, `_rag_instruction`), so this step
changes WHERE the words live and nothing about WHAT they say. Any wording
change is a separate decision with its own live check.

**The long legend is the one that survives, at both doors.** `/v1` carried a
one-liner ("use this retrieved information if relevant") while the web door
carried this one. It is not a tie broken by taste:

* the labels this legend names — `[DOCUMENTACIO DEL SISTEMA]` and its
  siblings — are emitted at BOTH doors by `chat_rag._format_results`, and the
  system prompt cites them by name. A legend that does not name them leaves
  the labels unexplained in front of a model that was told they matter.
* "MAI diguis que ho saps pel teu entrenament si la info ve d'aqui" is
  BEHAVIOUR, not decoration: it changes what the model answers when asked
  where it knows something from. `/v1` never had it. Unifying downwards would
  have been losing behaviour the web door has today.

The cost is real and paid for elsewhere: 397 chars in Catalan against 64, and
`_trim_rag_context` subtracts it from the retrieved payload so the assembled
prompt does not grow (`WRAPPER_SLACK` is what measures that promise).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os as _os

from core.context_presentation.port import ContextFraming, ContextShape

#: The sentence that cites the attached document. Moved verbatim from
#: `core/context_budget.py::_doc_framing`. It speaks of "the PREVIOUS context
#: block", which is why `ContextFraming` carries it as `closing`.
_DOC_CLOSING = {
    "ca": (
        "Respon basant-te en el DOCUMENT ADJUNTAT del bloc de context "
        "anterior. Si la informacio no hi es, indica-ho clarament."
    ),
    "es": (
        "Responde basandote en el DOCUMENTO ADJUNTO del bloque de "
        "contexto anterior. Si la informacion no esta, indicalo claramente."
    ),
    "en": (
        "Answer based on the ATTACHED DOCUMENT in the previous context "
        "block. If the information is not there, say so clearly."
    ),
}

#: The source legend. Moved verbatim from `core/context_budget.py::_rag_instruction`.
#: It names the three section labels, which is why
#: `test_the_legend_names_every_section_label` pins the correspondence.
_RAG_LEGEND = {
    "ca": (
        "INFORMACIO RECUPERADA. UTILITZA-LA per respondre. "
        "Si la resposta es aqui, cita-la directament. "
        "Fonts: [DOCUMENTACIO DEL SISTEMA] = knowledge base del sistema, "
        "[DOCUMENTACIO TECNICA] = documents pujats per l'usuari, "
        "[MEMORIA DE L'USUARI] = coses que l'usuari t'ha dit abans. "
        "Quan et preguntin d'on saps algo, indica la font correcta. "
        "MAI diguis que ho saps pel teu entrenament si la info ve d'aqui:"
    ),
    "es": (
        "INFORMACION RECUPERADA. UTILIZALA para responder. "
        "Si la respuesta esta aqui, citala directamente. "
        "Fuentes: [DOCUMENTACION DEL SISTEMA] = knowledge base del sistema, "
        "[DOCUMENTACION TECNICA] = documentos subidos por el usuario, "
        "[MEMORIA DEL USUARIO] = cosas que el usuario te dijo antes. "
        "Cuando te pregunten de donde sabes algo, indica la fuente correcta. "
        "NUNCA digas que lo sabes por tu entrenamiento si la info viene de aqui:"
    ),
    "en": (
        "RETRIEVED INFORMATION. USE IT to answer. "
        "If the answer is here, cite it directly. "
        "Sources: [SYSTEM DOCUMENTATION] = system knowledge base, "
        "[TECHNICAL DOCUMENTATION] = documents uploaded by the user, "
        "[USER MEMORY] = things the user told you before. "
        "When asked where you know something from, indicate the correct source. "
        "NEVER say you know it from training if the info comes from here:"
    ),
}


#: The sentence that flags an attached image (#1081). Content carried over
#: from the old `_inject_image_block` (`plugins/web_ui_module/api/routes_chat.py`),
#: minus its own `[IMATGE ADJUNTA]`/`[FI IMATGE]` wrapper: the image is not
#: untrusted data to delimit (it never enters the text prompt at all — it
#: travels as `images=[...]`), so there is nothing here for B030 to wrap.
_IMAGE_NOTE = {
    "ca": (
        "L'usuari ha adjuntat una imatge a aquest missatge. Analitza-la i "
        "incorpora-la a la teva resposta, prioritzant el que hi veus per "
        "sobre de memories anteriors."
    ),
    "es": (
        "El usuario ha adjuntado una imagen a este mensaje. Analizala e "
        "incorporala a tu respuesta, priorizando lo que ves en ella por "
        "encima de memorias anteriores."
    ),
    "en": (
        "The user has attached an image to this message. Analyze it and "
        "incorporate it into your response, prioritizing what you see in it "
        "over previous memories."
    ),
}


def _lang_key(lang: str | None) -> str:
    """Two-letter code, the server's language when the turn has none.

    The exact normalisation `_inject_context_into_messages` has applied since
    #1072 — moved, not reinvented, so the fallback a caller without turn
    language relies on keeps behaving identically.
    """
    return (lang or _os.environ.get("NEXE_LANG", "en")).split("-")[0].lower()


class DefaultContextPresenter:
    """The framing that ships with server-nexe.

    Stateless, so one instance per process is an economy and never a shared
    mutable — unlike `SessionManager`, where the singleton is the point.
    """

    def frame(self, shape: ContextShape) -> ContextFraming:
        lk = _lang_key(shape.lang)
        return ContextFraming(
            legend=_RAG_LEGEND.get(lk, _RAG_LEGEND["en"]) if shape.has_rag else "",
            closing=_DOC_CLOSING.get(lk, _DOC_CLOSING["en"]) if shape.has_document else "",
            note=_IMAGE_NOTE.get(lk, _IMAGE_NOTE["en"]) if shape.has_image else "",
        )
