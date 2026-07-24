from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


def tokens(value: str) -> set[str]:
    result: set[str] = set()
    for item in TOKEN_PATTERN.findall(value or ""):
        normalized = item.lower()
        if all("\u4e00" <= char <= "\u9fff" for char in normalized):
            result.update(char for char in normalized if char.strip())
            result.update(
                normalized[index : index + 2]
                for index in range(len(normalized) - 1)
            )
        elif len(normalized.strip()) > 1:
            result.add(normalized)
    return result


def is_relevant(chunk: dict[str, Any], case: dict[str, Any]) -> bool:
    expected_ids = {int(item) for item in case.get("expected_chunk_ids", [])}
    if expected_ids and int(chunk.get("id", -1)) in expected_ids:
        return True

    expected_sources = {str(item) for item in case.get("expected_document_names", [])}
    if expected_sources and str(chunk.get("source_name", "")) in expected_sources:
        return True

    required_terms = {str(item).lower() for item in case.get("retrieval_terms", [])}
    content = str(chunk.get("content", "")).lower()
    return bool(required_terms) and all(term in content for term in required_terms)


def recall_at_k(results: list[dict[str, Any]], cases: list[dict[str, Any]], k: int) -> float:
    if not cases:
        return 0.0
    hits = sum(
        any(is_relevant(chunk, case) for chunk in results[:k])
        for case in cases
    )
    return hits / len(cases)


def precision_at_k(results: list[dict[str, Any]], case: dict[str, Any], k: int) -> float:
    selected = results[:k]
    if not selected:
        return 0.0
    return sum(is_relevant(chunk, case) for chunk in selected) / len(selected)


def reciprocal_rank(results: list[dict[str, Any]], case: dict[str, Any]) -> float:
    for rank, chunk in enumerate(results, 1):
        if is_relevant(chunk, case):
            return 1 / rank
    return 0.0


def mean_reciprocal_rank(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get("reciprocal_rank", 0)) for row in rows) / len(rows)


def ndcg_at_k(results: list[dict[str, Any]], case: dict[str, Any], k: int) -> float:
    selected = results[:k]
    if not selected:
        return 0.0
    gains = [3 if is_relevant(chunk, case) else 0 for chunk in selected]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, 1))
    ideal = sorted(gains, reverse=True)
    idcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def context_recall(context: str, case: dict[str, Any]) -> float:
    expected = case.get("required_context_terms") or case.get("must_contain") or []
    if not expected:
        return 1.0 if context.strip() else 0.0
    normalized = context.lower()
    return sum(str(term).lower() in normalized for term in expected) / len(expected)


def average(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0
