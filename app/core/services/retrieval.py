from __future__ import annotations

from typing import Any

from app.core.common.exception import BusiException
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.rag import embeddings, retrievers
from app.schemas.retrieval import RetrievalResponse

DEFAULT_TOP_K = 5
MAX_TOP_K = 50
STATUS_DELETED = "deleted"


def _validate(kb_id: int, query: str, top_k: int, mode: str) -> str:
    if not kb_id:
        raise BusiException("kb_id 不能为空")
    normalized_query = query.strip() if query else ""
    if not normalized_query:
        raise BusiException("query 不能为空")
    if top_k < 1 or top_k > MAX_TOP_K:
        raise BusiException("top_k 必须在 1 到 50 之间")
    if mode != "vector":
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
    mode: str = "vector",
) -> RetrievalResponse:
    """检索指定知识库中的相关文档分块。

    这个方法是问答链路中的“召回”阶段：它只负责找到候选 chunks，
    不负责组装 Prompt、调用聊天模型，也不负责保存会话消息或引用。

    Args:
        kb_id: 要检索的知识库 ID。权限过滤的入口也应放在这里或更早的位置。
        query: 用户问题或关键词。会先去除首尾空白，空问题直接拒绝。
        top_k: 本次最多返回多少个分块；不传时使用知识库配置的 retrieval_top_k。
        mode: 当前固定为 vector，使用 pgvector 余弦距离。

    Returns:
        包含统一检索结果结构的 RetrievalResponse，供 Search API 或 Chat Service 使用。
    """
    # @check_db_connected 会在真正进入函数前确保 DB 已连接，并把连接对象放入 DB ContextVar。
    db = DB.get()

    # 先校验知识库存在且未被软删除；不能先查全库 chunks 再做知识库过滤。
    knowledge_base = await knowledge_base_db.get(db, id=kb_id)
    if knowledge_base is None or knowledge_base.get("status") == STATUS_DELETED:
        raise BusiException("知识库不存在", status_code=404)

    # top_k 未传时沿用知识库配置，显式传入时则覆盖默认值，并统一限制范围。
    limit = _top_k(top_k, knowledge_base)
    normalized_query = _validate(kb_id, query, limit, mode)

    # 先把问题转换成向量，再交给 pgvector 按余弦距离排序。
    # 这里使用知识库保存的 embedding_model，保证问题向量与分块向量模型一致。
    vectors = await embeddings.embed_texts(
        [normalized_query],
        model=knowledge_base.get("embedding_model"),
    )
    if not vectors or not vectors[0]:
        raise BusiException("查询向量为空")
    chunks = await retrievers.vector_search(db, kb_id, vectors[0], limit)

    # 无论底层使用关键词还是向量，向上层暴露相同的数据结构，方便后续 Chat Service 复用。
    return RetrievalResponse(
        kb_id=kb_id,
        query=normalized_query,
        mode=mode,
        top_k=limit,
        chunks=chunks,
    )


__all__ = ("search",)
