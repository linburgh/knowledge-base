-- Tenant resource distribution test data for local development only.
-- This file is independent from the other test DML files and is repeatable.
-- It associates 100 trend users with five tenants and creates two knowledge
-- bases for each tenant so the overview chart has three visible bar series.

begin;

-- Distribute the 100 trend users evenly across the first five test tenants.
insert into t_tenant_member (
    tenant_id,
    user_id,
    role_code,
    is_primary,
    status,
    joined_at
)
select
    tenant.id,
    trend_user.id,
    'member',
    false,
    'active',
    trend_user.created_at
from generate_series(1, 100) as series(item)
join t_tenant tenant
    on tenant.code = format(
        'test-tenant-%s',
        lpad((((series.item - 1) % 5) + 1)::text, 2, '0')
    )
join t_user trend_user
    on trend_user.username = format('trend-user-%s', lpad(series.item::text, 3, '0'))
on conflict (tenant_id, user_id) do update
set role_code = excluded.role_code,
    is_primary = excluded.is_primary,
    status = excluded.status,
    joined_at = excluded.joined_at,
    updated_at = now();

-- Create two knowledge bases for each of the first five test tenants.
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
    system_prompt_updated_at,
    created_by,
    status,
    created_at,
    updated_at
)
select
    tenant.id,
    root_organization.id,
    format('趋势测试知识库 %s-%s', tenant_number.item, knowledge_base_number.item),
    format('用于租户资源分布测试的知识库 %s-%s', tenant_number.item, knowledge_base_number.item),
    owner_user.username,
    'private',
    'text-embedding-3-small',
    600,
    100,
    5,
    '',
    1,
    timestamps.created_at,
    owner_user.id,
    'active',
    timestamps.created_at,
    timestamps.created_at
from generate_series(1, 5) as tenant_number(item)
cross join generate_series(1, 2) as knowledge_base_number(item)
join t_tenant tenant
    on tenant.code = format('test-tenant-%s', lpad(tenant_number.item::text, 2, '0'))
join t_organization root_organization
    on root_organization.tenant_id = tenant.id
   and root_organization.code = format('test-org-%s-root', lpad(tenant_number.item::text, 2, '0'))
join t_user owner_user
    on owner_user.username = format('trend-user-%s', lpad(tenant_number.item::text, 3, '0'))
cross join lateral (
    select timestamp with time zone '2026-07-01 10:00:00+08:00'
        + ((tenant_number.item - 1) * 3 + knowledge_base_number.item - 1) * interval '1 day'
        as created_at
) as timestamps
where not exists (
    select 1
    from t_knowledge_base existing
    where existing.tenant_id = tenant.id
      and existing.name = format('趋势测试知识库 %s-%s', tenant_number.item, knowledge_base_number.item)
);

-- Keep prompt history consistent with the inserted knowledge bases.
insert into t_knowledge_base_prompt (
    kb_id,
    version,
    system_prompt,
    created_by
)
select
    knowledge_base.id,
    1,
    knowledge_base.system_prompt,
    knowledge_base.owner_id
from t_knowledge_base knowledge_base
where knowledge_base.name like '趋势测试知识库 %'
  and not exists (
      select 1
      from t_knowledge_base_prompt prompt
      where prompt.kb_id = knowledge_base.id
        and prompt.version = 1
  );

commit;
