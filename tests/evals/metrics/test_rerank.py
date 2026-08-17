from __future__ import annotations

import unittest

from app.rag.rerank import _parse_results


class RerankProtocolTest(unittest.TestCase):
    def test_parse_standard_rerank_response(self) -> None:
        chunks = [
            {"id": 1, "content": "first", "score": 0.2},
            {"id": 2, "content": "second", "score": 0.3},
        ]
        result = _parse_results(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.12},
                ]
            },
            chunks,
        )
        self.assertEqual([item["id"] for item in result], [2, 1])
        self.assertEqual(result[0]["vector_score"], 0.3)
        self.assertEqual(result[0]["score"], 0.91)


if __name__ == "__main__":
    unittest.main()
