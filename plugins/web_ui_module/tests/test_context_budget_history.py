"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_context_budget_history.py
Description: Bug 32 — Tests del budget dinàmic de context window.
             Verifica que un document gran NO trunca l'historial de conversa,
             sinó que el document es trunca per preservar la reserva mínima
             d'historial (NEXE_HISTORY_CONTEXT_RATIO).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


from plugins.web_ui_module.api.routes_chat import compute_context_budget


class TestComputeContextBudget:
    """Bug 32 — budget de context que preserva l'historial."""

    def test_small_doc_fits_completely(self):
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=2000,
            message_chars=200,
            document_chars=1000,
            history_ratio=0.30,
        )
        assert out["doc_truncated_pct"] == 0
        assert out["doc_kept_chars"] == 1000

    def test_huge_doc_truncated_history_preserved(self):
        """Bug 32 core: PDF gigant + historial llarg -> document tallat, historial intacte."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=3000,  # historial real
            message_chars=200,
            document_chars=50000,  # PDF de 573 chunks ~ molt gran
            history_ratio=0.30,
        )
        # Historial efectiu = max(3000, 30%*10000=3000) = 3000
        assert out["history_effective"] == 3000
        # Disponible per doc = 10000 - 500 - 3000 - 200 - 500 = 5800
        assert out["available_chars"] == 5800
        # Document truncat
        assert out["doc_truncated_pct"] > 0
        assert out["doc_kept_chars"] == 5800

    def test_history_below_reserve_uses_reserve(self):
        """Si l'historial real és més petit que la reserva, el budget reserva igualment."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=500,  # historial petit
            message_chars=200,
            document_chars=8000,
            history_ratio=0.30,
        )
        # Reserva = 3000
        assert out["history_reserve"] == 3000
        assert out["history_effective"] == 3000  # max(500, 3000)
        # Disponible = 10000 - 500 - 3000 - 200 - 500 = 5800
        assert out["available_chars"] == 5800
        # Doc 8000 -> truncat a 5800
        assert out["doc_kept_chars"] == 5800
        assert out["doc_truncated_pct"] == round((1 - 5800 / 8000) * 100)

    def test_history_above_reserve_not_truncated(self):
        """Si l'historial real és més gran que la reserva, NO es trunca."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=5000,  # excedeix reserva
            message_chars=200,
            document_chars=8000,
            history_ratio=0.30,
        )
        # Historial efectiu = max(5000, 3000) = 5000 (real, no es trunca)
        assert out["history_effective"] == 5000
        # Disponible = 10000 - 500 - 5000 - 200 - 500 = 3800
        assert out["available_chars"] == 3800
        # Document tallat a 3800
        assert out["doc_kept_chars"] == 3800

    def test_no_document_no_truncation(self):
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=2000,
            message_chars=200,
            document_chars=0,
            history_ratio=0.30,
        )
        assert out["doc_truncated_pct"] == 0
        assert out["doc_kept_chars"] == 0

    def test_zero_history_with_huge_doc_still_reserves(self):
        """Sessió nova (sense historial) + doc gigant: la reserva s'aplica igual."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=0,
            message_chars=200,
            document_chars=20000,
            history_ratio=0.30,
        )
        # Reserva 3000 garanteix que noves preguntes podran tenir espai d'historial
        assert out["history_effective"] == 3000
        assert out["available_chars"] == 5800

    def test_ratio_clamped_below(self):
        """Ratio negatiu es satura a 0."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=0,
            history_chars=0,
            message_chars=0,
            document_chars=20000,
            history_ratio=-1.0,
        )
        assert out["history_reserve"] == 0

    def test_ratio_clamped_above(self):
        """Ratio absurd (1.5) es satura a 0.9."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=0,
            history_chars=0,
            message_chars=0,
            document_chars=20000,
            history_ratio=1.5,
        )
        assert out["history_reserve"] == 9000

    def test_negative_available_means_no_doc(self):
        """Si l'historial + system + msg + buffer ja excedeixen el màxim, doc no s'envia."""
        out = compute_context_budget(
            max_context_chars=5000,
            system_chars=2000,
            history_chars=4000,
            message_chars=500,
            document_chars=10000,
            history_ratio=0.30,
        )
        assert out["available_chars"] < 0
        assert out["doc_kept_chars"] == 0
        assert out["doc_truncated_pct"] == 0

    def test_default_ratio_is_30_percent(self):
        """Reserva per defecte = 30% del context."""
        out = compute_context_budget(
            max_context_chars=24000,
            system_chars=0,
            history_chars=0,
            message_chars=0,
            document_chars=0,
        )
        assert out["history_reserve"] == 7200
