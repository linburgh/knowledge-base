import unittest

from app.core.common.exception import BusiException
from app.core.services.knowledge_base_qa_config import default_config, validate_config


class KnowledgeBaseQaConfigTest(unittest.TestCase):
    def test_default_config_is_valid(self):
        config = default_config()

        validate_config(config)

    def test_chunk_overlap_must_be_less_than_chunk_size(self):
        config = default_config()
        config["document"]["chunk_overlap"] = config["document"]["chunk_size"]

        with self.assertRaisesRegex(BusiException, "chunk_overlap"):
            validate_config(config)

    def test_final_return_count_cannot_exceed_candidates(self):
        config = default_config()
        config["rerank"]["final_return_count"] = config["rerank"]["candidate_count"] + 1

        with self.assertRaisesRegex(BusiException, "final_return_count"):
            validate_config(config)

    def test_hybrid_retrieval_requires_hybrid_mode(self):
        config = default_config()
        config["retrieval"]["hybrid_enabled"] = True

        with self.assertRaisesRegex(BusiException, "hybrid"):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
