from __future__ import annotations

from typing import Any

from app.config import CONF
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.rag import embeddings, retrievers
from app.rag.rerank import rerank
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
    if mode not in {"vector", "keyword", "hybrid"}:
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
    config: dict[str, Any] | None = None,
    index_version_id: int | None = None,
) -> RetrievalResponse:
    """检索指定知识库中的相关文档分块。

    这个方法是问答链路中的“召回”阶段：它只负责找到候选 chunks，
    不负责组装 Prompt、调用聊天模型，也不负责保存会话消息或引用。

    Args:
        kb_id: 要检索的知识库 ID。权限过滤的入口也应放在这里或更早的位置。
        query: 用户问题或关键词。会先去除首尾空白，空问题直接拒绝。
        top_k: 本次最多返回多少个分块；不传时使用知识库配置的 retrieval_top_k。
        mode: vector、keyword 或 hybrid。

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
    retrieval_config = (config or {}).get("retrieval", {})
    configured_top_k = retrieval_config.get("top_k")
    limit = _top_k(top_k or configured_top_k, knowledge_base)
    configured_mode = retrieval_config.get("mode") or mode
    mode = configured_mode
    normalized_query = _validate(kb_id, query, limit, mode)

    candidate_limit = limit
    rerank_config = (config or {}).get("rerank", {})
    rerank_enabled = bool(rerank_config.get("enabled", CONF.rag.rerank_enabled))
    if rerank_enabled:
        candidate_limit = min(
            MAX_TOP_K,
            int(
                rerank_config.get("candidate_count")
                or limit * max(1, int(CONF.rag.rerank_candidate_multiplier))
            ),
        )
    vector_chunks: list[dict[str, Any]] = []
    keyword_chunks: list[dict[str, Any]] = []
    if mode in {"vector", "hybrid"}:
        vectors = await embeddings.embed_texts(
            [normalized_query],
            model=knowledge_base.get("embedding_model"),
        )
        if not vectors or not vectors[0]:
            raise BusiException("查询向量为空")
        vector_chunks = await retrievers.vector_search(
            db,
            kb_id,
            vectors[0],
            candidate_limit,
            index_version_id=index_version_id,
        )
    if mode in {"keyword", "hybrid"}:
        keyword_chunks = await retrievers.keyword_search(
            db,
            kb_id,
            normalized_query,
            candidate_limit,
            index_version_id=index_version_id,
        )
    if mode == "vector":
        chunks = vector_chunks
    elif mode == "keyword":
        chunks = keyword_chunks[:limit]
    else:
        keyword_weight = int(retrieval_config.get("keyword_weight") or 0)
        chunks = retrievers.merge_hybrid_results(
            vector_chunks,
            keyword_chunks,
            candidate_limit,
            keyword_weight,
        )
    similarity_threshold = retrieval_config.get("similarity_threshold")
    if similarity_threshold is not None and mode != "keyword":
        chunks = [
            chunk
            for chunk in chunks
            if float(chunk.get("score") or 0) >= float(similarity_threshold)
        ]
    if rerank_enabled:
        try:
            chunks = await rerank(
                normalized_query,
                chunks,
                int(rerank_config.get("final_return_count") or limit),
                model=rerank_config.get("model"),
                timeout_seconds=rerank_config.get("timeout_seconds"),
            )
        except BusiException:
            fail_strategy = rerank_config.get("fail_strategy")
            fail_open = (
                fail_strategy == "使用向量结果"
                if fail_strategy
                else CONF.rag.rerank_fail_open
            )
            if not fail_open:
                raise
            LOG.exception(
                "Rerank unavailable, using vector candidates kb_id={} model={}",
                kb_id,
                CONF.rag.rerank_model,
            )
            chunks = chunks[:limit]

    # 无论底层使用关键词还是向量，向上层暴露相同的数据结构，方便后续 Chat Service 复用。
    return RetrievalResponse(
        kb_id=kb_id,
        query=normalized_query,
        mode=mode,
        top_k=limit,
        chunks=chunks,
    )


__all__ = ("search",)
