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
    ),
    (
        'guest',
        'guest@example.test',
        '访客演示用户',
        'pbkdf2_sha256$600000$bzprv0AXG4F1w3VMS7iOOQ$yfJ84ElYmceMh16aM9eUbs32tlpK4EKygjO1Eolg9x4',
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
        ('single-tenant', 'demo-tenant-a', 'member', true),
        ('guest', 'demo-tenant-a', 'tenant_guest', true)
) as membership(username, tenant_code, role_code, is_primary)
join t_user demo_user on demo_user.username = membership.username
join t_tenant demo_tenant on demo_tenant.code = membership.tenant_code
on conflict (tenant_id, user_id) do update
set role_code = excluded.role_code,
    is_primary = excluded.is_primary,
    status = excluded.status,
    updated_at = now();

-- tenant_guest 测试账号使用演示企业租户中的独立组织和知识库。
insert into t_organization (
    tenant_id,
    parent_id,
    code,
    name,
    status
)
select demo_tenant.id, null, 'demo-guest-org', '访客测试组织', 'active'
from t_tenant demo_tenant
where demo_tenant.code = 'demo-tenant-a'
on conflict (tenant_id, code) do update
set name = excluded.name,
    status = excluded.status,
    updated_at = now();

insert into t_organization_member (
    organization_id,
    user_id,
    role_code,
    is_primary,
    status,
    joined_at
)
select demo_org.id, demo_user.id, 'org_member', true, 'active', now()
from t_organization demo_org
join t_tenant demo_tenant on demo_tenant.id = demo_org.tenant_id
join t_user demo_user on demo_user.username = 'guest'
where demo_tenant.code = 'demo-tenant-a'
  and demo_org.code = 'demo-guest-org'
on conflict (organization_id, user_id) do update
set role_code = excluded.role_code,
    is_primary = excluded.is_primary,
    status = excluded.status,
    updated_at = now();

insert into t_knowledge_base (
    tenant_id,
    organization_id,
    name,
    description,
    owner_id,
    visibility,
    embedding_model,
    chunk_size,
    chunk_overlap,
    retrieval_top_k,
    system_prompt,
    system_prompt_version,
    created_by,
    status
)
select demo_tenant.id,
       demo_org.id,
       '访客测试知识库',
       '用于验证 tenant_guest 授权数据源、搜索分页和问答流程',
       'guest',
       'private',
       'text-embedding-3-small',
       600,
       100,
       5,
       '',
       1,
       demo_user.id,
       'active'
from t_tenant demo_tenant
join t_organization demo_org
  on demo_org.tenant_id = demo_tenant.id
 and demo_org.code = 'demo-guest-org'
join t_user demo_user on demo_user.username = 'guest'
where demo_tenant.code = 'demo-tenant-a'
  and not exists (
      select 1
      from t_knowledge_base existing_kb
      where existing_kb.tenant_id = demo_tenant.id
        and existing_kb.name = '访客测试知识库'
  );

insert into t_knowledge_base_organization (
    kb_id,
    organization_id,
    created_by
)
select demo_kb.id, demo_org.id, demo_user.id
from t_knowledge_base demo_kb
join t_organization demo_org
  on demo_org.tenant_id = demo_kb.tenant_id
 and demo_org.code = 'demo-guest-org'
join t_tenant demo_tenant on demo_tenant.id = demo_kb.tenant_id
join t_user demo_user on demo_user.username = 'guest'
where demo_tenant.code = 'demo-tenant-a'
  and demo_kb.name = '访客测试知识库'
on conflict (kb_id, organization_id) do nothing;

commit;
