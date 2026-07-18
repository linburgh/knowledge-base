from __future__ import annotations

import re
from typing import Any

from sqlalchemy import case, func, or_, select

from app.db.models import Document, DocumentChunk

DOCUMENT_STATUS_READY = "ready"
MAX_QUERY_TERMS = 12


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _query_terms(query: str) -> list[str]:
    normalized = " ".join(query.split())
    terms = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    values: list[str] = []
    for value in [normalized, *terms]:
        if value and value not in values:
            values.append(value)
    return values[:MAX_QUERY_TERMS]


def _chunk_columns() -> list[Any]:
    return [
        DocumentChunk.c.id,
        DocumentChunk.c.kb_id,
        DocumentChunk.c.document_id,
        DocumentChunk.c.chunk_index,
        DocumentChunk.c.content,
        DocumentChunk.c.source_name,
        DocumentChunk.c.page,
        DocumentChunk.c.section,
        DocumentChunk.c.start_index,
        DocumentChunk.c.token_count,
        DocumentChunk.c.metadata,
    ]


def _base_query(kb_id: int):
    return (
        select(*_chunk_columns())
        .select_from(
            DocumentChunk.join(
                Document,
                Document.c.id == DocumentChunk.c.document_id,
            )
        )
        .where(
            DocumentChunk.c.kb_id == kb_id,
            Document.c.kb_id == kb_id,
            Document.c.status == DOCUMENT_STATUS_READY,
            func.length(func.trim(DocumentChunk.c.content)) > 0,
        )
    )


def _serialize_chunk(row: dict[str, Any], score: float, distance: float | None = None) -> dict:
    item = dict(row)
    item["metadata"] = item.get("metadata") or {}
    item["score"] = float(score)
    item["distance"] = float(distance) if distance is not None else None
    return item


async def keyword_search(db, kb_id: int, query: str, top_k: int) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    patterns = [f"%{_escape_like(term)}%" for term in terms]
    matches = [DocumentChunk.c.content.ilike(pattern, escape="\\") for pattern in patterns]
    score_expression = sum(
        (case((match, 1), else_=0) for match in matches),
    ).label("keyword_score")

    statement = _base_query(kb_id).add_columns(score_expression).where(or_(*matches))
    statement = statement.order_by(score_expression.desc(), DocumentChunk.c.chunk_index.asc())
    statement = statement.limit(top_k)

    rows = await db.fetch_all(statement)
    result = []
    for row in rows:
        data = dict(row)
        keyword_score = data.pop("keyword_score", 0)
        result.append(_serialize_chunk(data, float(keyword_score) / len(patterns)))
    return result


async def vector_search(
    db,
    kb_id: int,
    query_embedding: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    distance_expression = DocumentChunk.c.embedding.cosine_distance(query_embedding)
    score_expression = (1 - distance_expression).label("vector_score")
    statement = (
        _base_query(kb_id)
        .add_columns(distance_expression.label("vector_distance"), score_expression)
        .where(DocumentChunk.c.embedding.is_not(None))
        .order_by(distance_expression.asc(), DocumentChunk.c.chunk_index.asc())
        .limit(top_k)
    )

    rows = await db.fetch_all(statement)
    result = []
    for row in rows:
        data = dict(row)
        distance = data.pop("vector_distance", None)
        score = data.pop("vector_score", None)
        result.append(_serialize_chunk(data, float(score), float(distance)))
    return result


__all__ = ("keyword_search", "vector_search")
