"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_embeddings_recall_ab.py
Description: Esquelet test recall@N A/B regression per embedding model.
             Opció β Onada 4.6b: framework establert, dataset golden pendent.
             BACKLOG M5-tests-recall-ab-dataset.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest


class TestRecallABRegression:
    """Recall@N A/B regression per embedding model.

    Contracte: recall@5 de l'embedding model actual no pot caure més d'un 5%
    respecte al baseline golden. Detecta degradació silenciosa per canvis de
    model (int8 → altra quantització, upgrade mpnet, canvi de dims).

    BACKLOG M5-tests-recall-ab-dataset: construir dataset golden ≥50 queries
    amb recall@5/@10 baseline. Pot córrer en BUS nocturn paral·lel.
    Format esperat: tests/fixtures/recall_golden.json
    [{"query": "...", "expected_doc_ids": ["id1", "id2", ...]}]
    """

    @pytest.mark.skip(
        reason="BACKLOG M5-tests-recall-ab-dataset: dataset golden ≥50 queries pendent"
    )
    def test_recall_at_5_baseline_skip_until_golden_dataset(self):
        """Recall@5: l'embedding actual ha de superar el threshold baseline.

        Quan el dataset golden estigui disponible:
        1. Carregar fixtures de tests/fixtures/recall_golden.json
        2. Per cada query, cridar EmbeddingService.search() i recollir top-5
        3. Calcular recall@5 = len(intersecció(retornats, esperats)) / len(esperats)
        4. Afirmar recall@5_actual >= recall@5_baseline * 0.95 (dropoff màx 5%)
        """
        raise NotImplementedError(
            "Dataset golden pendent (BACKLOG M5-tests-recall-ab-dataset)"
        )

    @pytest.mark.skip(
        reason="BACKLOG M5-tests-recall-ab-dataset: dataset golden ≥50 queries pendent"
    )
    def test_recall_at_10_baseline_skip_until_golden_dataset(self):
        """Recall@10: cobertura ampliada per queries de long-tail.

        Mateixa lògica que recall@5 però avalua top-10.
        Threshold: recall@10_actual >= recall@10_baseline * 0.95
        """
        raise NotImplementedError(
            "Dataset golden pendent (BACKLOG M5-tests-recall-ab-dataset)"
        )
