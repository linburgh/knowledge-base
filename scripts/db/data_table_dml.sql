-- PostgreSQL initial and migration DML for knowledge-base data.
-- DDL is maintained separately in data_table_ddl.sql.

insert into t_platform_role (code, name, description)
values ('p_super_admin', '平台超级管理员', '可以操作平台范围内全部资源')
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    status = 'active';

insert into t_system_menu (parent_id, code, name, menu_type, route_path, sort_order)
values
    (null, 'platform', '平台管理', 'directory', null, 10),
    (null, 'knowledge_base', '知识库管理', 'directory', null, 20),
    (null, 'independent_chat', '独立问答', 'item', '/guest/knowledge-bases', 30)
on conflict (code) do update
set name = excluded.name,
    menu_type = excluded.menu_type,
    route_path = excluded.route_path,
    sort_order = excluded.sort_order,
    status = 'active',
    updated_at = now();

insert into t_system_menu (parent_id, code, name, menu_type, route_path, sort_order)
select parent.id, menu.code, menu.name, menu.menu_type, menu.route_path, menu.sort_order
from (
    values
        ('platform', 'platform_overview', '平台概览', 'item', '/platform/overview', 10),
        ('platform', 'platform_users', '用户管理', 'item', '/platform/users', 20),
        ('platform', 'platform_tenants', '租户管理', 'item', '/platform/tenants', 30),
        ('platform', 'platform_organizations', '组织管理', 'item', '/platform/organizations', 40),
        ('platform', 'platform_evaluations', '自主评测', 'item', '/platform/evaluations', 45),
        ('platform', 'developer_api', '开发者中心', 'item', '/platform/developer-api', 50),
        ('knowledge_base', 'knowledge_base_list', '知识库列表', 'item', '/knowledge-bases', 10)
) as menu(parent_code, code, name, menu_type, route_path, sort_order)
join t_system_menu parent on parent.code = menu.parent_code
on conflict (code) do update
set parent_id = excluded.parent_id,
    name = excluded.name,
    menu_type = excluded.menu_type,
    route_path = excluded.route_path,
    sort_order = excluded.sort_order,
    status = 'active',
    updated_at = now();

insert into t_system_menu (parent_id, code, name, menu_type, route_path, sort_order)
select parent.id, menu.code, menu.name, menu.menu_type, menu.route_path, menu.sort_order
from (
    values
        ('knowledge_base_list', 'knowledge_base_workspace', '知识库工作区', 'directory', null, 10)
) as menu(parent_code, code, name, menu_type, route_path, sort_order)
join t_system_menu parent on parent.code = menu.parent_code
on conflict (code) do update
set parent_id = excluded.parent_id,
    name = excluded.name,
    menu_type = excluded.menu_type,
    route_path = excluded.route_path,
    sort_order = excluded.sort_order,
    status = 'active',
    updated_at = now();

insert into t_system_menu (parent_id, code, name, menu_type, route_path, sort_order)
select parent.id, menu.code, menu.name, menu.menu_type, menu.route_path, menu.sort_order
from (
    values
        ('knowledge_base_workspace', 'knowledge_base_overview', '概览', 'item', '/knowledge-bases/:kbId/overview', 10),
        ('knowledge_base_workspace', 'knowledge_base_documents', '文档', 'item', '/knowledge-bases/:kbId/documents', 20),
        ('knowledge_base_workspace', 'knowledge_base_chat', '问答', 'item', '/knowledge-bases/:kbId/chat', 30)
) as menu(parent_code, code, name, menu_type, route_path, sort_order)
join t_system_menu parent on parent.code = menu.parent_code
on conflict (code) do update
set parent_id = excluded.parent_id,
    name = excluded.name,
    menu_type = excluded.menu_type,
    route_path = excluded.route_path,
    sort_order = excluded.sort_order,
    status = 'active',
    updated_at = now();

delete from t_role_menu role_menu
using t_system_menu menu
where role_menu.menu_id = menu.id
  and menu.code = 'knowledge_base_documents'
  and (
      (role_menu.role_scope = 'tenant' and role_menu.role_code = 'tenant_member')
      or (role_menu.role_scope = 'organization' and role_menu.role_code = 'org_member')
  );

delete from t_role_menu_action role_action
using t_system_menu_action action
join t_system_menu menu on menu.id = action.menu_id
where role_action.action_id = action.id
  and menu.code = 'developer_api'
  and role_action.role_scope = 'tenant'
  and role_action.role_code = 'tenant_admin';

delete from t_role_menu role_menu
using t_system_menu menu
where role_menu.menu_id = menu.id
  and menu.code = 'developer_api'
  and role_menu.role_scope = 'tenant'
  and role_menu.role_code = 'tenant_admin';

delete from t_role_menu_action role_action
using t_system_menu_action action
join t_system_menu menu on menu.id = action.menu_id
where role_action.action_id = action.id
  and menu.code = 'platform_tenants'
  and role_action.role_scope = 'tenant'
  and role_action.role_code = 'tenant_admin';

delete from t_role_menu role_menu
using t_system_menu menu
where role_menu.menu_id = menu.id
  and menu.code = 'platform_tenants'
  and role_menu.role_scope = 'tenant'
  and role_menu.role_code = 'tenant_admin';

delete from t_role_menu_action
where role_scope = 'tenant'
  and role_code = 'tenant_owner';

delete from t_role_menu
where role_scope = 'tenant'
  and role_code = 'tenant_owner';

with role_menus(role_scope, role_code, menu_code) as (
    values
        ('platform', 'p_super_admin', 'platform'),
        ('platform', 'p_super_admin', 'platform_overview'),
        ('platform', 'p_super_admin', 'platform_users'),
        ('platform', 'p_super_admin', 'platform_tenants'),
        ('platform', 'p_super_admin', 'platform_organizations'),
        ('platform', 'p_super_admin', 'platform_evaluations'),
        ('platform', 'p_super_admin', 'developer_api'),
        ('platform', 'p_super_admin', 'knowledge_base'),
        ('platform', 'p_super_admin', 'knowledge_base_list'),
        ('platform', 'p_super_admin', 'knowledge_base_workspace'),
        ('platform', 'p_super_admin', 'knowledge_base_overview'),
        ('platform', 'p_super_admin', 'knowledge_base_documents'),
        ('platform', 'p_super_admin', 'knowledge_base_chat'),
        ('tenant', 'tenant_admin', 'platform_overview'),
        ('tenant', 'tenant_admin', 'platform_users'),
        ('tenant', 'tenant_admin', 'platform_organizations'),
        ('tenant', 'tenant_admin', 'platform_evaluations'),
        ('tenant', 'tenant_admin', 'platform'),
        ('tenant', 'tenant_admin', 'knowledge_base'),
        ('tenant', 'tenant_admin', 'knowledge_base_list'),
        ('tenant', 'tenant_admin', 'knowledge_base_workspace'),
        ('tenant', 'tenant_admin', 'knowledge_base_overview'),
        ('tenant', 'tenant_admin', 'knowledge_base_documents'),
        ('tenant', 'tenant_admin', 'knowledge_base_chat'),
        ('tenant', 'tenant_member', 'knowledge_base'),
        ('tenant', 'tenant_member', 'knowledge_base_list'),
        ('tenant', 'tenant_member', 'knowledge_base_workspace'),
        ('tenant', 'tenant_member', 'knowledge_base_overview'),
        ('tenant', 'tenant_member', 'knowledge_base_chat'),
        ('tenant', 'tenant_guest', 'independent_chat'),
        ('organization', 'org_admin', 'knowledge_base'),
        ('organization', 'org_admin', 'knowledge_base_list'),
        ('organization', 'org_admin', 'knowledge_base_workspace'),
        ('organization', 'org_admin', 'knowledge_base_overview'),
        ('organization', 'org_admin', 'knowledge_base_documents'),
        ('organization', 'org_admin', 'knowledge_base_chat'),
        ('organization', 'org_member', 'knowledge_base'),
        ('organization', 'org_member', 'knowledge_base_list'),
        ('organization', 'org_member', 'knowledge_base_workspace'),
        ('organization', 'org_member', 'knowledge_base_overview'),
        ('organization', 'org_member', 'knowledge_base_chat')
)
insert into t_role_menu (role_scope, role_code, menu_id)
select role_menus.role_scope, role_menus.role_code, menu.id
from role_menus
join t_system_menu menu on menu.code = role_menus.menu_code
on conflict (role_scope, role_code, menu_id) do update
set status = 'active',
    updated_at = now();

insert into t_system_menu_action (menu_id, code, name, action_type, sort_order, status)
select menu.id, actions.code, actions.name, actions.action_type, actions.sort_order, 'active'
from (
    values
        ('platform_overview', 'platform_overview:view', '查看平台概览', 'business', 10),
        ('platform_users', 'platform_user:list', '查看平台用户', 'business', 10),
        ('platform_users', 'platform_user:create', '新增平台用户', 'business', 20),
        ('platform_users', 'platform_user:update', '编辑平台用户', 'business', 30),
        ('platform_users', 'platform_user:delete', '删除平台用户', 'business', 40),
        ('platform_users', 'platform_user:role', '调整平台角色', 'business', 50),
        ('platform_tenants', 'tenant:list', '查看租户', 'business', 10),
        ('platform_tenants', 'tenant:create', '新增租户', 'business', 20),
        ('platform_tenants', 'tenant:update', '编辑租户', 'business', 30),
        ('platform_tenants', 'tenant:delete', '删除租户', 'business', 40),
        ('platform_tenants', 'tenant:member', '管理租户成员', 'business', 50),
        ('platform_organizations', 'organization:list', '查看组织', 'business', 10),
        ('platform_organizations', 'organization:create', '新增组织', 'business', 20),
        ('platform_organizations', 'organization:update', '编辑组织', 'business', 30),
        ('platform_organizations', 'organization:delete', '删除组织', 'business', 40),
        ('platform_organizations', 'organization:member', '管理组织成员', 'business', 50),
        ('platform_evaluations', 'evaluation:list', '查看自主评测', 'business', 10),
        ('platform_evaluations', 'evaluation:create', '新增自主评测', 'business', 20),
        ('platform_evaluations', 'evaluation:update', '修改未执行自主评测', 'business', 25),
        ('platform_evaluations', 'evaluation:execute', '执行自主评测', 'business', 30),
        ('platform_evaluations', 'evaluation:detail', '查看评测结果', 'business', 40),
        ('platform_evaluations', 'evaluation:delete', '删除自主评测', 'business', 50),
        ('platform_evaluations', 'evaluation:optimize', '优化评测方案', 'business', 60),
        ('developer_api', 'developer_api:view', '查看开发者文档', 'business', 10),
        ('knowledge_base_list', 'knowledge_base:list', '查看知识库', 'business', 10),
        ('knowledge_base_list', 'knowledge_base:create', '新增知识库', 'business', 20),
        ('knowledge_base_list', 'knowledge_base:update', '编辑知识库', 'business', 30),
        ('knowledge_base_list', 'knowledge_base:delete', '删除知识库', 'business', 40),
        ('knowledge_base_list', 'knowledge_base:member', '管理知识库成员', 'business', 50),
        ('knowledge_base_overview', 'knowledge_base:overview', '查看知识库概览', 'business', 10),
        ('knowledge_base_overview', 'knowledge_base:update_config', '修改知识库配置', 'business', 20),
        ('knowledge_base_documents', 'document:list', '查看文档', 'business', 10),
        ('knowledge_base_documents', 'document:upload', '上传文档', 'business', 20),
        ('knowledge_base_documents', 'document:delete', '删除文档', 'business', 30),
        ('knowledge_base_documents', 'document:reindex', '重新索引文档', 'business', 40),
        ('knowledge_base_chat', 'knowledge_base:ask', '知识库问答', 'business', 10),
        ('independent_chat', 'guest_chat:ask', '独立问答', 'business', 10)
) as actions(menu_code, code, name, action_type, sort_order)
join t_system_menu menu on menu.code = actions.menu_code
on conflict (code) do update
set menu_id = excluded.menu_id,
    name = excluded.name,
    action_type = excluded.action_type,
    sort_order = excluded.sort_order,
    status = 'active',
    updated_at = now();

with role_action_grants(role_scope, role_code, menu_code, action_code) as (
    values
        ('platform', 'p_super_admin', 'platform_overview', null),
        ('platform', 'p_super_admin', 'platform_users', null),
        ('platform', 'p_super_admin', 'platform_tenants', null),
        ('platform', 'p_super_admin', 'platform_organizations', null),
        ('platform', 'p_super_admin', 'platform_evaluations', null),
        ('platform', 'p_super_admin', 'developer_api', null),
        ('platform', 'p_super_admin', 'knowledge_base_list', null),
        ('platform', 'p_super_admin', 'knowledge_base_overview', null),
        ('platform', 'p_super_admin', 'knowledge_base_documents', null),
        ('platform', 'p_super_admin', 'knowledge_base_chat', null),
        ('tenant', 'tenant_admin', 'platform_overview', null),
        ('tenant', 'tenant_admin', 'platform_users', null),
        ('tenant', 'tenant_admin', 'platform_organizations', null),
        ('tenant', 'tenant_admin', 'platform_evaluations', null),
        ('tenant', 'tenant_admin', 'knowledge_base_list', null),
        ('tenant', 'tenant_admin', 'knowledge_base_overview', null),
        ('tenant', 'tenant_admin', 'knowledge_base_documents', null),
        ('tenant', 'tenant_admin', 'knowledge_base_chat', null),
        ('tenant', 'tenant_member', 'knowledge_base_list', 'knowledge_base:list'),
        ('tenant', 'tenant_member', 'knowledge_base_overview', 'knowledge_base:overview'),
        ('tenant', 'tenant_member', 'knowledge_base_chat', 'knowledge_base:ask'),
        ('tenant', 'tenant_guest', 'independent_chat', 'guest_chat:ask'),
        ('organization', 'org_admin', 'platform_organizations', null),
        ('organization', 'org_admin', 'knowledge_base_list', null),
        ('organization', 'org_admin', 'knowledge_base_overview', null),
        ('organization', 'org_admin', 'knowledge_base_documents', null),
        ('organization', 'org_admin', 'knowledge_base_chat', null),
        ('organization', 'org_member', 'knowledge_base_list', 'knowledge_base:list'),
        ('organization', 'org_member', 'knowledge_base_overview', 'knowledge_base:overview'),
        ('organization', 'org_member', 'knowledge_base_chat', 'knowledge_base:ask')
)
insert into t_role_menu_action (role_scope, role_code, action_id, status)
select grants.role_scope, grants.role_code, action.id, 'active'
from role_action_grants grants
join t_system_menu menu on menu.code = grants.menu_code
join t_system_menu_action action
  on action.menu_id = menu.id
 and (grants.action_code is null or action.code = grants.action_code)
on conflict (role_scope, role_code, action_id) do update
set status = 'active',
    updated_at = now();

-- 为已有知识库补齐初始提示词历史版本，重复执行不会产生重复记录。
insert into t_knowledge_base_prompt (kb_id, version, system_prompt, created_by)
select kb.id, coalesce(kb.system_prompt_version, 1), coalesce(kb.system_prompt, ''), kb.owner_id
from t_knowledge_base kb
where not exists (
    select 1
    from t_knowledge_base_prompt prompt
    where prompt.kb_id = kb.id
);

-- 自主监控导航与权限种子；菜单只授予平台超级管理员和租户管理员。
insert into t_system_menu (parent_id, code, name, menu_type, route_path, icon, sort_order, visible, status)
select null, 'monitoring', '自主监控', 'directory', null, 'monitoring', 90, true, 'active'
where not exists (select 1 from t_system_menu where code = 'monitoring');

update t_system_menu
set meta = coalesce(meta, '{}'::jsonb) || '{"sidebar_show_children": true}'::jsonb,
    updated_at = now()
where code = 'monitoring';

insert into t_system_menu (parent_id, code, name, menu_type, route_path, icon, sort_order, visible, status)
select parent.id, item.code, item.name, 'item', item.route_path, 'monitoring', item.sort_order, true, 'active'
from t_system_menu parent
cross join (values
    ('monitoring_overview', '监控总览', '/monitoring/overview', 1),
    ('monitoring_collection', '数据采集', '/monitoring/collection', 2),
    ('monitoring_metrics', '指标分析', '/monitoring/metrics', 3),
    ('monitoring_tasks', '任务监控', '/monitoring/tasks', 4),
    ('monitoring_alerts', '告警中心', '/monitoring/alerts', 5),
    ('monitoring_events', '事件中心', '/monitoring/events', 6),
    ('monitoring_analysis', '智能分析', '/monitoring/analysis', 7),
    ('monitoring_audits', '审计管理', '/monitoring/audits', 8)
) as item(code, name, route_path, sort_order)
where parent.code = 'monitoring'
  and not exists (select 1 from t_system_menu existing where existing.code = item.code);

-- 智能分析收敛为单一入口，兼容更新存量菜单，并清理历史“分析总览 / 分析对话”子菜单及授权。
update t_system_menu menu
set parent_id = parent.id,
    name = '智能分析',
    menu_type = 'item',
    route_path = '/monitoring/analysis',
    sort_order = 7,
    visible = true,
    status = 'active',
    updated_at = now()
from t_system_menu parent
where menu.code = 'monitoring_analysis'
  and parent.code = 'monitoring';

delete from t_role_menu_action relation
using t_system_menu_action action, t_system_menu child, t_system_menu parent
where relation.action_id = action.id
  and action.menu_id = child.id
  and child.parent_id = parent.id
  and parent.code = 'monitoring_analysis';

delete from t_system_menu_action action
using t_system_menu child, t_system_menu parent
where action.menu_id = child.id
  and child.parent_id = parent.id
  and parent.code = 'monitoring_analysis';

delete from t_role_menu relation
using t_system_menu child, t_system_menu parent
where relation.menu_id = child.id
  and child.parent_id = parent.id
  and parent.code = 'monitoring_analysis';

delete from t_system_menu child
using t_system_menu parent
where child.parent_id = parent.id
  and parent.code = 'monitoring_analysis';

-- 审计管理暂不对业务角色开放；事件中心恢复平台超级管理员和租户管理员授权。
delete from t_role_menu relation
using t_system_menu menu
where relation.menu_id = menu.id
  and menu.code = 'monitoring_audits'
  and (
      (relation.role_scope = 'platform' and relation.role_code = 'p_super_admin')
      or (relation.role_scope = 'tenant' and relation.role_code = 'tenant_admin')
  );

insert into t_role_menu (role_scope, role_code, menu_id, status)
select role_item.role_scope, role_item.role_code, menu.id, 'active'
from (values ('platform', 'p_super_admin'), ('tenant', 'tenant_admin')) as role_item(role_scope, role_code)
cross join t_system_menu menu
where (menu.code = 'monitoring' or menu.code like 'monitoring_%')
  and menu.code <> 'monitoring_audits'
on conflict (role_scope, role_code, menu_id) do update
set status = excluded.status,
    updated_at = now();

insert into t_system_menu_action (menu_id, code, name, action_type, sort_order, status)
select menu.id, action.code, action.name, 'button', action.sort_order, 'active'
from t_system_menu menu
cross join (values
    ('monitoring_overview', 'monitoring:list', '查看监控', 1),
    ('monitoring_alerts', 'monitoring:detail', '查看告警', 1),
    ('monitoring_alerts', 'monitoring:alert-action', '处理告警', 2),
    ('monitoring_alerts', 'monitoring:rule-manage', '管理规则', 3),
    ('monitoring_alerts', 'monitoring:notification-manage', '管理通知', 4),
    ('monitoring_analysis', 'monitoring:analysis', '使用智能分析', 1)
) as action(menu_code, code, name, sort_order)
where menu.code = action.menu_code
  and not exists (select 1 from t_system_menu_action existing where existing.code = action.code);

update t_system_menu_action
set name = '使用智能分析',
    updated_at = now()
where code = 'monitoring:analysis';

insert into t_role_menu_action (role_scope, role_code, action_id, status)
select role_item.role_scope, role_item.role_code, action.id, 'active'
from (values ('platform', 'p_super_admin'), ('tenant', 'tenant_admin')) as role_item(role_scope, role_code)
cross join t_system_menu_action action
where action.code like 'monitoring:%'
  and not exists (
      select 1 from t_role_menu_action relation
      where relation.role_scope = role_item.role_scope
        and relation.role_code = role_item.role_code
        and relation.action_id = action.id
  );

-- 自主监控采集目标由系统发布统一维护，业务页面只读展示运行事实。
-- target_locator 只保存稳定代码定位、预置适配器和非敏感探针参数，不保存凭证或任意可执行代码。
insert into t_monitor_gather_target (
    target_code,
    target_name,
    target_type,
    target_locator,
    enabled,
    tenant_id,
    version,
    effective_at,
    created_by,
    updated_by
)
select
    target.target_code,
    target.target_name,
    target.target_type,
    target.target_locator::jsonb,
    target.enabled,
    null,
    1,
    timestamptz '2026-07-31 00:00:00+00:00',
    'system-release',
    'system-release'
from (
    values
        (
            'knowledge.qa',
            '知识库问答',
            'method',
            '{"module":"app.agents.knowledge.agent","callable":"run_knowledge_agent","collector":"knowledge_qa_collector","input_mapping":{"kb_id":"args.0.kb_id","tenant_id":"context.tenant_id","purpose":"context.purpose"},"output_mapping":{"duration_ms":"result.duration_ms","hit_count":"result.hit_count","citation_count":"result.citations.length","termination_reason":"result.termination_reason"}}',
            true
        ),
        (
            'evaluation.run',
            '自主评测运行',
            'method',
            '{"module":"app.workers.evaluation","callable":"run_evaluation","collector":"evaluation_run_collector","input_mapping":{"run_id":"args.0"}}',
            true
        ),
        (
            'document.ingestion',
            '文档入库处理',
            'method',
            '{"module":"app.core.services.knowledge_base.document","callable":"upload","collector":"document_ingestion_collector","input_mapping":{"kb_id":"args.1","source_type":"kwargs.source_type"},"output_mapping":{"document_id":"result.id","file_size":"result.file_size"}}',
            true
        ),
        (
            'document.indexing',
            '文档索引构建',
            'method',
            '{"module":"app.core.services.knowledge_base.ingestion","callable":"run_claimed_task","collector":"document_indexing_collector","input_mapping":{"task_id":"args.0"},"output_mapping":{"document_id":"result.document_id","kb_id":"result.kb_id","chunk_count":"result.chunk_count","index_version":"result.index_version_id"}}',
            true
        ),
        (
            'api.http',
            'API 请求采集',
            'api',
            '{"adapter":"fastapi_middleware","collector":"http_request_collector","path_mode":"route_template","exclude_paths":["/api/v1/health","/docs","/openapi.json"]}',
            true
        ),
        (
            'db.execute',
            '数据库操作采集',
            'db',
            '{"adapter":"database_access","collector":"sql_operation_collector","slow_threshold_ms":500,"exclude_tables":["t_monitor_event","t_monitor_state_snapshot","t_monitor_metric_value","t_monitor_alert"]}',
            true
        ),
        (
            'worker.lifecycle',
            'Worker 生命周期',
            'worker',
            '{"adapter":"worker_loop","collector":"worker_lifecycle_collector","heartbeat_interval_seconds":30,"workers":["indexing","evaluation","monitoring_collect","monitoring_aggregate","monitoring_notify"]}',
            true
        ),
        (
            'probe.api',
            'API 服务探针',
            'probe',
            '{"probe":"process_api","resource_type":"service","resource_code":"api-service","interval_seconds":60,"timeout_seconds":3}',
            true
        ),
        (
            'probe.database',
            '数据库探针',
            'probe',
            '{"probe":"database","resource_type":"service","resource_code":"database","interval_seconds":60,"timeout_seconds":3}',
            true
        ),
        (
            'probe.llm',
            '模型服务探针',
            'probe',
            '{"probe":"http_dependency","config_group":"chat","resource_type":"dependency","resource_code":"llm-service","interval_seconds":60,"timeout_seconds":5}',
            true
        ),
        (
            'probe.embedding',
            'Embedding 探针',
            'probe',
            '{"probe":"http_dependency","config_group":"embedding","resource_type":"dependency","resource_code":"embedding-service","interval_seconds":60,"timeout_seconds":5}',
            true
        ),
        (
            'probe.rerank',
            'Rerank 探针',
            'probe',
            '{"probe":"http_dependency","config_group":"rag","resource_type":"dependency","resource_code":"rerank-service","interval_seconds":60,"timeout_seconds":5}',
            true
        ),
        (
            'probe.vector',
            '向量能力探针',
            'probe',
            '{"probe":"vector_database","resource_type":"dependency","resource_code":"vector-service","interval_seconds":60,"timeout_seconds":3}',
            true
        ),
        (
            'probe.storage',
            '对象存储探针',
            'probe',
            '{"probe":"object_storage","config_group":"storage","resource_type":"dependency","resource_code":"storage-service","interval_seconds":60,"timeout_seconds":5}',
            true
        ),
        (
            'probe.worker',
            'Worker 状态探针',
            'probe',
            '{"probe":"worker_status","resource_type":"worker","resource_code":"worker-runtime","interval_seconds":30,"timeout_seconds":3}',
            true
        ),
        (
            'probe.task_backlog',
            '任务积压探针',
            'probe',
            '{"probe":"task_backlog","resource_type":"task","resource_code":"task-backlog","interval_seconds":60,"timeout_seconds":3}',
            true
        ),
        (
            'capacity.database',
            '数据库连接容量',
            'probe',
            '{"probe":"database_capacity","resource_type":"capacity","resource_code":"database-capacity","interval_seconds":60,"timeout_seconds":3,"warning_threshold":80,"critical_threshold":95}',
            true
        ),
        (
            'capacity.queue',
            '任务队列容量',
            'probe',
            '{"probe":"queue_capacity","resource_type":"capacity","resource_code":"task-queue-capacity","interval_seconds":60,"timeout_seconds":3,"capacity_limit":100,"warning_threshold":80,"critical_threshold":95}',
            true
        ),
        (
            'capacity.file_storage',
            '文件存储容量',
            'probe',
            '{"probe":"file_storage_capacity","resource_type":"capacity","resource_code":"file-storage-capacity","interval_seconds":300,"timeout_seconds":30,"quota_bytes":10737418240,"warning_threshold":80,"critical_threshold":90}',
            true
        ),
        (
            'capacity.vector_storage',
            '向量存储容量',
            'probe',
            '{"probe":"vector_storage_capacity","resource_type":"capacity","resource_code":"vector-storage-capacity","interval_seconds":300,"timeout_seconds":10,"quota_bytes":1073741824,"warning_threshold":80,"critical_threshold":90}',
            true
        ),
        (
            'probe.qa',
            '问答链路主动探针',
            'probe',
            '{"probe":"knowledge_qa","purpose":"monitor_probe","resource_type":"service","resource_code":"knowledge-qa-probe","interval_seconds":300,"timeout_seconds":120,"tenant_id":null,"kb_id":null,"user_id":null,"fixed_question":"请简要说明当前监控知识库的用途。","top_k":3}',
            false
        ),
        (
            'collector.self',
            '监控采集器状态',
            'collector',
            '{"probe":"collector_self","resource_type":"collector","resource_code":"monitor-collector","interval_seconds":60,"stale_after_seconds":180}',
            true
        )
) as target(target_code, target_name, target_type, target_locator, enabled)
on conflict (target_code, version) do update
set target_name = excluded.target_name,
    target_type = excluded.target_type,
    target_locator = excluded.target_locator,
    enabled = excluded.enabled,
    effective_at = excluded.effective_at,
    updated_by = excluded.updated_by,
    updated_at = now();

-- 采集动作仅引用预置 Collector 和受控字段白名单。
insert into t_monitor_gather_action (
    target_code,
    event_type,
    field_mapping,
    sampling_rate,
    enabled,
    version
)
select
    action.target_code,
    action.event_type,
    jsonb_build_object(
        'hook', action.hook,
        'collector', action.collector,
        'source_type', action.source_type,
        'status', action.event_status,
        'sampling', jsonb_build_object('mode', 'all'),
        'payload_allowlist', to_jsonb(action.payload_allowlist)
    ),
    action.sampling_rate,
    true,
    1
from (
    values
        ('knowledge.qa', 'qa_started', 'before', 'knowledge_qa_collector', 'knowledge_agent', 'started', 1::numeric, array['attempt']),
        ('knowledge.qa', 'qa_retrieval_completed', 'explicit', 'knowledge_qa_collector', 'knowledge_agent', 'completed', 1::numeric, array['hit_count','retrieval_duration_ms']),
        ('knowledge.qa', 'qa_model_completed', 'explicit', 'knowledge_qa_collector', 'knowledge_agent', 'completed', 1::numeric, array['model_duration_ms','model_version']),
        ('knowledge.qa', 'qa_completed', 'explicit', 'knowledge_qa_collector', 'knowledge_agent', 'completed', 1::numeric, array['hit_count','citation_count','termination_reason']),
        ('knowledge.qa', 'qa_degraded', 'explicit', 'knowledge_qa_collector', 'knowledge_agent', 'degraded', 1::numeric, array['degraded_reason','hit_count']),
        ('knowledge.qa', 'qa_timeout', 'explicit', 'knowledge_qa_collector', 'knowledge_agent', 'timeout', 1::numeric, array['timeout_stage']),
        ('knowledge.qa', 'qa_failed', 'exception', 'knowledge_qa_collector', 'knowledge_agent', 'failed', 1::numeric, array['failure_stage']),
        ('evaluation.run', 'evaluation_task_claimed', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'started', 1::numeric, array['worker_name']),
        ('evaluation.run', 'evaluation_run_started', 'before', 'evaluation_run_collector', 'evaluation_agent', 'started', 1::numeric, array['task_id']),
        ('evaluation.run', 'evaluation_config_validated', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'completed', 1::numeric, array['questions_source']),
        ('evaluation.run', 'evaluation_questions_ready', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'completed', 1::numeric, array['question_count','questions_source']),
        ('evaluation.run', 'evaluation_case_started', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'started', 1::numeric, array['case_no','attempt']),
        ('evaluation.run', 'evaluation_case_retry', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'retrying', 1::numeric, array['case_no','attempt','error_category']),
        ('evaluation.run', 'evaluation_case_completed', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'completed', 1::numeric, array['case_no','duration_ms','hit_count','citation_count']),
        ('evaluation.run', 'evaluation_metrics_completed', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'completed', 1::numeric, array['sample_count','conclusion']),
        ('evaluation.run', 'evaluation_report_persisted', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'completed', 1::numeric, array['result_count']),
        ('evaluation.run', 'evaluation_run_completed', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'completed', 1::numeric, array['result_count','failed_count','conclusion']),
        ('evaluation.run', 'evaluation_run_failed', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'failed', 1::numeric, array['failure_stage']),
        ('evaluation.run', 'evaluation_run_timeout', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'timeout', 1::numeric, array['timeout_stage','completed_count']),
        ('evaluation.run', 'evaluation_run_cancelled', 'explicit', 'evaluation_run_collector', 'evaluation_agent', 'cancelled', 1::numeric, array['cancel_source']),
        ('document.ingestion', 'document_ingestion_started', 'before', 'document_ingestion_collector', 'document_index', 'started', 1::numeric, array['source_type']),
        ('document.ingestion', 'document_ingestion_completed', 'after', 'document_ingestion_collector', 'document_index', 'completed', 1::numeric, array['document_id','file_size']),
        ('document.ingestion', 'document_ingestion_failed', 'exception', 'document_ingestion_collector', 'document_index', 'failed', 1::numeric, array['failure_stage']),
        ('document.indexing', 'indexing_task_claimed', 'explicit', 'document_indexing_collector', 'document_index', 'started', 1::numeric, array['worker_name']),
        ('document.indexing', 'indexing_started', 'before', 'document_indexing_collector', 'document_index', 'started', 1::numeric, array['attempt']),
        ('document.indexing', 'indexing_completed', 'after', 'document_indexing_collector', 'document_index', 'completed', 1::numeric, array['document_id','chunk_count','index_version']),
        ('document.indexing', 'indexing_failed', 'exception', 'document_indexing_collector', 'document_index', 'failed', 1::numeric, array['failure_stage']),
        ('document.indexing', 'indexing_timeout', 'explicit', 'document_indexing_collector', 'document_index', 'timeout', 1::numeric, array['timeout_stage','processed_count']),
        ('api.http', 'http_request_completed', 'after', 'http_request_collector', 'api', 'completed', 1::numeric, array['method','path','status_code']),
        ('api.http', 'http_request_failed', 'exception', 'http_request_collector', 'api', 'failed', 1::numeric, array['method','path','status_code']),
        ('db.execute', 'db_operation_completed', 'after', 'sql_operation_collector', 'database', 'completed', 1::numeric, array['operation','query_summary','row_count','slow']),
        ('db.execute', 'db_operation_failed', 'exception', 'sql_operation_collector', 'database', 'failed', 1::numeric, array['operation','query_summary','slow']),
        ('worker.lifecycle', 'worker_started', 'explicit', 'worker_lifecycle_collector', 'worker', 'started', 1::numeric, array['worker_name']),
        ('worker.lifecycle', 'worker_heartbeat', 'explicit', 'worker_lifecycle_collector', 'worker', 'healthy', 1::numeric, array['worker_name']),
        ('worker.lifecycle', 'worker_idle', 'explicit', 'worker_lifecycle_collector', 'worker', 'idle', 0.1::numeric, array['worker_name']),
        ('worker.lifecycle', 'worker_task_claimed', 'explicit', 'worker_lifecycle_collector', 'worker', 'started', 1::numeric, array['worker_name','task_id']),
        ('worker.lifecycle', 'worker_stopped', 'explicit', 'worker_lifecycle_collector', 'worker', 'stopped', 1::numeric, array['worker_name']),
        ('worker.lifecycle', 'worker_failed', 'explicit', 'worker_lifecycle_collector', 'worker', 'failed', 1::numeric, array['worker_name']),
        ('probe.api', 'api_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.api', 'api_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.database', 'database_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.database', 'database_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.llm', 'llm_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.llm', 'llm_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.embedding', 'embedding_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.embedding', 'embedding_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.rerank', 'rerank_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.rerank', 'rerank_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.vector', 'vector_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.vector', 'vector_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.storage', 'storage_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['latency_ms']),
        ('probe.storage', 'storage_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('probe.worker', 'worker_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['worker_count','stale_count']),
        ('probe.worker', 'worker_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['worker_count','stale_count']),
        ('probe.task_backlog', 'task_backlog_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['pending_count','oldest_wait_seconds']),
        ('probe.task_backlog', 'task_backlog_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['pending_count']),
        ('capacity.database', 'database_capacity_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['usage','used','capacity','unit','threshold','current_database_connections','active_connections','idle_connections','reserved_connections','pool_used','pool_size','pool_idle','pool_capacity']),
        ('capacity.database', 'database_capacity_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['usage','used','capacity','unit','threshold','current_database_connections','active_connections','idle_connections','reserved_connections','pool_used','pool_size','pool_idle','pool_capacity']),
        ('capacity.queue', 'task_queue_capacity_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['usage','used','capacity','unit','threshold','oldest_wait_seconds']),
        ('capacity.queue', 'task_queue_capacity_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['usage','used','capacity','unit','threshold','oldest_wait_seconds']),
        ('capacity.file_storage', 'file_storage_capacity_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['usage','used','capacity','unit','threshold']),
        ('capacity.file_storage', 'file_storage_capacity_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['usage','used','capacity','unit','threshold']),
        ('capacity.vector_storage', 'vector_storage_capacity_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['usage','used','capacity','unit','threshold']),
        ('capacity.vector_storage', 'vector_storage_capacity_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['usage','used','capacity','unit','threshold']),
        ('probe.qa', 'knowledge_qa_probe_completed', 'periodic', 'status_probe_collector', 'probe', 'healthy', 1::numeric, array['hit_count','citation_count','latency_ms']),
        ('probe.qa', 'knowledge_qa_probe_failed', 'periodic_error', 'status_probe_collector', 'probe', 'failed', 1::numeric, array['latency_ms']),
        ('collector.self', 'collector_cycle_completed', 'periodic', 'collector_self_collector', 'collector', 'healthy', 1::numeric, array['target_count','success_count','failure_count']),
        ('collector.self', 'collector_cycle_failed', 'periodic_error', 'collector_self_collector', 'collector', 'failed', 1::numeric, array['target_count','success_count','failure_count']),
        ('collector.self', 'collector_recovery_completed', 'explicit', 'collector_self_collector', 'collector', 'recovered', 1::numeric, array['failure_count','dropped_count','target_count','last_failure_at'])
) as action(
    target_code,
    event_type,
    hook,
    collector,
    source_type,
    event_status,
    sampling_rate,
    payload_allowlist
)
on conflict (target_code, event_type, version) do update
set field_mapping = excluded.field_mapping,
    sampling_rate = excluded.sampling_rate,
    enabled = excluded.enabled;

-- 旧资源容量探针使用本地暂存目录磁盘使用率，不属于需求范围，删除登记及当前快照。
delete from t_monitor_gather_action where target_code = 'probe.capacity';
delete from t_monitor_gather_target where target_code = 'probe.capacity';
delete from t_monitor_state_snapshot where resource_code = 'platform-capacity';

-- 自主监控指标定义由系统发布，页面只读取定义和真实聚合结果。
insert into t_monitor_metric_definition (
    metric_code,
    metric_name,
    metric_domain,
    unit,
    formula,
    dimensions,
    minimum_sample_count,
    status,
    version
)
values
    ('qa_request_count', '问答请求量', 'qa', 'count', '统计窗口内进入知识库问答链路的请求数量。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1),
    ('qa_success_rate', '问答成功率', 'qa', 'percent', '成功完成且未降级的问答请求数 / 有效问答请求总数。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1),
    ('qa_error_rate', '问答错误率', 'qa', 'percent', '失败、异常或超时的问答请求数 / 有效问答请求总数。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1),
    ('qa_timeout_rate', '问答超时率', 'qa', 'percent', '超时问答请求数 / 有效问答请求总数。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1),
    ('qa_reference_rate', '问答引用率', 'qa', 'percent', '返回有效引用的成功问答数 / 成功问答请求数。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1),
    ('qa_p95', '问答 P95', 'qa', 'ms', '统计窗口内成功问答请求耗时的第 95 百分位。', '{"scope":["platform","tenant","knowledge_base"]}', 20, 'active', 1),
    ('database_connection_usage', '数据库连接使用率', 'platform', 'percent', '数据库当前连接数 / 数据库允许的最大连接数。', '{"scope":["platform"]}', 1, 'active', 1),
    ('task_queue_usage', '任务队列使用率', 'platform', 'percent', '当前排队任务数 / 系统发布的队列容量。', '{"scope":["platform","tenant"]}', 1, 'active', 1),
    ('file_storage_usage', '文件存储使用率', 'platform', 'percent', '文件存储已使用字节数 / 系统发布的文件存储配额。', '{"scope":["platform"]}', 1, 'active', 1),
    ('vector_storage_usage', '向量存储使用率', 'platform', 'percent', '向量数据已使用字节数 / 系统发布的向量存储配额。', '{"scope":["platform"]}', 1, 'active', 1),
    ('vector_service_availability', '向量服务可用率', 'platform', 'percent', '向量服务成功探测次数 / 有效探测总数。', '{"scope":["platform"]}', 3, 'active', 1),
    ('task_backlog_count', '任务积压数量', 'task', 'count', '统计时点处于待处理或排队中的异步任务数量。', '{"scope":["platform","tenant"],"task_type":true}', 1, 'active', 1),
    ('task_wait_p95', '任务等待 P95', 'task', 'ms', '统计窗口内任务从创建到开始执行等待时长的第 95 百分位。', '{"scope":["platform","tenant"],"task_type":true}', 20, 'active', 1),
    ('task_success_rate', '任务成功率', 'task', 'percent', '成功完成任务数 / 已结束任务总数。', '{"scope":["platform","tenant"],"task_type":true}', 1, 'active', 1),
    ('evaluation_completion_rate', '评测完成率', 'evaluation', 'percent', '成功完成评测运行数 / 已结束评测运行总数。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1),
    ('evaluation_evidence_completeness', '评测执行证明完整率', 'evaluation', 'percent', '具备完整 Agent 生命周期证据的评测运行数 / 已结束评测运行总数。', '{"scope":["platform","tenant","knowledge_base"]}', 1, 'active', 1)
on conflict (metric_code, version) do update
set metric_name = excluded.metric_name,
    metric_domain = excluded.metric_domain,
    unit = excluded.unit,
    formula = excluded.formula,
    dimensions = excluded.dimensions,
    minimum_sample_count = excluded.minimum_sample_count,
    status = excluded.status,
    updated_at = now();

-- 指标判定规则由系统发布；比例指标统一使用 0 至 1，耗时统一使用毫秒。
-- trigger_type=lower_than 表示低于阈值异常，higher_than 表示高于阈值异常，informational 仅确认数据可用性。
insert into t_monitor_metric_rule (
    metric_code,
    scope_type,
    warning_threshold,
    critical_threshold,
    recovery_threshold,
    minimum_sample_count,
    consecutive_periods,
    window_seconds,
    trigger_type,
    recovery_periods,
    enabled,
    version,
    effective_at,
    created_by
)
values
    ('qa_request_count', 'all', null, null, null, 1, 1, 300, 'informational', 1, true, 1, now(), 'system-release'),
    ('qa_success_rate', 'all', 0.98, 0.95, 0.99, 1, 1, 300, 'lower_than', 1, true, 1, now(), 'system-release'),
    ('qa_error_rate', 'all', 0.01, 0.05, 0.005, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('qa_timeout_rate', 'all', 0.01, 0.03, 0.005, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('qa_reference_rate', 'all', 0.90, 0.80, 0.95, 1, 1, 300, 'lower_than', 1, true, 1, now(), 'system-release'),
    ('qa_p95', 'all', 3000, 8000, 2000, 20, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('database_connection_usage', 'all', 0.70, 0.85, 0.65, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('task_queue_usage', 'all', 0.70, 0.90, 0.60, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('file_storage_usage', 'all', 0.70, 0.85, 0.65, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('vector_storage_usage', 'all', 0.70, 0.85, 0.65, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('vector_service_availability', 'all', 0.99, 0.95, 0.999, 3, 1, 300, 'lower_than', 1, true, 1, now(), 'system-release'),
    ('task_backlog_count', 'all', 10, 50, 5, 1, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('task_wait_p95', 'all', 60000, 300000, 30000, 20, 1, 300, 'higher_than', 1, true, 1, now(), 'system-release'),
    ('task_success_rate', 'all', 0.95, 0.90, 0.98, 1, 1, 300, 'lower_than', 1, true, 1, now(), 'system-release'),
    ('evaluation_completion_rate', 'all', 0.95, 0.85, 0.98, 1, 1, 300, 'lower_than', 1, true, 1, now(), 'system-release'),
    ('evaluation_evidence_completeness', 'all', 0.99, 0.95, 1.00, 1, 1, 300, 'lower_than', 1, true, 1, now(), 'system-release')
on conflict (metric_code, scope_type, version) do update
set warning_threshold = excluded.warning_threshold,
    critical_threshold = excluded.critical_threshold,
    recovery_threshold = excluded.recovery_threshold,
    minimum_sample_count = excluded.minimum_sample_count,
    consecutive_periods = excluded.consecutive_periods,
    window_seconds = excluded.window_seconds,
    trigger_type = excluded.trigger_type,
    recovery_periods = excluded.recovery_periods,
    enabled = excluded.enabled,
    effective_at = excluded.effective_at,
    updated_at = now();
