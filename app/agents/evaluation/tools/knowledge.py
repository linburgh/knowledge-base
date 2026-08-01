from __future__ import annotations

from typing import Any

from app.agents.knowledge import run_knowledge_agent
from app.schemas.agent import AgentContext, AgentTask
from app.schemas.evaluation import (
    EvaluationAgentContext,
    KnowledgeAgentCall,
    KnowledgeAgentCallResult,
)


async def call_knowledge_agent(
    payload: dict[str, Any],
    context: EvaluationAgentContext,
) -> KnowledgeAgentCallResult:
    call = KnowledgeAgentCall.model_validate(payload)
    result = await run_knowledge_agent(
        AgentTask(
            kb_id=context.kb_id,
            question=call.question,
            user_id=context.user_id,
            top_k=call.top_k,
        ),
        AgentContext(
            tenant_id=context.tenant_id,
            organization_ids=context.organization_ids,
            user_id=context.user_id,
            kb_id=context.kb_id,
            index_version_id=context.index_version_id,
            knowledge_base_prompt=context.knowledge_base_prompt,
            qa_config=context.qa_config,
            purpose="business",
            access_level="evaluation",
        ),
    )
    return KnowledgeAgentCallResult(result=result)


__all__ = ("call_knowledge_agent",)
