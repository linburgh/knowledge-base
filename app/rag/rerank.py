from __future__ import annotations

import re
from typing import Any

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


def _tokens(value: str) -> set[str]:
    result: set[str] = set()
    for item in TOKEN_PATTERN.findall(value or ""):
        item = item.lower()
        if all("\u4e00" <= char <= "\u9fff" for char in item):
            result.update(item)
            result.update(item[index : index + 2] for index in range(len(item) - 1))
        elif len(item) > 1:
            result.add(item)
    return result


def rerank(query: str, chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """在向量候选集上做轻量词项重排，保持向量分数并记录重排分数。"""
    query_terms = _tokens(query)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, chunk in enumerate(chunks):
        vector_score = float(chunk.get("score") or 0.0)
        content_terms = _tokens(
            f"{chunk.get('source_name', '')} {chunk.get('content', '')}"
        )
        overlap = len(query_terms & content_terms) / len(query_terms) if query_terms else 0.0
        phrase_bonus = (
            0.1
            if query.strip() and query.strip() in str(chunk.get("content", ""))
            else 0.0
        )
        rerank_score = vector_score * 0.75 + overlap * 0.2 + phrase_bonus
        item = dict(chunk)
        item["vector_score"] = vector_score
        item["score"] = rerank_score
        scored.append((rerank_score, index, item))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


__all__ = ("rerank",)
