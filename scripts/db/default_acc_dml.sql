-- 默认联调测试账号初始化脚本。
--
-- 本脚本只维护非敏感的账号、租户、组织和角色关系；密码哈希必须在执行时
-- 通过 psql 变量注入，禁止把明文密码或固定密码哈希提交到仓库。
-- 推荐由 app.core.common.auth.hash_password 生成与当前认证实现兼容的哈希。

\if :{?linburgh_password_hash}
\else
\echo '缺少 psql 变量：linburgh_password_hash'
\quit
\endif
\if :{?tenant_admin_acc_password_hash}
\else
\echo '缺少 psql 变量：tenant_admin_acc_password_hash'
\quit
\endif
\if :{?zhangfei_password_hash}
\else
\echo '缺少 psql 变量：zhangfei_password_hash'
\quit
\endif
\if :{?zhugeliang_password_hash}
\else
\echo '缺少 psql 变量：zhugeliang_password_hash'
\quit
\endif
\if :{?guest_password_hash}
\else
\echo '缺少 psql 变量：guest_password_hash'
\quit
\endif
\if :{?multi_tenant_password_hash}
\else
\echo '缺少 psql 变量：multi_tenant_password_hash'
\quit
\endif
\if :{?single_tenant_password_hash}
\else
\echo '缺少 psql 变量：single_tenant_password_hash'
\quit
\endif

begin;

-- 确保测试账号引用的固定角色已经存在；重复执行时同步角色名称和启用状态。
insert into t_platform_role (code, name, description, status)
values ('p_super_admin', '平台超级管理员', '可以操作平台范围内全部资源', 'active')
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    status = excluded.status,
    updated_at = now();

insert into t_tenant_role (code, name, description, status, sort_order)
values
    ('tenant_admin', '租户管理员', '负责当前租户范围内的成员、组织和业务资源管理', 'active', 10),
    ('tenant_member', '租户成员', '当前租户内的普通成员角色', 'active', 20),
    ('tenant_guest', '租户访客', '使用当前租户授权的独立问答资源', 'active', 30)
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    status = excluded.status,
    sort_order = excluded.sort_order,
    updated_at = now();

insert into t_organization_role (code, name, description, status, sort_order)
values
    ('org_admin', '组织管理员', '负责当前组织范围内的成员和业务资源管理', 'active', 10),
    ('org_member', '组织成员', '当前组织内的普通成员角色', 'active', 20)
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    status = excluded.status,
    sort_order = excluded.sort_order,
    updated_at = now();

-- 创建七个文档约定的测试账号。账号已存在时重置为本次注入的测试密码并恢复启用。
insert into t_user (username, email, display_name, password_hash, status)
values
    ('linburgh', 'linburgh@example.test', '林博', :'linburgh_password_hash', 'active'),
    ('tenant-admin-acc', 'tenant-admin-acc@example.test', '租户管理员测试账号', :'tenant_admin_acc_password_hash', 'active'),
    ('zhangfei', 'zhangfei@example.test', '张飞', :'zhangfei_password_hash', 'active'),
    ('zhugeliang', 'zhugeliang@example.test', '诸葛亮', :'zhugeliang_password_hash', 'active'),
    ('guest', 'guest@example.test', '访客演示用户', :'guest_password_hash', 'active'),
    ('multi-tenant', 'multi-tenant@example.test', '多租户演示用户', :'multi_tenant_password_hash', 'active'),
    ('single-tenant', 'single-tenant@example.test', '单租户演示用户', :'single_tenant_password_hash', 'active')
on conflict (username) do update
set email = excluded.email,
    display_name = excluded.display_name,
    password_hash = excluded.password_hash,
    status = excluded.status,
    updated_at = now();

-- 创建覆盖平台、独立租户管理员、角色组合和多租户切换场景的测试租户。
insert into t_tenant (code, name, description, status)
values
    ('demo-enterprise-services', '演示企业服务中心', '平台管理员、访客和单租户成员联调租户', 'active'),
    ('demo-product-innovation', '演示产品创新中心', '多租户切换联调租户', 'active'),
    ('tenant-admin-test', '租户管理员测试租户', '独立租户管理员权限联调租户', 'active'),
    ('example-tenant-services', '示例租户服务中心', '租户与组织组合角色联调租户', 'active')
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    status = excluded.status,
    updated_at = now();

-- 每个租户只配置一个有效 tenant_admin，兼容租户管理员唯一性约束。
with memberships(tenant_code, username, role_code, is_primary) as (
    values
        ('demo-enterprise-services', 'linburgh', 'tenant_admin', true),
        ('demo-product-innovation', 'linburgh', 'tenant_admin', false),
        ('tenant-admin-test', 'tenant-admin-acc', 'tenant_admin', true),
        ('example-tenant-services', 'zhangfei', 'tenant_admin', true),
        ('example-tenant-services', 'zhugeliang', 'tenant_member', true),
        ('demo-enterprise-services', 'guest', 'tenant_guest', true),
        ('demo-enterprise-services', 'multi-tenant', 'tenant_member', true),
        ('demo-product-innovation', 'multi-tenant', 'tenant_member', false),
        ('demo-enterprise-services', 'single-tenant', 'tenant_member', true)
)
insert into t_tenant_member (
    tenant_id,
    user_id,
    role_code,
    is_primary,
    status,
    joined_at
)
select tenant.id, app_user.id, membership.role_code, membership.is_primary, 'active', now()
from memberships membership
join t_tenant tenant on tenant.code = membership.tenant_code
join t_user app_user on app_user.username = membership.username
on conflict (tenant_id, user_id) do update
set role_code = excluded.role_code,
    is_primary = excluded.is_primary,
    status = excluded.status,
    updated_at = now();

-- 平台超级管理员只绑定 linburgh，满足平台角色单例约束。
insert into t_platform_user_role (user_id, role_id, created_by)
select app_user.id, role.id, app_user.id
from t_user app_user
join t_platform_role role on role.code = 'p_super_admin'
where app_user.username = 'linburgh'
on conflict (user_id, role_id) do nothing;

-- 组织编码只要求在租户内唯一；负责人引用用户主键，不创建数据库外键。
with organizations(tenant_code, code, name, leader_username) as (
    values
        ('demo-enterprise-services', 'knowledge-base-headquarters', '知识库总部', 'linburgh'),
        ('demo-enterprise-services', 'guest-service-team', '访客服务团队', 'guest'),
        ('example-tenant-services', 'technical-center', '技术中心', 'zhangfei'),
        ('example-tenant-services', 'operations-center', '运营中心', 'zhugeliang')
)
insert into t_organization (tenant_id, code, name, leader_user_id, status)
select tenant.id, organization.code, organization.name, leader.id, 'active'
from organizations organization
join t_tenant tenant on tenant.code = organization.tenant_code
join t_user leader on leader.username = organization.leader_username
on conflict (tenant_id, code) do update
set name = excluded.name,
    leader_user_id = excluded.leader_user_id,
    status = excluded.status,
    updated_at = now();

with memberships(tenant_code, organization_code, username, role_code) as (
    values
        ('demo-enterprise-services', 'knowledge-base-headquarters', 'linburgh', 'org_admin'),
        ('demo-enterprise-services', 'guest-service-team', 'guest', 'org_member'),
        ('example-tenant-services', 'technical-center', 'zhangfei', 'org_member'),
        ('example-tenant-services', 'operations-center', 'zhugeliang', 'org_member')
)
insert into t_organization_member (
    organization_id,
    user_id,
    role_code,
    is_primary,
    status,
    joined_at
)
select organization.id, app_user.id, membership.role_code, true, 'active', now()
from memberships membership
join t_tenant tenant on tenant.code = membership.tenant_code
join t_organization organization
  on organization.tenant_id = tenant.id
 and organization.code = membership.organization_code
join t_user app_user on app_user.username = membership.username
on conflict (organization_id, user_id) do update
set role_code = excluded.role_code,
    is_primary = excluded.is_primary,
    status = excluded.status,
    updated_at = now();

commit;
