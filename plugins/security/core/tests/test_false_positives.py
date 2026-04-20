"""
────────────────────────────────────
Server Nexe
Location: plugins/security/core/tests/test_false_positives.py
Description: Tests de false positives — missatges normals d'usuari que NO han de ser bloquejats.
────────────────────────────────────
"""

import pytest
from fastapi import HTTPException
from plugins.security.core.input_sanitizers import validate_string_input

CONTEXT = "chat"


def _assert_not_blocked(message, description):
    """Helper: verifica que el missatge NO llança HTTPException."""
    try:
        result = validate_string_input(message, context=CONTEXT)
        # validate_string_input retorna el text (possiblement sanititzat amb html.escape)
        assert isinstance(result, str), f"Resultat inesperat per: {description}"
    except HTTPException as e:
        pytest.fail(f"False positive [{e.status_code}]: {description!r} — input: {message!r}")


# ── Tests parametritzats — missatges normals d'usuari ────────────────


@pytest.mark.parametrize("message,description", [
    # URLs
    ("mira https://example.com/api/v1/users", "URL amb path"),
    ("ves a https://docs.python.org/3/library/os.html#os.path.join", "URL documentació Python"),
    ("el link és http://localhost:8080/health", "URL localhost"),

    # Ellipsis i punts
    ("no sé... potser demà", "Ellipsis casual"),
    ("espera... deixa'm pensar... sí!", "Múltiples ellipsis"),
    ("...", "Només ellipsis"),
    ("hm........ ok", "Molts punts seguits"),

    # Code snippets en conversa
    ("usa `rm -rf /tmp/cache` per netejar", "Comanda Unix en backticks"),
    ("el `cat` de Linux serveix per mostrar fitxers", "Comanda Unix en text"),
    ("com funciona cd .. a Linux?", "cd .. en pregunta"),
    ("prova amb `ls -la /var/log`", "ls en backticks"),
    ("executa `pip install flask` al terminal", "pip install en conversa"),

    # URLs amb paràmetres
    ("ves a example.com?q=test&lang=ca", "URL amb query params"),
    ("busca a google.com/search?q=python+tutorial", "URL cerca Google"),

    # Text amb aspecte SQL-like
    ("selecciona els que tenen més de 10", "Frase amb 'selecciona'"),
    ("elimina els duplicats de la llista", "Frase amb 'elimina'"),
    ("actualitza el comptador cada hora", "Frase amb 'actualitza'"),
    ("la taula del menjador és gran", "Frase amb 'taula'"),

    # Paths locals
    ("el fitxer està a /Users/jordi/Documents/report.pdf", "Path absolut macOS"),
    ("guarda-ho a C:\\Users\\jordi\\Desktop", "Path Windows"),

    # Fraccions i barres
    ("és una fracció: 3/4 o 7/8", "Fraccions amb barres"),
    ("la proporció és 1/3 del total", "Fracció en text"),
    ("24/7 sempre disponible", "Format 24/7"),

    # HTML-like en conversa
    ("el tag <div> va dins del <body>", "Tags HTML en conversa"),
    ("usa <strong> per posar en negreta", "Tag HTML instrucció"),

    # JSON-like en conversa
    ('{"key": "value", "nested": {"a": 1}}', "JSON objecte"),
    ('[1, 2, 3, "hola"]', "JSON array"),

    # Emojis i caràcters especials
    ("hola! 👋 com va?", "Emojis"),
    ("🎉🎊 felicitats pel projecte!", "Múltiples emojis"),

    # Caràcters catalans
    ("l'àvia va dir: 'sí, és clar!'", "Apòstrofs i accents catalans"),
    ("la caça del cérvol és a l'hivern", "Ç i accents"),
    ("què, on, com, per què?", "Interrogatius catalans"),

    # Missatges llargs normals
    (
        "Bon dia! Estic treballant en un projecte de Python i tinc un dubte "
        "sobre com configurar el servidor. He provat amb Flask i FastAPI però "
        "no sé quin és millor per al meu cas. Pots ajudar-me?",
        "Missatge llarg normal"
    ),

    # Markdown en conversa
    ("## Títol del document\n\n- punt 1\n- punt 2\n\n**important**", "Markdown formatat"),
    ("```python\nprint('hola')\n```", "Code block markdown"),

    # Números i formats
    ("el preu és 19.99€ o $24.50", "Preus amb símbols"),
    ("la IP del servidor és 192.168.1.100", "Adreça IP"),
    ("truca'm al +34 612 345 678", "Número de telèfon"),

    # Separadors i signatures d'email (dos guions seguits de whitespace)
    (
        "Un saludo, Jordi\n\n----------------------------\n\nMi respuesta.\nHola!",
        "Separador visual amb guions (cas real correu de seguiment)"
    ),
    ("Salutacions,\n-- \nJordi Goy", "Signatura RFC 3676 (-- + espai + newline)"),
    ("text natural -- amb em-dash -- entre paraules", "Em-dash en conversa natural"),
    ("opcions: -- primera -- segona -- tercera", "Guions separadors en enumeracio"),
])
def test_normal_message_not_blocked(message, description):
    """Missatge normal d'usuari NO ha de ser bloquejat en context chat."""
    _assert_not_blocked(message, description)


# ── Tests HTML: sanititzat però NO bloquejat ─────────────────────────


@pytest.mark.parametrize("message,description", [
    ("<div>hola</div>", "Tag div simple"),
    ("<p>paràgraf</p>", "Tag p"),
    ("<b>negreta</b> i <i>cursiva</i>", "Tags inline"),
    ("<a href='https://example.com'>link</a>", "Tag anchor"),
])
def test_html_sanitized_not_blocked(message, description):
    """HTML normal és sanititzat (escaped) però NO bloquejat com a XSS."""
    _assert_not_blocked(message, description)


# ── Tests que verifiquen que atacs REALS SÍ són bloquejats ──────────


@pytest.mark.parametrize("message,description", [
    ("<script>alert('xss')</script>", "XSS script tag"),
    ("<img onerror='alert(1)' src=x>", "XSS img onerror"),
    ("' OR '1'='1' --", "SQL injection clàssic"),
    ("'; DROP TABLE users; --", "SQL DROP TABLE"),
    ("1 UNION SELECT * FROM passwords", "SQL UNION SELECT"),
])
def test_real_attacks_still_blocked(message, description):
    """Atacs reals SÍ han de ser bloquejats — no hem trencat la seguretat."""
    with pytest.raises(HTTPException) as exc_info:
        validate_string_input(message, context=CONTEXT)
    assert exc_info.value.status_code == 400, f"Atac no bloquejat: {description}"
