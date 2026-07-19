-- Platform recent activity test data for local development only.
-- Creates 100 audit records between 2026-07-01 and 2026-07-19 (Asia/Shanghai).
-- The request_id guard makes this script safe to execute repeatedly.

begin;

insert into t_audit_log (
    actor_id,
    action,
    target_type,
    target_id,
    request_id,
    request_summary,
    result,
    error_message,
    created_at
)
select
    format('trend-user-%s', lpad((((series.item - 1) % 100) + 1)::text, 3, '0')),
    case series.item % 5
        when 0 then '创建知识库'
        when 1 then '新增用户'
        when 2 then '加入租户'
        when 3 then '创建组织'
        else '完成文档索引'
    end,
    case series.item % 5
        when 0 then 'knowledge_base'
        when 1 then 'user'
        when 2 then 'tenant_member'
        when 3 then 'organization'
        else 'document'
    end,
    case series.item % 5
        when 0 then format('趋势测试知识库 %s-%s', ((series.item - 1) % 5) + 1, ((series.item - 1) % 2) + 1)
        when 1 then format('trend-user-%s', lpad((((series.item - 1) % 100) + 1)::text, 3, '0'))
        when 2 then format('test-tenant-%s', lpad(((series.item - 1) % 5 + 1)::text, 2, '0'))
        when 3 then format('test-org-%s-root', lpad(((series.item - 1) % 10 + 1)::text, 2, '0'))
        else format('trend-document-%s', lpad(series.item::text, 3, '0'))
    end,
    format('platform-activity-test-%s', lpad(series.item::text, 3, '0')),
    jsonb_build_object('source', 'platform_activity_test_data', 'sequence', series.item),
    case when series.item % 17 = 0 then 'failure' else 'success' end,
    case when series.item % 17 = 0 then '测试失败记录' else null end,
    timestamp with time zone '2026-07-01 08:30:00+08:00'
        + ((series.item - 1) % 19) * interval '1 day'
        + ((series.item - 1) / 19) * interval '1 hour'
from generate_series(1, 100) as series(item)
where not exists (
    select 1
    from t_audit_log existing
    where existing.request_id = format('platform-activity-test-%s', lpad(series.item::text, 3, '0'))
);

commit;
