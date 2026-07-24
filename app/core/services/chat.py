from __future__ import annotations

from typing import Any

from app.agents.agent import run_knowledge_agent
from app.agents.runtime import AgentError
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import conversation as conversation_db
from app.db import conversation_message as conversation_message_db
from app.db import knowledge_base as knowledge_base_db
from app.db import message_citation as message_citation_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.agent import AgentContext, AgentResult, AgentTask
from app.schemas.chat import ChatResponse, CitationDto, RetrievalInfoDto

STATUS_DELETED = "deleted"
STATUS_ACTIVE = "active"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


async def validate(db, kb_id: int, question: str, user_id: str) -> str:
    """校验问答参数和知识库，并返回规范化后的问题。"""
    normalized_question = common_utils.normalize_space(question)
    if not normalized_question:
        raise BusiException("question 不能为空")
    if not user_id.strip():
        raise BusiException("user_id 不能为空")
    knowledge_base = await knowledge_base_db.get(db, id=kb_id)
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

    new_id = await conversation_db.insert_(
        db,
        kb_id=kb_id,
        user_id=user_id,
        title=question[:255],
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


def _citation_values(message_id: int, kb_id: int, citation: Any) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "kb_id": kb_id,
        "document_id": citation.document_id,
        "chunk_id": citation.chunk_id,
        "source_name": citation.source_name,
        "page": citation.page,
        "snippet": citation.snippet,
        "score": citation.score,
        "rank": citation.rank,
    }


async def _build_agent_context(
    db,
    conversation: dict[str, Any],
    user_id: str,
) -> AgentContext:
    knowledge_base = await knowledge_base_db.get(db, id=conversation["kb_id"])
    if knowledge_base is None or knowledge_base.get("status") == STATUS_DELETED:
        raise BusiException("知识库不存在", status_code=404)
    return AgentContext(
        tenant_id=knowledge_base.get("tenant_id"),
        user_id=user_id,
        kb_id=conversation["kb_id"],
        conversation_id=conversation["id"],
        knowledge_base_prompt=knowledge_base.get("system_prompt"),
    )


async def _save_agent_result(
    db,
    conversation: dict[str, Any],
    user_message: dict[str, Any],
    result: AgentResult,
) -> ChatResponse:
    assistant_message = await _save_message(
        db,
        conversation,
        ROLE_ASSISTANT,
        result.answer,
        {
            "source": "chat",
            "user_message_id": user_message["id"],
            "agent_mode": result.mode,
            "retrieval_top_k": result.top_k,
            "retrieval_hit_count": result.hit_count,
            "tool_call_count": result.tool_call_count,
            "model_call_count": result.model_call_count,
            "termination_reason": result.termination_reason,
            "duration_ms": result.duration_ms,
        },
    )

    citations = []
    for citation in result.citations:
        values = _citation_values(assistant_message["id"], conversation["kb_id"], citation)
        await message_citation_db.insert_(db, **values)
        citations.append(
            CitationDto(
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                source_name=citation.source_name,
                page=citation.page,
                snippet=citation.snippet,
                score=citation.score,
                rank=citation.rank,
            )
        )

    return ChatResponse(
        conversation_id=conversation["id"],
        message_id=assistant_message["id"],
        answer=result.answer,
        citations=citations,
        retrieval=RetrievalInfoDto(
            top_k=result.top_k,
            hit_count=result.hit_count,
            mode="vector",
        ),
        status=result.status,
        termination_reason=result.termination_reason,
    )


@check_db_connected
async def chat(
    kb_id: int,
    question: str,
    user_id: str,
    conversation_id: int | None = None,
    top_k: int | None = None,
) -> ChatResponse:
    """通过用户消息事务、Agent 执行和结果事务完成一次问答。"""
    db = DB.get()
    question = await validate(db, kb_id, question, user_id)

    async with db.transaction():
        conversation = await _get_or_create_conversation(
            db,
            kb_id,
            user_id,
            question,
            conversation_id,
        )
        user_message = await _save_message(
            db,
            conversation,
            ROLE_USER,
            question,
            {"source": "chat"},
        )

    context = await _build_agent_context(db, conversation, user_id)
    try:
        result = await run_knowledge_agent(
            AgentTask(
                kb_id=kb_id,
                question=question,
                user_id=user_id,
                conversation_id=conversation["id"],
                top_k=top_k,
            ),
            context,
        )
    except AgentError as exc:
        raise BusiException(exc.public_message, status_code=exc.status_code) from exc

    async with db.transaction():
        return await _save_agent_result(db, conversation, user_message, result)


__all__ = ("validate", "chat")
