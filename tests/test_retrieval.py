import unittest

from app.rag.retrievers import _keyword_tokens, merge_hybrid_results


class RetrieverTest(unittest.TestCase):
    def test_keyword_tokens_keep_product_terms(self):
        self.assertEqual(_keyword_tokens("医签通 V2.3"), ["医签通", "V2.3"])

    def test_merge_hybrid_results_applies_keyword_weight(self):
        vector_chunks = [
            {"id": 1, "score": 0.9, "content": "语义相近"},
            {"id": 2, "score": 0.7, "content": "向量结果"},
        ]
        keyword_chunks = [
            {"id": 2, "score": 1.0, "content": "精确命中"},
            {"id": 3, "score": 1.0, "content": "关键词结果"},
        ]

        result = merge_hybrid_results(vector_chunks, keyword_chunks, top_k=3, keyword_weight=70)

        self.assertEqual([item["id"] for item in result], [2, 3, 1])
        self.assertGreater(result[0]["score"], result[1]["score"])


if __name__ == "__main__":
    unittest.main()
