"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/intent_texts.py
Description: What a memory command answers, in the user's language.

Before C3.1 these lived inside the UI plugin in three different states: English
hardcoded (save, list, delete), Catalan hardcoded (clear_all) and a real ca/es/en
table (the delete confirmation). One table now, same resolution the existing
tables already used (NEXE_LANG), so a memory command answers in the server's
language whichever door asked.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os

#: Language of the answers. Same resolution `_build_delete_confirm_response`
#: used before C3.1 (NEXE_LANG, first subtag) — not the request's Accept-Language:
#: these texts belong to the server's voice, like the system prompt.
DEFAULT_LANG = "en"

def current_lang() -> str:
    return os.environ.get("NEXE_LANG", DEFAULT_LANG).split("-")[0].lower()

#: D6 removed the `save.*` texts: a save no longer answers the turn, so it
#: has no text of its own — the note travels as [MEM:n]/memory_saved.
TEXTS: dict[str, dict[str, str]] = {
    "ca": {
        # C4.5 (decision of 26/09): what the user reads when the model wrote
        # only memory tags and no second reply came — neutral, never "saved":
        # the server's [MEM:n:facts] note is the only word on that (#1098).
        "reply.ack": "D'acord.",
        "delete.empty": "Què vols que oblidi?",
        "delete.not_found": 'No he trobat res sobre "{fact}" a la memòria.',
        "delete.error": "Error: {error}",
        "delete.done": "He esborrat {n} record(s){details}. Ja no ho recordaré.",
        "delete.nothing_pending": "No hi ha res pendent d'esborrar.",
        "delete.confirm": ('Vols que esborri això de la memòria?{items}{profile_warn} '
                           'Respon "sí" per confirmar, o qualsevol altra cosa per cancel·lar.'),
        "delete.profile_warning": " (ATENCIÓ: inclou dades de perfil de l'usuari)",
        "delete.blocked": ("Per esborrar dades de perfil necessito que ho diguis explícitament "
                           "(per exemple: «esborra que ...»), no només «sí». No s'ha esborrat res."),
        "list.header": "Memòria activa — {shown} de {total} entrades:",
        "list.empty": "No tinc res desat a la memòria.",
        "clear_all.confirm": ("Segur que vols esborrar TOTA la memòria personal? "
                              "Aquesta acció és irreversible. "
                              'Respon "sí, esborra-ho tot" per confirmar, '
                              "o qualsevol altra cosa per cancel·lar."),
        "clear_all.done": "✓ Memòria personal esborrada completament. Ja no recordo res sobre tu.",
        "clear_all.error": "Error esborrant la memòria: {error}",
    },
    "es": {
        "reply.ack": "De acuerdo.",
        "delete.empty": "¿Qué quieres que olvide?",
        "delete.not_found": 'No he encontrado nada sobre "{fact}" en la memoria.',
        "delete.error": "Error: {error}",
        "delete.done": "He borrado {n} recuerdo(s){details}. Ya no lo recordaré.",
        "delete.nothing_pending": "No hay nada pendiente de borrar.",
        "delete.confirm": ('¿Quieres que borre esto de la memoria?{items}{profile_warn} '
                           'Responde "sí" para confirmar, o cualquier otra cosa para cancelar.'),
        "delete.profile_warning": " (ATENCIÓN: incluye datos de perfil del usuario)",
        "delete.blocked": ("Para borrar datos de perfil necesito que lo digas explícitamente "
                           "(por ejemplo: «borra que ...»), no solo «sí». No se ha borrado nada."),
        "list.header": "Memoria activa — {shown} de {total} entradas:",
        "list.empty": "No tengo nada guardado en la memoria.",
        "clear_all.confirm": ("¿Seguro que quieres borrar TODA la memoria personal? "
                              "Esta acción es irreversible. "
                              'Responde "sí, bórralo todo" para confirmar, '
                              "o cualquier otra cosa para cancelar."),
        "clear_all.done": "✓ Memoria personal borrada completamente. Ya no recuerdo nada sobre ti.",
        "clear_all.error": "Error borrando la memoria: {error}",
    },
    "en": {
        "reply.ack": "Okay.",
        "delete.empty": "What do you want me to forget?",
        "delete.not_found": 'Nothing found about "{fact}" in memory.',
        "delete.error": "Error: {error}",
        "delete.done": "Deleted {n} memory(ies){details}. I won't remember this anymore.",
        "delete.nothing_pending": "Nothing pending to delete.",
        "delete.confirm": ('Do you want me to delete this from memory?{items}{profile_warn} '
                           'Reply "yes" to confirm, or anything else to cancel.'),
        "delete.profile_warning": " (WARNING: includes user profile data)",
        "delete.blocked": ('To delete profile data I need an explicit reference '
                           '(e.g. "delete that ..."), not just "yes". Nothing was deleted.'),
        "list.header": "Active memory — {shown} of {total} entries:",
        "list.empty": "No memories stored.",
        "clear_all.confirm": ("Are you sure you want to delete ALL personal memory? "
                              "This action is irreversible. "
                              'Reply "yes, delete everything" to confirm, '
                              "or anything else to cancel."),
        "clear_all.done": "✓ Personal memory completely deleted. I no longer remember anything about you.",
        "clear_all.error": "Error clearing memory: {error}",
    },
}

def text(key: str, *, lang: "str | None" = None, **kwargs) -> str:
    """The text for `key` in the server's language, English as the fallback.

    `lang` (C4.5) picks the TURN's language instead: a reply that stands in
    for the model's answer speaks the conversation's language, not the
    server's — the same rule the re-prompt override has always followed.
    """
    lang = (lang or current_lang()).split("-")[0].lower()
    table = TEXTS.get(lang) or TEXTS[DEFAULT_LANG]
    template = table.get(key) or TEXTS[DEFAULT_LANG].get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
