import unittest

from app.schemas.knowledge_base_user import (
    KnowledgeBaseUserBatchRequest,
    KnowledgeBaseUserRequest,
)


class KnowledgeBaseUserSchemaTest(unittest.TestCase):
    def test_request(self):
        request = KnowledgeBaseUserRequest(user_id=12)

        self.assertEqual(request.user_id, 12)

    def test_request_rejects_invalid_user(self):
        with self.assertRaises(ValueError):
            KnowledgeBaseUserRequest(user_id=0)

    def test_batch_request(self):
        request = KnowledgeBaseUserBatchRequest(user_ids=[12, 13])

        self.assertEqual(request.user_ids, [12, 13])

    def test_batch_request_requires_users(self):
        with self.assertRaises(ValueError):
            KnowledgeBaseUserBatchRequest(user_ids=[])


if __name__ == "__main__":
    unittest.main()
