import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()


KnowledgeBase = sa.Table(
    "t_knowledge_base",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("description", sa.String(500), nullable=False, server_default=sa.text("''")),
    sa.Column("owner_id", sa.String(128), nullable=False),
    sa.Column("visibility", sa.String(32), nullable=False),
    sa.Column("embedding_model", sa.String(128), nullable=False),
    sa.Column("chunk_size", sa.Integer, nullable=False),
    sa.Column("chunk_overlap", sa.Integer, nullable=False),
    sa.Column("retrieval_top_k", sa.Integer, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_knowledge_base_owner_id", "owner_id"),
    sa.Index("idx_t_knowledge_base_status", "status"),
)


Document = sa.Table(
    "t_document",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("source_type", sa.String(32), nullable=False),
    sa.Column("source_name", sa.String(512), nullable=False),
    sa.Column("source_uri", sa.Text),
    sa.Column("content_type", sa.String(128), nullable=False),
    sa.Column("object_path", sa.String(1024), nullable=False),
    sa.Column("file_size", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("content_hash", sa.String(128), nullable=False),
    sa.Column("parser", sa.String(128)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("error_message", sa.Text),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_document_kb_status", "knowledge_base_id", "status"),
    sa.Index("idx_t_document_content_hash", "content_hash"),
    sa.Index("idx_t_document_created_by", "created_by"),
)


DocumentChunk = sa.Table(
    "t_document_chunk",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("document_id", sa.BigInteger, nullable=False),
    sa.Column("parent_id", sa.BigInteger),
    sa.Column("chunk_index", sa.Integer, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("content_hash", sa.String(128), nullable=False),
    sa.Column("source_name", sa.String(512), nullable=False),
    sa.Column("page", sa.Integer),
    sa.Column("section", sa.String(512)),
    sa.Column("start_index", sa.Integer),
    sa.Column("token_count", sa.Integer),
    sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("embedding_model", sa.String(128), nullable=False),
    sa.Column("embedding", Vector()),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_document_chunk_kb_doc", "knowledge_base_id", "document_id"),
    sa.Index("idx_t_document_chunk_kb_index", "knowledge_base_id", "chunk_index"),
    sa.Index("idx_t_document_chunk_content_hash", "content_hash"),
    sa.Index("idx_t_document_chunk_metadata_gin", "metadata", postgresql_using="gin"),
)


IndexingTask = sa.Table(
    "t_indexing_task",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("document_id", sa.BigInteger, nullable=False),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("task_type", sa.String(32), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default=sa.text("3")),
    sa.Column("error_message", sa.Text),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_indexing_task_document_id", "document_id"),
    sa.Index("idx_t_indexing_task_status", "status"),
    sa.Index("idx_t_indexing_task_kb_status", "knowledge_base_id", "status"),
)


Conversation = sa.Table(
    "t_conversation",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("user_id", sa.String(128), nullable=False),
    sa.Column("title", sa.String(255)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_conversation_user_id", "user_id"),
    sa.Index("idx_t_conversation_kb_user", "knowledge_base_id", "user_id"),
)


ConversationMessage = sa.Table(
    "t_conversation_message",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("conversation_id", sa.BigInteger, nullable=False),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("user_id", sa.String(128), nullable=False),
    sa.Column("role", sa.String(32), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_conversation_message_conversation_id", "conversation_id"),
    sa.Index("idx_t_conversation_message_kb_user", "knowledge_base_id", "user_id"),
    sa.Index("idx_t_conversation_message_created_at", "created_at"),
)


MessageCitation = sa.Table(
    "t_message_citation",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("message_id", sa.BigInteger, nullable=False),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("document_id", sa.BigInteger, nullable=False),
    sa.Column("chunk_id", sa.BigInteger, nullable=False),
    sa.Column("source_name", sa.String(512), nullable=False),
    sa.Column("page", sa.Integer),
    sa.Column("snippet", sa.Text, nullable=False),
    sa.Column("score", sa.Numeric(8, 6)),
    sa.Column("rank", sa.Integer, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_message_citation_message_id", "message_id"),
    sa.Index("idx_t_message_citation_document_id", "document_id"),
    sa.Index("idx_t_message_citation_chunk_id", "chunk_id"),
)


EvaluationFeedback = sa.Table(
    "t_evaluation_feedback",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("knowledge_base_id", sa.BigInteger, nullable=False),
    sa.Column("conversation_id", sa.BigInteger),
    sa.Column("message_id", sa.BigInteger),
    sa.Column("question", sa.Text, nullable=False),
    sa.Column("expected_answer", sa.Text),
    sa.Column("actual_answer", sa.Text),
    sa.Column("expected_sources", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("rating", sa.Integer),
    sa.Column("labels", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("comment", sa.Text),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_evaluation_feedback_kb_created", "knowledge_base_id", "created_at"),
    sa.Index("idx_t_evaluation_feedback_message_id", "message_id"),
)


AuditLog = sa.Table(
    "t_audit_log",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("action", sa.String(128), nullable=False),
    sa.Column("target_type", sa.String(64), nullable=False),
    sa.Column("target_id", sa.String(128)),
    sa.Column("request_id", sa.String(128)),
    sa.Column("request_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("result", sa.String(32), nullable=False),
    sa.Column("error_message", sa.Text),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_audit_log_actor_id", "actor_id"),
    sa.Index("idx_t_audit_log_target", "target_type", "target_id"),
    sa.Index("idx_t_audit_log_created_at", "created_at"),
)
