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

with role_menus(role_scope, role_code, menu_code) as (
    values
        ('platform', 'p_super_admin', 'platform'),
        ('platform', 'p_super_admin', 'platform_overview'),
        ('platform', 'p_super_admin', 'platform_users'),
        ('platform', 'p_super_admin', 'platform_tenants'),
        ('platform', 'p_super_admin', 'platform_organizations'),
        ('platform', 'p_super_admin', 'developer_api'),
        ('platform', 'p_super_admin', 'knowledge_base'),
        ('platform', 'p_super_admin', 'knowledge_base_list'),
        ('platform', 'p_super_admin', 'knowledge_base_workspace'),
        ('platform', 'p_super_admin', 'knowledge_base_overview'),
        ('platform', 'p_super_admin', 'knowledge_base_documents'),
        ('platform', 'p_super_admin', 'knowledge_base_chat'),
        ('tenant', 'tenant_owner', 'platform_organizations'),
        ('tenant', 'tenant_owner', 'knowledge_base'),
        ('tenant', 'tenant_owner', 'knowledge_base_list'),
        ('tenant', 'tenant_owner', 'knowledge_base_workspace'),
        ('tenant', 'tenant_owner', 'knowledge_base_overview'),
        ('tenant', 'tenant_owner', 'knowledge_base_documents'),
        ('tenant', 'tenant_owner', 'knowledge_base_chat'),
        ('tenant', 'tenant_admin', 'platform_organizations'),
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
        ('organization', 'org_member', 'knowledge_base_documents'),
        ('organization', 'org_member', 'knowledge_base_chat')
)
insert into t_role_menu (role_scope, role_code, menu_id)
select role_menus.role_scope, role_menus.role_code, menu.id
from role_menus
join t_system_menu menu on menu.code = role_menus.menu_code
on conflict (role_scope, role_code, menu_id) do update
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
