from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from app.db.models import (
    AuditLog,
    Conversation,
    ConversationMessage,
    Document,
    DocumentChunk,
    IndexingTask,
    MessageCitation,
)

DOCUMENT_STATUSES = ("pending", "processing", "ready", "failed")
LOW_SIMILARITY_THRESHOLD = 0.5


async def metrics(db, kb_id: int) -> dict[str, int]:
    document_scope = sa.and_(Document.c.kb_id == kb_id, Document.c.status != "deleted")
    chunk_source = DocumentChunk.join(
        Document,
        sa.and_(
            Document.c.id == DocumentChunk.c.document_id,
            Document.c.kb_id == kb_id,
            Document.c.status != "deleted",
        ),
    )
    chunk_scope = DocumentChunk.c.kb_id == kb_id
    queries = {
        "document_total": sa.select(sa.func.count()).select_from(Document).where(document_scope),
        "chunk_total": sa.select(sa.func.count()).select_from(chunk_source).where(chunk_scope),
        "vector_total": sa.select(sa.func.count())
        .select_from(chunk_source)
        .where(chunk_scope, DocumentChunk.c.embedding.is_not(None)),
        "indexing_failed_total": sa.select(sa.func.count(sa.distinct(Document.c.id)))
        .select_from(Document)
        .where(document_scope, Document.c.status == "failed"),
    }
    return {name: int(await db.fetch_val(query) or 0) for name, query in queries.items()}


async def document_trend(
    db, kb_id: int, start_at: datetime, end_at: datetime
) -> list[dict[str, Any]]:
    created_date = sa.func.date_trunc("day", Document.c.created_at).label("date")
    indexed_date = sa.func.date_trunc("day", IndexingTask.c.finished_at).label("date")
    created_rows = await db.fetch_all(
        sa.select(created_date, sa.func.count().label("total"))
        .where(
            Document.c.kb_id == kb_id,
            Document.c.status != "deleted",
            Document.c.created_at >= start_at,
            Document.c.created_at < end_at,
        )
        .group_by(created_date)
    )
    indexed_rows = await db.fetch_all(
        sa.select(
            indexed_date,
            sa.func.count(sa.distinct(IndexingTask.c.document_id)).label("total"),
        )
        .where(
            IndexingTask.c.kb_id == kb_id,
            IndexingTask.c.status == "succeeded",
            IndexingTask.c.finished_at.is_not(None),
            IndexingTask.c.finished_at >= start_at,
            IndexingTask.c.finished_at < end_at,
        )
        .group_by(indexed_date)
    )
    created_map = {row["date"]: int(row["total"]) for row in created_rows}
    indexed_map = {row["date"]: int(row["total"]) for row in indexed_rows}
    return _merge_daily(
        start_at,
        end_at,
        created_map,
        indexed_map,
        "new_documents",
        "indexed_documents",
    )


async def document_status(db, kb_id: int) -> list[dict[str, Any]]:
    query = (
        sa.select(Document.c.status, sa.func.count().label("total"))
        .where(Document.c.kb_id == kb_id, Document.c.status != "deleted")
        .group_by(Document.c.status)
    )
    rows = {row["status"]: int(row["total"]) for row in await db.fetch_all(query)}
    return [{"status": status, "total": rows.get(status, 0)} for status in DOCUMENT_STATUSES]


async def qa_trend(db, kb_id: int, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    date_column = sa.func.date_trunc("day", ConversationMessage.c.created_at).label("date")
    query = (
        sa.select(
            date_column,
            sa.func.count().label("question_total"),
            sa.func.count(sa.distinct(ConversationMessage.c.conversation_id)).label("active_session_total"),
        )
        .select_from(
            ConversationMessage.join(
                Conversation,
                sa.and_(
                    Conversation.c.id == ConversationMessage.c.conversation_id,
                    Conversation.c.kb_id == kb_id,
                    Conversation.c.status != "deleted",
                ),
            )
        )
        .where(
            ConversationMessage.c.kb_id == kb_id,
            ConversationMessage.c.role == "user",
            ConversationMessage.c.created_at >= start_at,
            ConversationMessage.c.created_at < end_at,
        )
        .group_by(date_column)
    )
    rows = await db.fetch_all(query)
    question_map = {row["date"]: int(row["question_total"]) for row in rows}
    session_map = {row["date"]: int(row["active_session_total"]) for row in rows}
    return _merge_daily(
        start_at,
        end_at,
        question_map,
        session_map,
        "question_total",
        "active_session_total",
    )


async def quality(db, kb_id: int, start_at: datetime, end_at: datetime) -> dict[str, Any]:
    assistant = ConversationMessage.alias("assistant_message")
    average_query = (
        sa.select(sa.func.avg(MessageCitation.c.score))
        .select_from(
            MessageCitation.join(
                assistant,
                sa.and_(
                    assistant.c.id == MessageCitation.c.message_id,
                    assistant.c.kb_id == kb_id,
                    assistant.c.role == "assistant",
                ),
            )
        )
        .where(
            MessageCitation.c.kb_id == kb_id,
            MessageCitation.c.score.is_not(None),
            assistant.c.created_at >= start_at,
            assistant.c.created_at < end_at,
        )
    )
    average = await db.fetch_val(average_query)

    citation_average = sa.func.avg(MessageCitation.c.score).label("average_score")
    low_query = (
        sa.select(sa.func.count())
        .select_from(
            sa.select(MessageCitation.c.message_id)
            .select_from(
                MessageCitation.join(
                    assistant,
                    sa.and_(
                        assistant.c.id == MessageCitation.c.message_id,
                        assistant.c.kb_id == kb_id,
                        assistant.c.role == "assistant",
                    ),
                )
            )
            .where(
                MessageCitation.c.kb_id == kb_id,
                MessageCitation.c.score.is_not(None),
                assistant.c.created_at >= start_at,
                assistant.c.created_at < end_at,
            )
            .group_by(MessageCitation.c.message_id)
            .having(citation_average < LOW_SIMILARITY_THRESHOLD)
            .subquery()
        )
    )
    no_citation_query = (
        sa.select(sa.func.count())
        .select_from(ConversationMessage)
        .where(
            ConversationMessage.c.kb_id == kb_id,
            ConversationMessage.c.role == "assistant",
            ConversationMessage.c.created_at >= start_at,
            ConversationMessage.c.created_at < end_at,
            ~sa.exists(
                sa.select(1).where(
                    MessageCitation.c.kb_id == kb_id,
                    MessageCitation.c.message_id == ConversationMessage.c.id,
                )
            ),
        )
    )
    return {
        "average_similarity": float(average) if average is not None else None,
        "low_similarity_question_total": int(await db.fetch_val(low_query) or 0),
        "no_citation_answer_total": int(await db.fetch_val(no_citation_query) or 0),
    }


async def hot_questions(
    db, kb_id: int, start_at: datetime, end_at: datetime, limit: int = 5
) -> list[dict[str, Any]]:
    normalized = sa.func.trim(ConversationMessage.c.content).label("question")
    query = (
        sa.select(normalized, sa.func.count().label("total"))
        .where(
            ConversationMessage.c.kb_id == kb_id,
            ConversationMessage.c.role == "user",
            sa.func.length(sa.func.trim(ConversationMessage.c.content)) > 0,
            ConversationMessage.c.created_at >= start_at,
            ConversationMessage.c.created_at < end_at,
        )
        .group_by(normalized)
        .order_by(sa.desc("total"), normalized.asc())
        .limit(limit)
    )
    return [
        {"question": row["question"], "total": int(row["total"])}
        for row in await db.fetch_all(query)
    ]


async def document_ranking(
    db, kb_id: int, start_at: datetime, end_at: datetime, limit: int = 5
) -> list[dict[str, Any]]:
    query = (
        sa.select(
            MessageCitation.c.document_id,
            MessageCitation.c.source_name.label("document_name"),
            sa.func.count().label("reference_total"),
        )
        .where(
            MessageCitation.c.kb_id == kb_id,
            MessageCitation.c.created_at >= start_at,
            MessageCitation.c.created_at < end_at,
        )
        .group_by(MessageCitation.c.document_id, MessageCitation.c.source_name)
        .order_by(sa.desc("reference_total"), MessageCitation.c.document_id.asc())
        .limit(limit)
    )
    return [
        dict(row) | {"reference_total": int(row["reference_total"])}
        for row in await db.fetch_all(query)
    ]


async def recent_activities(db, kb_id: int, limit: int = 5) -> list[dict[str, Any]]:
    document_ids = sa.select(sa.cast(Document.c.id, sa.String)).where(
        Document.c.kb_id == kb_id,
        Document.c.status != "deleted",
    )
    conversation_ids = sa.select(sa.cast(Conversation.c.id, sa.String)).where(
        Conversation.c.kb_id == kb_id,
        Conversation.c.status != "deleted",
    )
    query = (
        sa.select(
            AuditLog.c.id,
            AuditLog.c.actor_id,
            AuditLog.c.action,
            AuditLog.c.target_type,
            AuditLog.c.target_id,
            AuditLog.c.result,
            AuditLog.c.created_at,
        )
        .where(
            sa.or_(
                AuditLog.c.request_summary["kb_id"].as_string() == str(kb_id),
                AuditLog.c.request_summary["knowledge_base_id"].as_string() == str(kb_id),
                sa.and_(
                    AuditLog.c.target_type == "knowledge_base",
                    AuditLog.c.target_id == str(kb_id),
                ),
                sa.and_(
                    AuditLog.c.target_type == "document",
                    AuditLog.c.target_id.in_(document_ids),
                ),
                sa.and_(
                    AuditLog.c.target_type == "conversation",
                    AuditLog.c.target_id.in_(conversation_ids),
                ),
            )
        )
        .order_by(AuditLog.c.created_at.desc(), AuditLog.c.id.desc())
        .limit(limit)
    )
    return [dict(row) for row in await db.fetch_all(query)]


def _merge_daily(
    start_at: datetime,
    end_at: datetime,
    first_map: dict[datetime, int],
    second_map: dict[datetime, int],
    first_name: str,
    second_name: str,
) -> list[dict[str, Any]]:
    values = []
    current = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end_at.replace(hour=0, minute=0, second=0, microsecond=0)
    while current < last:
        values.append(
            {
                "date": current,
                first_name: first_map.get(current, 0),
                second_name: second_map.get(current, 0),
            }
        )
        current += timedelta(days=1)
    return values


__all__ = (
    "document_ranking",
    "document_status",
    "document_trend",
    "hot_questions",
    "metrics",
    "qa_trend",
    "quality",
    "recent_activities",
)
