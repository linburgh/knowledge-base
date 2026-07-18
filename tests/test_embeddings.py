import unittest
from unittest import mock

from app.rag import embeddings


class EmbeddingsTest(unittest.IsolatedAsyncioTestCase):
    async def test_embed_chunks_adds_embedding_fields(self):
        chunks = [
            {"content": "hello", "chunk_index": 0},
            {"content": "world", "chunk_index": 1},
        ]

        with mock.patch.object(
            embeddings,
            "embed_texts",
            return_value=[[0.1, 0.2], [0.3, 0.4]],
        ) as embed_texts:
            result = await embeddings.embed_chunks(chunks, "test-embedding")

        embed_texts.assert_awaited_once_with(["hello", "world"], "test-embedding")
        self.assertEqual(result[0]["embedding_model"], "test-embedding")
        self.assertEqual(result[0]["embedding"], [0.1, 0.2])
        self.assertEqual(result[1]["embedding"], [0.3, 0.4])
        self.assertNotIn("embedding", chunks[0])
