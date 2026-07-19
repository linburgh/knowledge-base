-- PostgreSQL initial and migration DML for knowledge-base data.
-- DDL is maintained separately in data_table_ddl.sql.

-- 为已有知识库补齐初始提示词历史版本，重复执行不会产生重复记录。
insert into t_knowledge_base_prompt (kb_id, version, system_prompt, created_by)
select kb.id, coalesce(kb.system_prompt_version, 1), coalesce(kb.system_prompt, ''), kb.owner_id
from t_knowledge_base kb
where not exists (
    select 1
    from t_knowledge_base_prompt prompt
    where prompt.kb_id = kb.id
);
