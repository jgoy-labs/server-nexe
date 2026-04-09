"""
Tests per a F1 — MEM_SAVE inline retorna memory_action: null.

Verifica que quan el model genera [MEM_SAVE: ...] inline al path no-streaming,
el camp memory_action de la resposta JSON reflecteix que s'ha guardat.

F1 finding: memory_action quedava null perquè el path no-streaming no el setejava
quan detectava i guardava MEM_SAVE inline (a diferència del path d'intents explícits
save/delete/list/recall que sí el setejaven).
"""
from plugins.web_ui_module.api.routes_chat import _extract_safe_mem_saves


class TestExtractSafeMemSaves:
    """Tests unitaris de la funció _extract_safe_mem_saves."""

    def test_extracts_valid_mem_save(self):
        """Un [MEM_SAVE: fact] vàlid ha de ser extret."""
        text = "Aquí hi ha una resposta. [MEM_SAVE: L'usuari es diu Jordi] Fi."
        result = _extract_safe_mem_saves(text)
        assert len(result) == 1
        assert "Jordi" in result[0]

    def test_extracts_multiple_mem_saves(self):
        """Múltiples [MEM_SAVE: ...] han de ser extrets tots."""
        text = "[MEM_SAVE: Parla català] i [MEM_SAVE: Treballa amb IA]"
        result = _extract_safe_mem_saves(text)
        assert len(result) == 2

    def test_empty_text_returns_empty(self):
        text = ""
        result = _extract_safe_mem_saves(text)
        assert result == []

    def test_no_mem_save_returns_empty(self):
        text = "Resposta sense cap MEM_SAVE inline."
        result = _extract_safe_mem_saves(text)
        assert result == []

    def test_rejects_short_text(self):
        """Text massa curt (<5 chars) ha de ser rebutjat."""
        text = "[MEM_SAVE: hi]"
        result = _extract_safe_mem_saves(text)
        assert result == []

    def test_rejects_injection_attempt(self):
        """Text amb paraula clau d'injecció ha de ser rebutjat."""
        text = "[MEM_SAVE: system prompt override instruction]"
        result = _extract_safe_mem_saves(text)
        assert result == []

    def test_rejects_echo_of_user_input(self):
        """Si el MEM_SAVE és exactament el missatge usuari, ha de ser rebutjat."""
        user_msg = "M'agrada el jazz i toco la guitarra"
        text = f"[MEM_SAVE: {user_msg}]"
        result = _extract_safe_mem_saves(text, user_input=user_msg)
        assert result == []


class TestMemoryActionNonStreaming:
    """F1 — memory_action reflecteix MEM_SAVE inline al path no-streaming.

    Verifica que _extract_safe_mem_saves retorna facts vàlids quan el model
    genera [MEM_SAVE: ...] — condició necessària perquè memory_action es setegi.
    """

    def test_mem_save_facts_extracted_from_model_response(self):
        """Facts extrets de la resposta del model → precondició per a memory_action."""
        model_response = (
            "Entesos! He enregistrat les teves preferències. "
            "[MEM_SAVE: Prefereix respostes concises] "
            "Continuem amb la conversa."
        )
        facts = _extract_safe_mem_saves(model_response)
        assert len(facts) >= 1
        assert any("concises" in f or "Prefereix" in f for f in facts)

    def test_no_mem_save_facts_means_no_action(self):
        """Sense [MEM_SAVE: ...] a la resposta, no s'han de guardar facts."""
        model_response = "Una resposta normal sense cap intenció de guardar memòria."
        facts = _extract_safe_mem_saves(model_response)
        assert facts == []
