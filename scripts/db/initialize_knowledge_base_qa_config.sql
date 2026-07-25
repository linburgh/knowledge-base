begin;

insert into t_knowledge_base_qa_config_version (
    kb_id,
    version_no,
    status,
    config_json,
    change_summary_json,
    requires_reindex,
    affected_document_count,
    created_by,
    published_by,
    published_at
)
select
    kb.id,
    1,
    'published',
    jsonb_build_object(
        'document', jsonb_build_object(
            'chunk_size', kb.chunk_size,
            'chunk_overlap', kb.chunk_overlap,
            'title_preserved', true,
            'whitespace_cleaning', true,
            'table_strategy', '保留文本',
            'duplicate_strategy', '标记重复'
        ),
        'retrieval', jsonb_build_object(
            'top_k', kb.retrieval_top_k,
            'similarity_threshold', null,
            'mode', 'vector',
            'hybrid_enabled', false,
            'keyword_weight', 30,
            'query_rewrite', false,
            'empty_result_strategy', '资料不足提示'
        ),
        'rerank', jsonb_build_object(
            'enabled', false,
            'model', 'hans-tech/bge-reranker-v2-m3:260522',
            'candidate_count', kb.retrieval_top_k * 3,
            'final_return_count', kb.retrieval_top_k,
            'timeout_seconds', 30,
            'fail_strategy', '使用向量结果'
        ),
        'answer', jsonb_build_object(
            'style', '专业自然',
            'max_length', 300,
            'must_cite', true,
            'max_citations', 3,
            'insufficient_data_strategy', '明确说明资料不足',
            'high_risk_strategy', '谨慎回答',
            'fallback_enabled', true,
            'prompt', case
                when kb.system_prompt is null or kb.system_prompt = ''
                    then '只能依据知识库资料回答，资料不足时明确说明。'
                else kb.system_prompt
            end
        ),
        'agent', jsonb_build_object(
            'max_steps', 4,
            'max_tool_calls', 6,
            'total_timeout_seconds', 60.0,
            'tool_timeout_seconds', 10.0,
            'max_retries', 1,
            'recursion_limit', 4,
            'fallback_timeout_seconds', 15
        )
    ),
    jsonb_build_object('reason', '初始化知识库问答配置'),
    false,
    0,
    kb.created_by,
    kb.created_by,
    now()
from t_knowledge_base kb
where kb.status <> 'deleted'
  and not exists (
      select 1
      from t_knowledge_base_qa_config_version existing
      where existing.kb_id = kb.id
        and existing.status = 'published'
  );

update t_knowledge_base_index_version index_version
set config_version_id = config.id
from t_knowledge_base_qa_config_version config
where config.kb_id = index_version.kb_id
  and config.status = 'published'
  and index_version.generation = 'generation-001'
  and index_version.config_version_id is null;

commit;
