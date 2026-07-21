begin;

-- 知识库不再直接归属组织，组织访问统一通过 t_knowledge_base_organization 授权表控制。
insert into t_knowledge_base_organization (kb_id, organization_id, created_by)
select kb.id, kb.organization_id, kb.created_by
from t_knowledge_base kb
where kb.organization_id is not null
  and not exists (
      select 1
      from t_knowledge_base_organization grant_row
      where grant_row.kb_id = kb.id
        and grant_row.organization_id = kb.organization_id
  );

alter table if exists t_knowledge_base drop constraint if exists t_knowledge_base_tenant_id_organization_id_fkey;
drop index if exists idx_t_knowledge_base_organization_id;
alter table if exists t_knowledge_base drop column if exists organization_id;

commit;
