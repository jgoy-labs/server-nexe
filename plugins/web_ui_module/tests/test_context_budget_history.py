"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_context_budget_history.py
Description: Bug 32 — Tests for the dynamic context window budget.
             Verifies that a large document does NOT truncate the conversation history,
             but rather the document is truncated to preserve the minimum
             history reserve (NEXE_HISTORY_CONTEXT_RATIO).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


from plugins.web_ui_module.api.routes_chat import compute_context_budget


class TestComputeContextBudget:
    """Bug 32 — context budget that preserves history."""

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
        """Bug 32 core: huge PDF + long history -> document truncated, history intact."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=3000,  # historial real
            message_chars=200,
            document_chars=50000,  # PDF of ~573 chunks, very large
            history_ratio=0.30,
        )
        # Effective history = max(3000, 30%*10000=3000) = 3000
        assert out["history_effective"] == 3000
        # Available for doc = 10000 - 500 - 3000 - 200 - 500 = 5800
        assert out["available_chars"] == 5800
        # Document truncated
        assert out["doc_truncated_pct"] > 0
        assert out["doc_kept_chars"] == 5800

    def test_history_below_reserve_uses_reserve(self):
        """If the actual history is smaller than the reserve, the budget reserves it anyway."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=500,  # historial petit
            message_chars=200,
            document_chars=8000,
            history_ratio=0.30,
        )
        # Reserve = 3000
        assert out["history_reserve"] == 3000
        assert out["history_effective"] == 3000  # max(500, 3000)
        # Available = 10000 - 500 - 3000 - 200 - 500 = 5800
        assert out["available_chars"] == 5800
        # Doc 8000 -> truncated to 5800
        assert out["doc_kept_chars"] == 5800
        assert out["doc_truncated_pct"] == round((1 - 5800 / 8000) * 100)

    def test_history_above_reserve_not_truncated(self):
        """If the actual history is larger than the reserve, it is NOT truncated."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=5000,  # exceeds reserve
            message_chars=200,
            document_chars=8000,
            history_ratio=0.30,
        )
        # Effective history = max(5000, 3000) = 5000 (real, not truncated)
        assert out["history_effective"] == 5000
        # Available = 10000 - 500 - 5000 - 200 - 500 = 3800
        assert out["available_chars"] == 3800
        # Document truncated to 3800
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
        """New session (no history) + huge doc: the reserve still applies."""
        out = compute_context_budget(
            max_context_chars=10000,
            system_chars=500,
            history_chars=0,
            message_chars=200,
            document_chars=20000,
            history_ratio=0.30,
        )
        # Reserve of 3000 guarantees that new questions will have history space
        assert out["history_effective"] == 3000
        assert out["available_chars"] == 5800

    def test_ratio_clamped_below(self):
        """Negative ratio is clamped to 0."""
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
        """Absurd ratio (1.5) is clamped to 0.9."""
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
        """If history + system + msg + buffer already exceed the maximum, doc is not sent."""
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
        """Default reserve = 30% of context."""
        out = compute_context_budget(
            max_context_chars=24000,
            system_chars=0,
            history_chars=0,
            message_chars=0,
            document_chars=0,
        )
        assert out["history_reserve"] == 7200
