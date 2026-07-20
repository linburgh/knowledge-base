-- 修复知识库关联的无效租户。
--
-- 使用场景：t_knowledge_base.tenant_id 指向不存在或已删除的租户，导致
-- /api/v1/organizations/tree?tenant_id=xxx 返回“租户不存在”。
--
-- 规则：
-- 1. 优先选择 id 最小的 active 租户作为目标租户；没有 active 租户时，
--    选择 id 最小的非 deleted 租户。
-- 2. 只修复关联租户不存在或已删除的知识库，不修改已经关联有效租户的知识库。
-- 3. 如果知识库的 organization_id 不属于目标租户，则清空该字段，避免
--    t_knowledge_base(tenant_id, organization_id) 联合外键不一致。
-- 4. 整体在事务中执行，执行失败会自动回滚。

begin;

do $$
declare
    target_tenant_id bigint;
    changed_count bigint;
begin
    select tenant.id
      into target_tenant_id
      from t_tenant tenant
     where tenant.status = 'active'
     order by tenant.id
     limit 1;

    if target_tenant_id is null then
        select tenant.id
          into target_tenant_id
          from t_tenant tenant
         where tenant.status <> 'deleted'
         order by tenant.id
         limit 1;
    end if;

    if target_tenant_id is null then
        raise exception '没有可用租户，无法修复知识库关联关系';
    end if;

    update t_knowledge_base kb
       set tenant_id = target_tenant_id,
           organization_id = case
               when kb.organization_id is not null
                    and exists (
                        select 1
                          from t_organization org
                         where org.id = kb.organization_id
                           and org.tenant_id = target_tenant_id
                    )
               then kb.organization_id
               else null
           end,
           updated_at = now()
     where not exists (
               select 1
                 from t_tenant tenant
                where tenant.id = kb.tenant_id
                  and tenant.status <> 'deleted'
           );

    get diagnostics changed_count = row_count;
    raise notice '知识库租户修复完成：目标租户 ID = %, 更新知识库数量 = %',
        target_tenant_id,
        changed_count;
end;
$$;

commit;

