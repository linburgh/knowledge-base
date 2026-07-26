from __future__ import annotations

from time import monotonic
from typing import Protocol

from app.schemas.agent import AgentContext, AgentTask

from .models import CaseResult, EvaluationQuestion


class KnowledgeAgentProtocol(Protocol):
    async def __call__(self, task: AgentTask, context: AgentContext): ...


class KnowledgeAgentExecutor:
    def __init__(self, runner: KnowledgeAgentProtocol) -> None:
        self.runner = runner

    async def execute(self, case_no: int, question: EvaluationQuestion, *, config) -> CaseResult:
        started = monotonic()
        result = await self.runner(
            AgentTask(kb_id=config.kb_id, question=question.question, user_id=str(config.user_id)),
            AgentContext(kb_id=config.kb_id, user_id=str(config.user_id)),
        )
        status = "fallback" if result.termination_reason == "fallback" else "completed"
        return CaseResult(
            case_no=case_no,
            question=question.question,
            question_source=question.source,
            question_basis=question.question_basis,
            answer=result.answer,
            status=status,
            termination_reason=result.termination_reason,
            citation_count=len(result.citations),
            hit_count=result.hit_count,
            duration_ms=max(result.duration_ms, int((monotonic() - started) * 1000)),
            metadata={
                "citations": [
                    citation.model_dump(mode="json") for citation in result.citations
                ]
            },
        )
