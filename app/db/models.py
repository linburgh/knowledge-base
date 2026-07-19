import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()


Tenant = sa.Table(
    "t_tenant",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("code", sa.String(64), nullable=False),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("description", sa.String(500), nullable=False, server_default=sa.text("''")),
    sa.Column("logo", sa.String(1024)),
    sa.Column("contact_name", sa.String(128)),
    sa.Column("contact_email", sa.String(255)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_tenant_status", "status"),
)


User = sa.Table(
    "t_user",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("username", sa.String(128), nullable=False),
    sa.Column("email", sa.String(255)),
    sa.Column("phone", sa.String(32)),
    sa.Column("display_name", sa.String(128), nullable=False),
    sa.Column("avatar", sa.String(1024)),
    sa.Column("password_hash", sa.String(255)),
    sa.Column("external_subject", sa.String(255)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("last_login_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_user_status", "status"),
)


LoginLog = sa.Table(
    "t_login_log",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("user_id", sa.BigInteger),
    sa.Column("login_account", sa.String(255), nullable=False),
    sa.Column("login_type", sa.String(32), nullable=False),
    sa.Column("result", sa.String(32), nullable=False),
    sa.Column("failure_reason", sa.String(64)),
    sa.Column("ip_address", sa.String(64)),
    sa.Column("user_agent", sa.String(1024)),
    sa.Column("request_id", sa.String(128)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_login_log_user_created", "user_id", "created_at"),
    sa.Index("idx_t_login_log_account_created", "login_account", "created_at"),
    sa.Index("idx_t_login_log_result_created", "result", "created_at"),
)


AuthSession = sa.Table(
    "t_auth_session",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("jti", sa.String(64), nullable=False),
    sa.Column("token_type", sa.String(32), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_auth_session_user_id", "user_id"),
    sa.Index("idx_t_auth_session_active", "jti", "revoked_at", "expires_at"),
)


PlatformRole = sa.Table(
    "t_platform_role",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("code", sa.String(64), nullable=False),
    sa.Column("name", sa.String(128), nullable=False),
    sa.Column("description", sa.String(500), nullable=False, server_default=sa.text("''")),
    sa.Column("status", sa.String(32), nullable=False),
)


PlatformUserRole = sa.Table(
    "t_platform_user_role",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("role_id", sa.BigInteger, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("created_by", sa.BigInteger),
)


TenantMember = sa.Table(
    "t_tenant_member",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.BigInteger, nullable=False),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("role_code", sa.String(64), nullable=False),
    sa.Column("is_primary", sa.Boolean, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("joined_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)


OrganizationMember = sa.Table(
    "t_organization_member",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("organization_id", sa.BigInteger, nullable=False),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("role_code", sa.String(64), nullable=False),
    sa.Column("is_primary", sa.Boolean, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("joined_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)


Organization = sa.Table(
    "t_organization",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.BigInteger, nullable=False),
    sa.Column("parent_id", sa.BigInteger),
    sa.Column("code", sa.String(64), nullable=False),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("leader_user_id", sa.BigInteger),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_organization_tenant_parent", "tenant_id", "parent_id"),
    sa.Index("idx_t_organization_tenant_status", "tenant_id", "status"),
)


KnowledgeBase = sa.Table(
    "t_knowledge_base",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("tenant_id", sa.BigInteger, nullable=False),
    sa.Column("organization_id", sa.BigInteger),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("description", sa.String(500), nullable=False, server_default=sa.text("''")),
    sa.Column("owner_id", sa.String(128), nullable=False),
    sa.Column("visibility", sa.String(32), nullable=False),
    sa.Column("embedding_model", sa.String(128), nullable=False),
    sa.Column("chunk_size", sa.Integer, nullable=False),
    sa.Column("chunk_overlap", sa.Integer, nullable=False),
    sa.Column("retrieval_top_k", sa.Integer, nullable=False),
    sa.Column("system_prompt", sa.Text, nullable=False, server_default=sa.text("''")),
    sa.Column("system_prompt_version", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column(
        "system_prompt_updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("created_by", sa.BigInteger, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_knowledge_base_owner_id", "owner_id"),
    sa.Index("idx_t_knowledge_base_status", "status"),
)


KnowledgeBasePrompt = sa.Table(
    "t_knowledge_base_prompt",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("system_prompt", sa.Text, nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("kb_id", "version", name="uq_t_knowledge_base_prompt_kb_version"),
    sa.Index("idx_t_knowledge_base_prompt_kb_version", "kb_id", "version"),
)


Document = sa.Table(
    "t_document",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
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
    sa.Index("idx_t_document_kb_status", "kb_id", "status"),
    sa.Index("idx_t_document_content_hash", "content_hash"),
    sa.Index("idx_t_document_created_by", "created_by"),
)


DocumentChunk = sa.Table(
    "t_document_chunk",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
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
    sa.Index("idx_t_document_chunk_kb_doc", "kb_id", "document_id"),
    sa.Index("idx_t_document_chunk_kb_index", "kb_id", "chunk_index"),
    sa.Index("idx_t_document_chunk_content_hash", "content_hash"),
    sa.Index("idx_t_document_chunk_metadata_gin", "metadata", postgresql_using="gin"),
)


IndexingTask = sa.Table(
    "t_indexing_task",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("document_id", sa.BigInteger, nullable=False),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
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
    sa.Index("idx_t_indexing_task_kb_status", "kb_id", "status"),
)


Conversation = sa.Table(
    "t_conversation",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
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
    sa.Index("idx_t_conversation_kb_user", "kb_id", "user_id"),
)


ConversationMessage = sa.Table(
    "t_conversation_message",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("conversation_id", sa.BigInteger, nullable=False),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("user_id", sa.String(128), nullable=False),
    sa.Column("role", sa.String(32), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_conversation_message_conversation_id", "conversation_id"),
    sa.Index("idx_t_conversation_message_kb_user", "kb_id", "user_id"),
    sa.Index("idx_t_conversation_message_created_at", "created_at"),
)


MessageCitation = sa.Table(
    "t_message_citation",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("message_id", sa.BigInteger, nullable=False),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
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
    sa.Column("kb_id", sa.BigInteger, nullable=False),
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
    sa.Index("idx_t_evaluation_feedback_kb_created", "kb_id", "created_at"),
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
