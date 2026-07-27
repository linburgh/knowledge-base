import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()


EvaluationTask = sa.Table(
    "t_evaluation_task", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("name", sa.String(255), nullable=False), sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

EvaluationRun = sa.Table(
    "t_evaluation_run", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("task_id", sa.BigInteger, nullable=False), sa.Column("run_no", sa.Integer, nullable=False),
    sa.Column("status", sa.String(32), nullable=False), sa.Column("conclusion", sa.String(32)),
    sa.Column("config_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("report", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("stage", sa.String(32), nullable=False, server_default="prepare"),
    sa.Column("question_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("error_message", sa.String(500)),
    sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("task_id", "run_no"),
)

EvaluationCaseResult = sa.Table(
    "t_evaluation_case_result", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True), sa.Column("run_id", sa.BigInteger, nullable=False),
    sa.Column("case_no", sa.Integer, nullable=False), sa.Column("question", sa.Text, nullable=False),
    sa.Column("question_source", sa.String(32), nullable=False), sa.Column("question_basis", sa.String(64)),
    sa.Column("answer", sa.Text), sa.Column("status", sa.String(32), nullable=False),
    sa.Column("termination_reason", sa.String(128)), sa.Column("citation_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"), sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
    sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text), sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.UniqueConstraint("run_id", "case_no"),
)

EvaluationOptimization = sa.Table(
    "t_evaluation_optimization", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True), sa.Column("run_id", sa.BigInteger, nullable=False),
    sa.Column("suggestion", sa.Text, nullable=False), sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("candidate_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("status", sa.String(32), nullable=False, server_default="suggested"),
    sa.Column("retest_run_id", sa.BigInteger), sa.Column("before_metrics", JSONB), sa.Column("after_metrics", JSONB),
    sa.Column("requires_confirmation", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column("created_by", sa.String(128), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)


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
    sa.Column("tenant_id", sa.BigInteger),
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


SystemMenu = sa.Table(
    "t_system_menu",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("parent_id", sa.BigInteger),
    sa.Column("code", sa.String(100), nullable=False),
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("menu_type", sa.String(32), nullable=False),
    sa.Column("route_path", sa.String(255)),
    sa.Column("icon", sa.String(100)),
    sa.Column("sort_order", sa.Integer, nullable=False),
    sa.Column("visible", sa.Boolean, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_system_menu_parent_sort", "parent_id", "sort_order", "id"),
    sa.Index("idx_t_system_menu_status_visible", "status", "visible"),
)


RoleMenu = sa.Table(
    "t_role_menu",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("role_scope", sa.String(32), nullable=False),
    sa.Column("role_code", sa.String(64), nullable=False),
    sa.Column("menu_id", sa.BigInteger, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("created_by", sa.BigInteger),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("role_scope", "role_code", "menu_id"),
    sa.Index("idx_t_role_menu_role", "role_scope", "role_code", "status"),
    sa.Index("idx_t_role_menu_menu", "menu_id", "status"),
)


SystemMenuAction = sa.Table(
    "t_system_menu_action",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("menu_id", sa.BigInteger, nullable=False),
    sa.Column("code", sa.String(128), nullable=False),
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("action_type", sa.String(32), nullable=False),
    sa.Column("sort_order", sa.Integer, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_system_menu_action_menu", "menu_id", "status"),
)


RoleMenuAction = sa.Table(
    "t_role_menu_action",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("role_scope", sa.String(32), nullable=False),
    sa.Column("role_code", sa.String(64), nullable=False),
    sa.Column("action_id", sa.BigInteger, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("created_by", sa.BigInteger),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_role_menu_action_role", "role_scope", "role_code", "status"),
    sa.Index("idx_t_role_menu_action_action", "action_id", "status"),
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
    sa.Column("tenant_id", sa.BigInteger, nullable=True),
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
    sa.Column("tenant_id", sa.BigInteger, nullable=True),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("description", sa.String(500), nullable=False, server_default=sa.text("''")),
    sa.Column("owner_id", sa.String(128), nullable=False),
    sa.Column("visibility", sa.String(32), nullable=False),
    sa.Column("embedding_model", sa.String(128), nullable=False),
    sa.Column("chunk_size", sa.Integer, nullable=False),
    sa.Column("chunk_overlap", sa.Integer, nullable=False),
    sa.Column("retrieval_top_k", sa.Integer, nullable=False),
    sa.Column("active_index_version_id", sa.BigInteger),
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


KnowledgeBaseQaConfigVersion = sa.Table(
    "t_knowledge_base_qa_config_version",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("version_no", sa.Integer, nullable=False),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("config_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column(
        "change_summary_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    sa.Column("requires_reindex", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("affected_document_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("created_by", sa.BigInteger, nullable=False),
    sa.Column("published_by", sa.BigInteger),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("kb_id", "version_no", name="uq_t_knowledge_base_qa_config_kb_version"),
    sa.Index("idx_t_knowledge_base_qa_config_kb_status", "kb_id", "status"),
)


KnowledgeBaseQaConfigAudit = sa.Table(
    "t_knowledge_base_qa_config_audit",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("config_version_id", sa.BigInteger),
    sa.Column("action", sa.String(32), nullable=False),
    sa.Column("actor_id", sa.BigInteger, nullable=False),
    sa.Column("before_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("after_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("result", sa.String(20), nullable=False),
    sa.Column("error_message", sa.Text),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("idx_t_knowledge_base_qa_config_audit_kb_created", "kb_id", "created_at"),
)


KnowledgeBaseIndexVersion = sa.Table(
    "t_knowledge_base_index_version",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("generation", sa.String(64), nullable=False),
    sa.Column("config_version_id", sa.BigInteger),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("vector_collection", sa.String(255), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("activated_at", sa.DateTime(timezone=True)),
    sa.Column("retired_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("kb_id", "generation", name="uq_t_knowledge_base_index_kb_generation"),
    sa.Index("idx_t_knowledge_base_index_kb_status", "kb_id", "status"),
)


KnowledgeBaseOrganization = sa.Table(
    "t_knowledge_base_organization",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("organization_id", sa.BigInteger, nullable=False),
    sa.Column("created_by", sa.BigInteger, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)


KnowledgeBaseUser = sa.Table(
    "t_knowledge_base_user",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("kb_id", sa.BigInteger, nullable=False),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("created_by", sa.BigInteger, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("kb_id", "user_id", name="uq_t_knowledge_base_user_kb_user"),
    sa.Index("idx_t_knowledge_base_user_kb_id", "kb_id"),
    sa.Index("idx_t_knowledge_base_user_user_id", "user_id"),
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
    sa.Column("index_version_id", sa.BigInteger),
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
    sa.Column("config_version_id", sa.BigInteger),
    sa.Column("index_version_id", sa.BigInteger),
    sa.Column("task_type", sa.String(32), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("progress", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("current_step", sa.String(64)),
    sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default=sa.text("3")),
    sa.Column("retry_of_task_id", sa.BigInteger),
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
    sa.Column("qa_config_version_id", sa.BigInteger),
    sa.Column("index_version_id", sa.BigInteger),
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
    sa.Column("qa_config_version_id", sa.BigInteger),
    sa.Column("index_version_id", sa.BigInteger),
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
    sa.Column("action_cn", sa.String(128), nullable=False),
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
