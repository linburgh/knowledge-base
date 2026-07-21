from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KnowledgeBaseOverviewMetrics(BaseModel):
    document_total: int
    chunk_total: int
    vector_total: int
    indexing_failed_total: int


class KnowledgeBaseDocumentTrendPoint(BaseModel):
    date: datetime
    new_documents: int
    indexed_documents: int


class KnowledgeBaseDocumentStatus(BaseModel):
    status: str
    total: int


class KnowledgeBaseQaTrendPoint(BaseModel):
    date: datetime
    question_total: int
    active_session_total: int


class KnowledgeBaseQuality(BaseModel):
    average_similarity: float | None
    low_similarity_question_total: int
    no_citation_answer_total: int


class KnowledgeBaseHotQuestion(BaseModel):
    question: str
    total: int


class KnowledgeBaseDocumentRanking(BaseModel):
    document_id: int
    document_name: str
    reference_total: int


class KnowledgeBaseActivity(BaseModel):
    id: int
    actor_id: str
    action: str
    action_cn: str
    target_type: str
    target_id: str | None = None
    result: str
    created_at: datetime


class KnowledgeBaseOverviewResponse(BaseModel):
    kb_id: int
    range: str
    start_at: datetime
    end_at: datetime
    metrics: KnowledgeBaseOverviewMetrics
    document_trend: list[KnowledgeBaseDocumentTrendPoint]
    document_status: list[KnowledgeBaseDocumentStatus]
    qa_trend: list[KnowledgeBaseQaTrendPoint]
    quality: KnowledgeBaseQuality
    hot_questions: list[KnowledgeBaseHotQuestion]
    document_ranking: list[KnowledgeBaseDocumentRanking]
    recent_activities: list[KnowledgeBaseActivity]


__all__ = ("KnowledgeBaseOverviewResponse",)
