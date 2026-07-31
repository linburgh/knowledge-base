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

insert into t_role_menu (role_scope, role_code, menu_id, status)
select role_item.role_scope, role_item.role_code, menu.id, 'active'
from (values ('platform', 'p_super_admin'), ('tenant', 'tenant_admin')) as role_item(role_scope, role_code)
cross join t_system_menu menu
where (menu.code = 'monitoring' or menu.code like 'monitoring_%')
  and not exists (
      select 1 from t_role_menu relation
      where relation.role_scope = role_item.role_scope
        and relation.role_code = role_item.role_code
        and relation.menu_id = menu.id
  );

insert into t_system_menu_action (menu_id, code, name, action_type, sort_order, status)
select menu.id, action.code, action.name, 'button', action.sort_order, 'active'
from t_system_menu menu
cross join (values
    ('monitoring_overview', 'monitoring:list', '查看监控', 1),
    ('monitoring_alerts', 'monitoring:detail', '查看告警', 1),
    ('monitoring_alerts', 'monitoring:alert-action', '处理告警', 2),
    ('monitoring_alerts', 'monitoring:rule-manage', '管理规则', 3),
    ('monitoring_alerts', 'monitoring:notification-manage', '管理通知', 4),
    ('monitoring_analysis', 'monitoring:analysis', '使用分析', 1)
) as action(menu_code, code, name, sort_order)
where menu.code = action.menu_code
  and not exists (select 1 from t_system_menu_action existing where existing.code = action.code);

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
