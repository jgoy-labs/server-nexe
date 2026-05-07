"""
────────────────────────────────────
Server Nexe
Location: plugins/security/core/tests/test_false_positives.py
Description: False positive tests — normal user messages that must NOT be blocked.
────────────────────────────────────
"""

import pytest
from fastapi import HTTPException
from plugins.security.core.input_sanitizers import validate_string_input

CONTEXT = "chat"


def _assert_not_blocked(message, description):
    """Helper: verifies that the message does NOT raise HTTPException."""
    try:
        result = validate_string_input(message, context=CONTEXT)
        # validate_string_input returns the text (possibly sanitized with html.escape)
        assert isinstance(result, str), f"Unexpected result for: {description}"
    except HTTPException as e:
        pytest.fail(f"False positive [{e.status_code}]: {description!r} — input: {message!r}")


# ── Parameterized tests — normal user messages ────────────────


@pytest.mark.parametrize("message,description", [
    # URLs
    ("mira https://example.com/api/v1/users", "URL amb path"),
    ("ves a https://docs.python.org/3/library/os.html#os.path.join", "URL documentació Python"),
    ("el link és http://localhost:8080/health", "URL localhost"),

    # Ellipsis and dots
    ("no sé... potser demà", "Ellipsis casual"),
    ("espera... deixa'm pensar... sí!", "Múltiples ellipsis"),
    ("...", "Només ellipsis"),
    ("hm........ ok", "Molts punts seguits"),

    # Code snippets in conversation
    ("usa `rm -rf /tmp/cache` per netejar", "Comanda Unix en backticks"),
    ("el `cat` de Linux serveix per mostrar fitxers", "Comanda Unix en text"),
    ("com funciona cd .. a Linux?", "cd .. en pregunta"),
    ("prova amb `ls -la /var/log`", "ls en backticks"),
    ("executa `pip install flask` al terminal", "pip install en conversa"),

    # URLs with parameters
    ("ves a example.com?q=test&lang=ca", "URL amb query params"),
    ("busca a google.com/search?q=python+tutorial", "URL cerca Google"),

    # SQL-like looking text
    ("selecciona els que tenen més de 10", "Frase amb 'selecciona'"),
    ("elimina els duplicats de la llista", "Frase amb 'elimina'"),
    ("actualitza el comptador cada hora", "Frase amb 'actualitza'"),
    ("la taula del menjador és gran", "Frase amb 'taula'"),

    # Local paths
    ("el fitxer està a /Users/jordi/Documents/report.pdf", "Path absolut macOS"),
    ("guarda-ho a C:\\Users\\jordi\\Desktop", "Path Windows"),

    # Fractions and slashes
    ("és una fracció: 3/4 o 7/8", "Fraccions amb barres"),
    ("la proporció és 1/3 del total", "Fracció en text"),
    ("24/7 sempre disponible", "Format 24/7"),

    # HTML-like in conversation
    ("el tag <div> va dins del <body>", "Tags HTML en conversa"),
    ("usa <strong> per posar en negreta", "Tag HTML instrucció"),

    # JSON-like in conversation
    ('{"key": "value", "nested": {"a": 1}}', "JSON objecte"),
    ('[1, 2, 3, "hola"]', "JSON array"),

    # Emojis and special characters
    ("hola! 👋 com va?", "Emojis"),
    ("🎉🎊 felicitats pel projecte!", "Múltiples emojis"),

    # Catalan characters
    ("l'àvia va dir: 'sí, és clar!'", "Apòstrofs i accents catalans"),
    ("la caça del cérvol és a l'hivern", "Ç i accents"),
    ("què, on, com, per què?", "Interrogatius catalans"),

    # Normal long messages
    (
        "Bon dia! Estic treballant en un projecte de Python i tinc un dubte "
        "sobre com configurar el servidor. He provat amb Flask i FastAPI però "
        "no sé quin és millor per al meu cas. Pots ajudar-me?",
        "Missatge llarg normal"
    ),

    # Markdown in conversation
    ("## Títol del document\n\n- punt 1\n- punt 2\n\n**important**", "Markdown formatat"),
    ("```python\nprint('hola')\n```", "Code block markdown"),

    # Numbers and formats
    ("el preu és 19.99€ o $24.50", "Preus amb símbols"),
    ("la IP del servidor és 192.168.1.100", "Adreça IP"),
    ("truca'm al +34 612 345 678", "Número de telèfon"),

    # Email separators and signatures (two dashes followed by whitespace)
    (
        "Un saludo, Jordi\n\n----------------------------\n\nMi respuesta.\nHola!",
        "Separador visual amb guions (cas real correu de seguiment)"
    ),
    ("Salutacions,\n-- \nJordi Goy", "Signatura RFC 3676 (-- + espai + newline)"),
    ("text natural -- amb em-dash -- entre paraules", "Em-dash en conversa natural"),
    ("opcions: -- primera -- segona -- tercera", "Guions separadors en enumeracio"),
])
def test_normal_message_not_blocked(message, description):
    """Normal user message must NOT be blocked in chat context."""
    _assert_not_blocked(message, description)


# ── HTML tests: sanitized but NOT blocked ─────────────────────────


@pytest.mark.parametrize("message,description", [
    ("<div>hola</div>", "Tag div simple"),
    ("<p>paràgraf</p>", "Tag p"),
    ("<b>negreta</b> i <i>cursiva</i>", "Tags inline"),
    ("<a href='https://example.com'>link</a>", "Tag anchor"),
])
def test_html_sanitized_not_blocked(message, description):
    """Normal HTML is sanitized (escaped) but NOT blocked as XSS."""
    _assert_not_blocked(message, description)


# ── Tests that verify REAL attacks ARE blocked ──────────


@pytest.mark.parametrize("message,description", [
    ("<script>alert('xss')</script>", "XSS script tag"),
    ("<img onerror='alert(1)' src=x>", "XSS img onerror"),
])
def test_real_attacks_still_blocked_in_chat(message, description):
    """In context=chat, XSS remains blocked because rendered text can reach
    the browser. SQL / command / LDAP / path-traversal are disabled in chat to
    avoid false positives in natural conversation — these attacks do not reach any
    DB / shell / LDAP via chat (see test_real_sql_attacks_still_blocked_in_param)."""
    with pytest.raises(HTTPException) as exc_info:
        validate_string_input(message, context=CONTEXT)
    assert exc_info.value.status_code == 400, f"Attack not blocked: {description}"


@pytest.mark.parametrize("message,description", [
    ("' OR '1'='1' --", "SQL injection clàssic"),
    ("'; DROP TABLE users; --", "SQL DROP TABLE"),
    ("1 UNION SELECT * FROM passwords", "SQL UNION SELECT"),
])
def test_real_sql_attacks_still_blocked_in_param(message, description):
    """In context=param (default), the SQL detector remains active for endpoints
    that accept structured identifiers, filters, sorting, etc."""
    with pytest.raises(HTTPException) as exc_info:
        validate_string_input(message, context="param")
    assert exc_info.value.status_code == 400, f"SQL attack not blocked in param: {description}"
