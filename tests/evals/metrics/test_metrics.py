from __future__ import annotations

import unittest

from tests.evals.metrics.generation import answer_correctness, faithfulness
from tests.evals.metrics.retrieval import ndcg_at_k, reciprocal_rank


class EvaluationMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.case = {
            "expected_answer": "支持扫码签名和协同签名",
            "expected_chunk_ids": [2],
            "answerable": True,
        }
        self.results = [
            {"id": 1, "content": "其他内容"},
            {"id": 2, "content": "支持扫码签名和协同签名"},
        ]

    def test_rank_metrics(self) -> None:
        self.assertEqual(reciprocal_rank(self.results, self.case), 0.5)
        self.assertGreater(ndcg_at_k(self.results, self.case, 2), 0)

    def test_generation_metrics(self) -> None:
        answer = "支持扫码签名和协同签名。"
        self.assertGreater(answer_correctness(answer, self.case), 0.5)
        self.assertEqual(faithfulness(answer, "支持扫码签名和协同签名"), 1.0)
