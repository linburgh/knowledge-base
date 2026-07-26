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
        ('tenant', 'tenant_owner', 'platform_organizations', null),
        ('tenant', 'tenant_owner', 'knowledge_base_list', null),
        ('tenant', 'tenant_owner', 'knowledge_base_overview', null),
        ('tenant', 'tenant_owner', 'knowledge_base_documents', null),
        ('tenant', 'tenant_owner', 'knowledge_base_chat', null),
        ('tenant', 'tenant_admin', 'platform_organizations', null),
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

-- 自主评测列表演示数据：约 100 条，用于分页、筛选、状态和长文本验证。
-- 任务名称前缀保证脚本可重复执行，也便于验收后清理。
with seed as (
    select
        gs,
        '自主评测演示任务' || lpad(gs::text, 3, '0') || case when gs in (7, 28, 49, 70, 91) then '超长名称用于列表省略和 Tooltip 验证' else '' end as task_name,
        (array[2, 3, 4, 5, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28])[((gs - 1) % 22) + 1] as kb_id,
        case when gs % 2 = 0 then 'generated' else 'imported' end as questions_source,
        10 + ((gs * 7) % 91) as questions_count
    from generate_series(1, 100) as series(gs)
)
insert into t_evaluation_task (name, kb_id, config, status, created_by, created_at, updated_at)
select
    task_name,
    kb_id,
    jsonb_build_object(
        'kb_id', kb_id,
        'questions_source', questions_source,
        'questions_count', questions_count,
        'questions_file', case when questions_source = 'imported' then 'demo-questions-' || gs || '.jsonl' else null end,
        'questions_instruction', case when questions_source = 'generated' then '问题表达自然、覆盖核心业务场景。' else null end,
        'business_scope_source', case when questions_source = 'generated' then 'description_and_knowledge_base' else 'knowledge_base' end,
        'business_description', case when questions_source = 'generated' then '验证产品能力、使用流程、部署方式和常见问题。' else null end,
        'user_id', 204,
        'concurrency', 3,
        'request_timeout_seconds', 120,
        'retry_count', 0,
        'keep_conversation', false,
        'gates', jsonb_build_object(
            'success_rate', jsonb_build_object('operator', '>=', 'value', 0.95),
            'error_rate', jsonb_build_object('operator', '<=', 'value', 0.01),
            'fallback_rate', jsonb_build_object('operator', '<=', 'value', 0.05),
            'citation_rate', jsonb_build_object('operator', '>=', 'value', 0.95),
            'p95_duration_ms', jsonb_build_object('operator', '<=', 'value', 8000)
        )
    ),
    'active',
    '204',
    now() - make_interval(days => (100 - gs) % 30, mins => gs),
    now() - make_interval(days => (100 - gs) % 30, mins => gs)
from seed
where not exists (
    select 1 from t_evaluation_task existing where existing.name = seed.task_name
);

with seed as (
    select
        task.id as task_id,
        task.config,
        row_number() over (order by task.id) as sequence_no
    from t_evaluation_task task
    where task.name like '自主评测演示任务%'
      and task.status = 'active'
)
insert into t_evaluation_run (
    task_id, run_no, status, conclusion, config_snapshot, metrics, report,
    question_count, started_at, finished_at, created_at
)
select
    task_id,
    1,
    case
        when sequence_no % 7 = 1 then 'running'
        when sequence_no % 7 = 2 then 'completed'
        when sequence_no % 7 = 3 then 'failed'
        when sequence_no % 7 = 4 then 'cancelled'
        when sequence_no % 7 = 5 then 'completed'
        when sequence_no % 7 = 6 then 'pending'
        else 'completed'
    end,
    case
        when sequence_no % 7 = 2 then 'passed'
        when sequence_no % 7 = 5 then 'failed'
        when sequence_no % 7 = 0 then 'indeterminate'
        else null
    end,
    config,
    '{}'::jsonb,
    '{}'::jsonb,
    (config ->> 'questions_count')::integer,
    case when sequence_no % 7 in (1, 2, 3, 4, 5, 0) then now() - interval '1 hour' else null end,
    case when sequence_no % 7 in (2, 3, 4, 5, 0) then now() - interval '30 minutes' else null end,
    now() - make_interval(mins => sequence_no::integer)
from seed
on conflict (task_id, run_no) do nothing;

-- 为演示任务补齐查看结果抽屉所需的运行摘要、指标、报告和逐题结果。
with seed as (
    select
        run.id as run_id,
        run.task_id,
        run.status,
        run.conclusion,
        row_number() over (order by run.id) as sequence_no,
        run.question_count
    from t_evaluation_run run
    join t_evaluation_task task on task.id = run.task_id
    where task.name like '自主评测演示任务%'
      and run.run_no = 1
)
update t_evaluation_run run
set
    conclusion = case
        when seed.conclusion is not null then seed.conclusion
        when seed.status in ('failed', 'cancelled') then 'indeterminate'
        else null
    end,
    metrics = jsonb_build_object(
        'metrics', jsonb_build_object(
            'success_rate', jsonb_build_object('value', case when seed.conclusion = 'failed' then 0.82 else 0.98 end, 'sample_count', seed.question_count, 'available', true),
            'error_rate', jsonb_build_object('value', case when seed.conclusion = 'failed' then 0.04 else 0.005 end, 'sample_count', seed.question_count, 'available', true),
            'fallback_rate', jsonb_build_object('value', case when seed.conclusion = 'failed' then 0.12 else 0.02 end, 'sample_count', seed.question_count, 'available', true),
            'citation_rate', jsonb_build_object('value', case when seed.conclusion = 'failed' then 0.78 else 0.96 end, 'sample_count', seed.question_count, 'available', true),
            'p95_duration_ms', jsonb_build_object('value', case when seed.conclusion = 'failed' then 9300 else 3517 end, 'sample_count', seed.question_count, 'available', true)
        ),
        'failed_gates', case when seed.conclusion = 'failed' then jsonb_build_array('success_rate', 'error_rate', 'fallback_rate', 'citation_rate') else '[]'::jsonb end,
        'conclusion', coalesce(seed.conclusion, 'indeterminate')
    ),
    report = jsonb_build_object(
        'task', jsonb_build_object('kb_id', task.kb_id, 'question_source', task.config ->> 'questions_source'),
        'dataset', jsonb_build_object('total', seed.question_count, 'sources', jsonb_build_array(task.config ->> 'questions_source')),
        'summary', case when seed.conclusion = 'failed' then '本次评测未通过全部门禁，发现引用覆盖和降级率异常。' else '本次评测整体通过，成功率和引用率达到门禁要求。' end,
        'findings', jsonb_build_array(case when seed.conclusion = 'failed' then '发现失败样品和引用缺失问题，建议优先检查知识库覆盖。' else '发现少量降级样品，建议关注长问题和边界问题的检索覆盖。' end),
        'failures', jsonb_build_array(jsonb_build_object('case_no', 2, 'question', '扫码签名具体怎么操作？', 'status', 'fallback', 'termination_reason', 'fallback')),
        'citation_anomalies', jsonb_build_array(jsonb_build_object('case_no', 3, 'question', '产品支持哪些部署方式？', 'status', 'completed', 'citation_count', 0)),
        'conclusion', coalesce(seed.conclusion, 'indeterminate')
    )
from seed
join t_evaluation_task task on task.id = seed.task_id
where run.id = seed.run_id;

with seed as (
    select
        run.id as run_id,
        row_number() over (order by run.id) as sequence_no
    from t_evaluation_run run
    join t_evaluation_task task on task.id = run.task_id
    where task.name like '自主评测演示任务%'
      and run.run_no = 1
), cases as (
    select seed.run_id, seed.sequence_no, series.case_no
    from seed
    cross join generate_series(1, 5) as series(case_no)
)
insert into t_evaluation_case_result (
    run_id, case_no, question, question_source, question_basis, answer, status,
    termination_reason, citation_count, hit_count, duration_ms, error_code, error_message, metadata
)
select
    run_id,
    case_no,
    case when case_no = 1 then '请简单介绍一下产品核心能力。'
         when case_no = 2 then '扫码签名具体怎么操作？'
         when case_no = 3 then '产品支持哪些部署方式？'
         when case_no = 4 then '出现服务异常时应该如何处理？'
         else '如何配置知识库问答参数？' end,
    case when sequence_no % 2 = 0 then 'generated' else 'imported' end,
    case when sequence_no % 2 = 0 then '业务范围与知识库内容' else '外部导入题目' end,
    case when case_no in (3, 4) then '当前样例题目返回了完整的异常说明，便于对照结果详情交互。'
         else '这是用于对照原型的样例答案，包含产品能力、操作流程和配置说明。' end,
    case when case_no = 2 then 'fallback'
         when case_no = 3 then 'error'
         when case_no = 4 then 'timeout'
         else 'completed' end,
    case when case_no = 2 then 'fallback'
         when case_no = 3 then 'agent_error'
         when case_no = 4 then 'request_timeout'
         else null end,
    case when case_no = 3 then 0 else 3 end,
    case when case_no = 3 then 0 else 5 end,
    1200 + case_no * 417 + sequence_no * 3,
    case when case_no = 3 then 'EVALUATION_AGENT_ERROR' when case_no = 4 then 'REQUEST_TIMEOUT' else null end,
    case when case_no = 3 then '样例错误：知识库问答服务暂时不可用。' when case_no = 4 then '样例超时：单题执行超过配置的超时时间。' else null end,
    jsonb_build_object(
        'citations', case when case_no = 3 then '[]'::jsonb else jsonb_build_array(
            jsonb_build_object('document_id', 100 + sequence_no, 'chunk_id', 1000 + sequence_no, 'source_name', '产品使用指南-样例文档.md', 'page', case_no, 'snippet', '这是用于查看结果抽屉的样例引用片段。', 'score', 0.91, 'rank', 1),
            jsonb_build_object('document_id', 200 + sequence_no, 'chunk_id', 2000 + sequence_no, 'source_name', '部署与运维手册-样例文档.md', 'page', case_no + 1, 'snippet', '这是第二条样例引用资料，用于测试多条引用展示。', 'score', 0.86, 'rank', 2)
        ) end,
        'sample', true
    )
from cases
on conflict (run_id, case_no) do update set
    question = excluded.question,
    question_source = excluded.question_source,
    question_basis = excluded.question_basis,
    answer = excluded.answer,
    status = excluded.status,
    termination_reason = excluded.termination_reason,
    citation_count = excluded.citation_count,
    hit_count = excluded.hit_count,
    duration_ms = excluded.duration_ms,
    error_code = excluded.error_code,
    error_message = excluded.error_message,
    metadata = excluded.metadata;
