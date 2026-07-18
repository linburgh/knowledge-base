from __future__ import annotations

from typing import Any

from app.core.common.exception import BusiException
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.rag import embeddings, retrievers
from app.schemas.retrieval import RetrievalMode, RetrievalResponse

DEFAULT_TOP_K = 5
MAX_TOP_K = 50
STATUS_DELETED = "deleted"


def _validate(kb_id: int, query: str, top_k: int, mode: RetrievalMode) -> str:
    if not kb_id:
        raise BusiException("kb_id 不能为空")
    normalized_query = query.strip() if query else ""
    if not normalized_query:
        raise BusiException("query 不能为空")
    if top_k < 1 or top_k > MAX_TOP_K:
        raise BusiException("top_k 必须在 1 到 50 之间")
    if mode not in {"keyword", "vector"}:
        raise BusiException("检索模式不合法")
    return normalized_query


def _top_k(value: int | None, knowledge_base: dict[str, Any]) -> int:
    result = value or knowledge_base.get("retrieval_top_k") or DEFAULT_TOP_K
    if result < 1 or result > MAX_TOP_K:
        raise BusiException("top_k 必须在 1 到 50 之间")
    return result


@check_db_connected
async def search(
    kb_id: int,
    query: str,
    top_k: int | None = None,
    mode: RetrievalMode = "keyword",
) -> RetrievalResponse:
    db = DB.get()
    knowledge_base = await knowledge_base_db.get(db, id=kb_id)
    if knowledge_base is None or knowledge_base.get("status") == STATUS_DELETED:
        raise BusiException("知识库不存在", status_code=404)

    limit = _top_k(top_k, knowledge_base)
    normalized_query = _validate(kb_id, query, limit, mode)
    if mode == "keyword":
        chunks = await retrievers.keyword_search(db, kb_id, normalized_query, limit)
    else:
        vectors = await embeddings.embed_texts(
            [normalized_query],
            model=knowledge_base.get("embedding_model"),
        )
        if not vectors or not vectors[0]:
            raise BusiException("查询向量为空")
        chunks = await retrievers.vector_search(db, kb_id, vectors[0], limit)

    return RetrievalResponse(
        kb_id=kb_id,
        query=normalized_query,
        mode=mode,
        top_k=limit,
        chunks=chunks,
    )


__all__ = ("search",)
