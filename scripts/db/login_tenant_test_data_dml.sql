-- 登录与多租户选择测试数据，仅用于本地开发环境。
-- 可重复执行，不删除现有业务数据。

begin;

-- 两个有效租户，用于验证多租户选择。
insert into t_tenant (
    code,
    name,
    contact_name,
    contact_email,
    status
)
values
    ('demo-tenant-a', '演示企业租户', '演示联系人 A', 'demo-a@example.test', 'active'),
    ('demo-tenant-b', '演示产品租户', '演示联系人 B', 'demo-b@example.test', 'active')
on conflict (code) do update
set name = excluded.name,
    contact_name = excluded.contact_name,
    contact_email = excluded.contact_email,
    status = excluded.status,
    updated_at = now();

-- 三个登录演示账号的密码分别为：linburgh、multi-tenant、single-tenant。
-- 密码哈希使用项目当前 PBKDF2-SHA256 格式生成。
insert into t_user (
    username,
    email,
    display_name,
    password_hash,
    status
)
values
    (
        'linburgh',
        'linburgh@example.test',
        '林堡',
        'pbkdf2_sha256$600000$lxHBc5sq50sfZlkB6AJydg$JFSkYfym5Pt3tTOCYCUJWHWqdomj5XZntMxqII092pY',
        'active'
    ),
    (
        'multi-tenant',
        'multi-tenant@example.test',
        '多租户演示用户',
        'pbkdf2_sha256$600000$qxsRY4mg7idGfB7mBAxN3w$K58Ec-_WAySS7wFbPRlb5zTf833W-N1Vi9yoAUHwyMw',
        'active'
    ),
    (
        'single-tenant',
        'single-tenant@example.test',
        '单租户演示用户',
        'pbkdf2_sha256$600000$VKvr5R5XsqRdDuPTnfw57A$QY36xzngnYG6klqCljhUPit3qtRaTLVGVm_rFa25sZw',
        'active'
    )
on conflict (username) do update
set email = excluded.email,
    display_name = excluded.display_name,
    password_hash = excluded.password_hash,
    status = excluded.status,
    updated_at = now();

insert into t_platform_role (code, name, description, status)
values ('p_super_admin', '平台超级管理员', '可以操作平台范围内全部资源', 'active')
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    status = excluded.status,
    updated_at = now();

insert into t_platform_user_role (user_id, role_id)
select demo_user.id, platform_role.id
from t_user demo_user
join t_platform_role platform_role
  on platform_role.code = 'p_super_admin'
where demo_user.username = 'linburgh'
on conflict (user_id, role_id) do nothing;

-- 平台管理员覆盖两个租户，多租户账号覆盖两个租户，单租户账号只覆盖 A 租户。
insert into t_tenant_member (
    tenant_id,
    user_id,
    role_code,
    is_primary,
    status,
    joined_at
)
select
    demo_tenant.id,
    demo_user.id,
    membership.role_code,
    membership.is_primary,
    'active',
    now()
from (
    values
        ('linburgh', 'demo-tenant-a', 'tenant_owner', true),
        ('linburgh', 'demo-tenant-b', 'tenant_owner', false),
        ('multi-tenant', 'demo-tenant-a', 'member', true),
        ('multi-tenant', 'demo-tenant-b', 'member', false),
        ('single-tenant', 'demo-tenant-a', 'member', true)
) as membership(username, tenant_code, role_code, is_primary)
join t_user demo_user on demo_user.username = membership.username
join t_tenant demo_tenant on demo_tenant.code = membership.tenant_code
on conflict (tenant_id, user_id) do update
set role_code = excluded.role_code,
    is_primary = excluded.is_primary,
    status = excluded.status,
    updated_at = now();

commit;
