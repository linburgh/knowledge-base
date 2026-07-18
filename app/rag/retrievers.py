from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db.models import Document, DocumentChunk

DOCUMENT_STATUS_READY = "ready"
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


async def vector_search(
    db,
    kb_id: int,
    query_embedding: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """使用 pgvector 从指定知识库召回最相似的文档分块。

    ``query_embedding`` 是用户问题生成的向量。数据库使用分块向量与它的
    cosine_distance 计算距离；距离越小表示越相似，因此按距离升序取前
    ``top_k`` 条。同时只保留当前 ``kb_id`` 且已经存在 embedding 的分块。

    返回结果会统一转换为检索分块结构，其中：

    - ``distance`` 表示 pgvector 计算出的余弦距离；
    - ``score`` 使用 ``1 - distance`` 转换为越大越相关；
    - 其余字段用于后续上下文组装和 citation 保存。
    """
    # 构造 pgvector 的余弦距离表达式：距离越小，说明分块向量与问题向量越相似。
    distance_expression = DocumentChunk.c.embedding.cosine_distance(query_embedding)
    # 将距离转换成相似度分数，分数越大越相关，并给结果列命名为 vector_score。
    score_expression = (1 - distance_expression).label("vector_score")
    # 以基础查询为起点，基础查询已经包含 kb_id、ready 文档和非空内容过滤。
    # 最终生成的参数化 SQL 结构如下：
    #
    # SELECT t_document_chunk.id, t_document_chunk.kb_id,
    #        t_document_chunk.document_id, t_document_chunk.chunk_index,
    #        t_document_chunk.content, t_document_chunk.source_name,
    #        t_document_chunk.page, t_document_chunk.section,
    #        t_document_chunk.start_index, t_document_chunk.token_count,
    #        t_document_chunk.metadata,
    #        t_document_chunk.embedding <=> :embedding AS vector_distance,
    #        1 - (t_document_chunk.embedding <=> :embedding) AS vector_score
    # FROM t_document_chunk
    # JOIN t_document ON t_document.id = t_document_chunk.document_id
    # WHERE t_document_chunk.kb_id = :kb_id
    #   AND t_document.kb_id = :kb_id
    #   AND t_document.status = 'ready'
    #   AND length(trim(t_document_chunk.content)) > 0
    #   AND t_document_chunk.embedding IS NOT NULL
    # ORDER BY t_document_chunk.embedding <=> :embedding ASC,
    #          t_document_chunk.chunk_index ASC
    # LIMIT :top_k;
    statement = (
        _base_query(kb_id)
        # 额外返回原始距离和相似度，供接口响应和后续排序/引用使用。
        .add_columns(distance_expression.label("vector_distance"), score_expression)
        # 只保留已经生成 embedding 的分块，避免 NULL 无法参与向量计算。
        .where(DocumentChunk.c.embedding.is_not(None))
        # 先按余弦距离升序排列；距离相同则按文档内分块顺序排列。
        .order_by(distance_expression.asc(), DocumentChunk.c.chunk_index.asc())
        # 限制最多返回 top_k 条，避免把整个知识库内容交给上层。
        .limit(top_k)
    )

    # 执行参数化 SQL，db 层会把 query_embedding、kb_id 和 top_k 作为绑定参数传给 PostgreSQL。
    rows = await db.fetch_all(statement)
    # 准备把数据库行转换成统一的检索结果字典。
    result = []
    for row in rows:
        # databases 返回的 Row 转成普通字典，方便移除中间计算字段。
        data = dict(row)
        # 取出 pgvector 计算的原始余弦距离。
        distance = data.pop("vector_distance", None)
        # 取出上面构造的相似度分数。
        score = data.pop("vector_score", None)
        # 将 Decimal/数据库数值转换为 Python float，并合并回标准 chunk 结构。
        result.append(_serialize_chunk(data, float(score), float(distance)))
    # 返回按相关性排序后的检索分块列表。
    return result


__all__ = ("vector_search",)
