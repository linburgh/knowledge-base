-- Platform user trend test data for local development only.
-- This file is independent from data_table_dml.sql and can be executed repeatedly.
-- It creates 100 active users from 2026-07-01 through 2026-07-19 (Asia/Shanghai).
-- For the full range, query the platform overview API with:
-- range=custom&start_at=2026-07-01T00:00:00%2B08:00&end_at=2026-07-20T00:00:00%2B08:00

begin;

insert into t_user (
    username,
    email,
    phone,
    display_name,
    status,
    last_login_at,
    created_at,
    updated_at
)
select
    format('trend-user-%s', lpad(item::text, 3, '0')),
    format('trend-user-%s@example.test', lpad(item::text, 3, '0')),
    format('1390000%s', lpad(item::text, 4, '0')),
    format('趋势测试用户 %s', lpad(item::text, 3, '0')),
    'active',
    case
        when item % 3 <> 0 then created_at + interval '2 hours'
        else null
    end,
    created_at,
    created_at
from (
    select
        item,
        timestamp with time zone '2026-07-01 09:00:00+08:00'
            + ((item - 1) % 19) * interval '1 day'
            + ((item - 1) / 19) * interval '1 hour' as created_at
    from generate_series(1, 100) as series(item)
) as generated_users
on conflict (username) do update
set email = excluded.email,
    phone = excluded.phone,
    display_name = excluded.display_name,
    status = excluded.status,
    last_login_at = excluded.last_login_at,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;

commit;
