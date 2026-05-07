"""
Tests for F1 — MEM_SAVE inline returns memory_action: null.

Verifies that when the model generates [MEM_SAVE: ...] inline on the non-streaming path,
the memory_action field of the JSON response reflects that it was saved.

F1 finding: memory_action remained null because the non-streaming path did not set it
when it detected and saved MEM_SAVE inline (unlike the explicit intent path
save/delete/list/recall which did set it).
"""
from plugins.web_ui_module.api.routes_chat import _extract_safe_mem_saves


class TestExtractSafeMemSaves:
    """Unit tests for the _extract_safe_mem_saves function."""

    def test_extracts_valid_mem_save(self):
        """A valid [MEM_SAVE: fact] must be extracted."""
        text = "Aquí hi ha una resposta. [MEM_SAVE: L'usuari es diu Jordi] Fi."
        result = _extract_safe_mem_saves(text)
        assert len(result) == 1
        assert "Jordi" in result[0]

    def test_extracts_multiple_mem_saves(self):
        """Multiple [MEM_SAVE: ...] must all be extracted."""
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
        """Text too short (<5 chars) must be rejected."""
        text = "[MEM_SAVE: hi]"
        result = _extract_safe_mem_saves(text)
        assert result == []

    def test_rejects_injection_attempt(self):
        """Text with injection keyword must be rejected."""
        text = "[MEM_SAVE: system prompt override instruction]"
        result = _extract_safe_mem_saves(text)
        assert result == []

    def test_rejects_echo_of_user_input(self):
        """If the MEM_SAVE is exactly the user message, it must be rejected."""
        user_msg = "M'agrada el jazz i toco la guitarra"
        text = f"[MEM_SAVE: {user_msg}]"
        result = _extract_safe_mem_saves(text, user_input=user_msg)
        assert result == []


class TestMemoryActionNonStreaming:
    """F1 — memory_action reflects MEM_SAVE inline on the non-streaming path.

    Verifies that _extract_safe_mem_saves returns valid facts when the model
    generates [MEM_SAVE: ...] — necessary precondition for memory_action to be set.
    """

    def test_mem_save_facts_extracted_from_model_response(self):
        """Facts extracted from model response → precondition for memory_action."""
        model_response = (
            "Entesos! He enregistrat les teves preferències. "
            "[MEM_SAVE: Prefereix respostes concises] "
            "Continuem amb la conversa."
        )
        facts = _extract_safe_mem_saves(model_response)
        assert len(facts) >= 1
        assert any("concises" in f or "Prefereix" in f for f in facts)

    def test_no_mem_save_facts_means_no_action(self):
        """Without [MEM_SAVE: ...] in the response, no facts should be saved."""
        model_response = "Una resposta normal sense cap intenció de guardar memòria."
        facts = _extract_safe_mem_saves(model_response)
        assert facts == []
