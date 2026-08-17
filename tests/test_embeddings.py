import asyncio
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

    async def test_embed_chunks_uses_bounded_concurrency(self):
        active = 0
        maximum_active = 0

        async def fake_embed_texts(texts, model):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.005)
            active -= 1
            return [[float(index)] for index, _ in enumerate(texts)]

        chunks = [{"content": f"chunk-{index}"} for index in range(20)]
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts) as mocked:
            result = await embeddings.embed_chunks(
                chunks,
                "test-embedding",
                batch_size=2,
                concurrency=3,
                retry_count=0,
            )

        self.assertLessEqual(maximum_active, 3)
        self.assertEqual(mocked.await_count, 10)
        self.assertEqual(len(result), len(chunks))
