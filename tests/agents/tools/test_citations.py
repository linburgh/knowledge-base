from __future__ import annotations

import unittest

from app.agents.knowledge.tools.citations import _build_candidates, validate_citations


class CitationToolTest(unittest.TestCase):
    def test_deduplicates_and_reorders_chunks(self) -> None:
        chunks = [
            {
                "id": 8,
                "document_id": 2,
                "source_name": "a.md",
                "content": "a",
                "score": 0.9,
            },
            {
                "id": 8,
                "document_id": 2,
                "source_name": "a.md",
                "content": "a duplicate",
                "score": 0.8,
            },
        ]
        citations = _build_candidates(chunks).citations
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].rank, 1)

    def test_rejects_unknown_chunk(self) -> None:
        with self.assertRaises(ValueError):
            validate_citations(
                _build_candidates(
                    [
                        {
                            "id": 1,
                            "document_id": 2,
                            "source_name": "a.md",
                            "content": "a",
                        }
                    ]
                ).citations,
                [],
            )
