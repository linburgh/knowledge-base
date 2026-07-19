from __future__ import annotations

from typing import Any

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import retrieval as retrieval_service
from app.db import conversation as conversation_db
from app.db import conversation_message as conversation_message_db
from app.db import knowledge_base as knowledge_base_db
from app.db import message_citation as message_citation_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.rag import chains
from app.schemas.chat import ChatResponse, CitationDto, RetrievalInfoDto

STATUS_DELETED = "deleted"
STATUS_ACTIVE = "active"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


async def validate(
    db,
    kb_id: int,
    question: str,
    user_id: str,
) -> str:
    """校验问答参数和知识库，并返回规范化后的问题。"""
    # 统一折叠连续空白并去除问题首尾空格。
    normalized_question = common_utils.normalize_space(question)
    # 问题为空时不继续创建会话或调用检索。
    if not normalized_question:
        raise BusiException("question 不能为空")
    # 用户 ID 用于会话归属校验，不能使用空白字符串。
    if not user_id.strip():
        raise BusiException("user_id 不能为空")

    # 查询知识库，确保后续会话和检索都绑定到有效知识库。
    knowledge_base = await knowledge_base_db.get(db, id=kb_id)
    # 不允许对不存在或已经软删除的知识库发起问答。
    if knowledge_base is None or knowledge_base.get("status") == STATUS_DELETED:
        raise BusiException("知识库不存在", status_code=404)
    return normalized_question


async def _get_or_create_conversation(
    db,
    kb_id: int,
    user_id: str,
    question: str,
    conversation_id: int | None,
) -> dict[str, Any]:
    if conversation_id is not None:
        conversation = await conversation_db.get(db, id=conversation_id)
        if (
            conversation is None
            or conversation["kb_id"] != kb_id
            or conversation["user_id"] != user_id
            or conversation["status"] == STATUS_DELETED
        ):
            raise BusiException("会话不存在", status_code=404)
        return conversation

    title = question[:255]
    new_id = await conversation_db.insert_(
        db,
        kb_id=kb_id,
        user_id=user_id,
        title=title,
        status=STATUS_ACTIVE,
    )
    conversation = await conversation_db.get(db, id=new_id)
    if conversation is None:
        raise BusiException("会话创建失败")
    return conversation


async def _save_message(
    db,
    conversation: dict[str, Any],
    role: str,
    content: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    message_id = await conversation_message_db.insert_(
        db,
        conversation_id=conversation["id"],
        kb_id=conversation["kb_id"],
        user_id=conversation["user_id"],
        role=role,
        content=content,
        metadata=metadata,
    )
    message = await conversation_message_db.get(db, id=message_id)
    if message is None:
        raise BusiException("消息保存失败")
    return message


def _citation_values(
    message_id: int,
    kb_id: int,
    chunk: dict[str, Any],
    rank: int,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "kb_id": kb_id,
        "document_id": chunk["document_id"],
        "chunk_id": chunk["id"],
        "source_name": chunk["source_name"],
        "page": chunk.get("page"),
        "snippet": chunk["content"],
        "score": chunk.get("score"),
        "rank": rank,
    }


async def _chat_in_transaction(
    db,
    kb_id: int,
    question: str,
    user_id: str,
    conversation_id: int | None,
    top_k: int | None,
) -> ChatResponse:
    # 有 conversation_id 时复用并校验会话；没有时创建当前用户的新会话。
    conversation = await _get_or_create_conversation(
        db, kb_id, user_id, question, conversation_id
    )
    # 先保存用户问题，保证问答历史中存在本次请求的原始输入。
    user_message = await _save_message(
        db, conversation, ROLE_USER, question, {"source": "chat"}
    )
    # 调用 Retrieval Service，根据问题召回当前知识库中的向量分块。
    retrieval = await retrieval_service.search(kb_id, question, top_k=top_k)
    # 将 Pydantic 分块对象转换为普通字典，供 Chain 组装上下文和保存引用。
    chunks = [chunk.model_dump() for chunk in retrieval.chunks]
    # 读取当前知识库独立提示词，确保不同知识库的回答规则互不污染。
    knowledge_base = await knowledge_base_db.get(db, id=kb_id)
    if knowledge_base is None or knowledge_base.get("status") == STATUS_DELETED:
        raise BusiException("知识库不存在", status_code=404)
    # 将知识库提示词、问题和召回分块交给 RAG Chain，生成最终答案。
    answer = await chains.generate_answer(
        question,
        chunks,
        system_prompt=knowledge_base.get("system_prompt"),
    )
    # 保存模型生成的 assistant 消息，并把检索参数写入 metadata。
    assistant_message = await _save_message(
        db,
        conversation,
        ROLE_ASSISTANT,
        answer,
        {
            "source": "chat",
            "user_message_id": user_message["id"],
            "retrieval_mode": retrieval.mode,
            "retrieval_top_k": retrieval.top_k,
            "retrieval_hit_count": len(chunks),
        },
    )

    # 准备返回给接口调用方的引用列表，并按检索顺序生成 rank。
    citations = []
    for rank, chunk in enumerate(chunks, start=1):
        # 组装并保存引用，引用关联到助手回答消息。
        values = _citation_values(assistant_message["id"], kb_id, chunk, rank)
        await message_citation_db.insert_(db, **values)
        citations.append(
            CitationDto(
                document_id=values["document_id"],
                chunk_id=values["chunk_id"],
                source_name=values["source_name"],
                page=values["page"],
                snippet=values["snippet"],
                score=values["score"],
                rank=rank,
            )
        )

    # 返回会话、助手消息、答案、引用和检索摘要。
    return ChatResponse(
        conversation_id=conversation["id"],
        message_id=assistant_message["id"],
        answer=answer,
        citations=citations,
        retrieval=RetrievalInfoDto(
            top_k=retrieval.top_k,
            hit_count=len(chunks),
            mode=retrieval.mode,
        ),
    )


@check_db_connected
async def chat(
    kb_id: int,
    question: str,
    user_id: str,
    conversation_id: int | None = None,
    top_k: int | None = None,
) -> ChatResponse:
    """在单个数据库事务中编排一次完整的知识库问答流程。"""
    # @check_db_connected 已经确保数据库连接可用，这里取得当前请求的连接对象。
    db = DB.get()
    # 在开启事务前完成纯参数和知识库校验，避免无效请求开启事务。
    question = await validate(db, kb_id, question, user_id)
    # 会话、消息和引用在同一个事务中提交；任一步失败都会整体回滚。
    async with db.transaction():
        # 在事务内完成会话处理、检索、模型调用、消息和引用落库。
        return await _chat_in_transaction(
            db,
            kb_id,
            question,
            user_id,
            conversation_id,
            top_k,
        )


__all__ = ("validate", "chat")
