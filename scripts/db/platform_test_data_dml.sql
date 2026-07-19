-- Platform management test data for local development only.
-- This file is intentionally independent from data_table_dml.sql.
-- It is safe to execute repeatedly and does not delete existing data.

begin;

-- 50 test tenants for the platform tenant list.
insert into t_tenant (
    code,
    name,
    contact_name,
    contact_email,
    status
)
select
    format('test-tenant-%s', lpad(item::text, 2, '0')),
    format('测试租户 %s', lpad(item::text, 2, '0')),
    format('测试联系人 %s', lpad(item::text, 2, '0')),
    format('tenant-%s@example.test', lpad(item::text, 2, '0')),
    case when item % 10 = 0 then 'trial' else 'active' end
from generate_series(1, 50) as series(item)
on conflict (code) do update
set name = excluded.name,
    contact_name = excluded.contact_name,
    contact_email = excluded.contact_email,
    status = excluded.status,
    updated_at = now();

-- 10 root organizations. Each root belongs to one of the first 10 test tenants.
insert into t_organization (
    tenant_id,
    parent_id,
    code,
    name,
    status
)
select
    tenant.id,
    null,
    format('test-org-%s-root', lpad(series.item::text, 2, '0')),
    format('测试组织 %s 总部', lpad(series.item::text, 2, '0')),
    'active'
from generate_series(1, 10) as series(item)
join t_tenant tenant
    on tenant.code = format('test-tenant-%s', lpad(series.item::text, 2, '0'))
on conflict (tenant_id, code) do update
set name = excluded.name,
    status = excluded.status,
    updated_at = now();

-- 40 child organizations: four children under each of the 10 root organizations.
insert into t_organization (
    tenant_id,
    parent_id,
    code,
    name,
    status
)
select
    tenant.id,
    root.id,
    format(
        'test-org-%s-%s',
        lpad(tenant_number.item::text, 2, '0'),
        child_number.item
    ),
    format(
        '测试组织 %s %s',
        lpad(tenant_number.item::text, 2, '0'),
        case child_number.item
            when 1 then '技术中心'
            when 2 then '产品中心'
            when 3 then '运营中心'
            else '综合管理部'
        end
    ),
    case when child_number.item = 4 then 'disabled' else 'active' end
from generate_series(1, 10) as tenant_number(item)
cross join generate_series(1, 4) as child_number(item)
join t_tenant tenant
    on tenant.code = format('test-tenant-%s', lpad(tenant_number.item::text, 2, '0'))
join t_organization root
    on root.tenant_id = tenant.id
   and root.code = format('test-org-%s-root', lpad(tenant_number.item::text, 2, '0'))
on conflict (tenant_id, code) do update
set parent_id = excluded.parent_id,
    name = excluded.name,
    status = excluded.status,
    updated_at = now();

commit;
