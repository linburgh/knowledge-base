from __future__ import annotations

from time import monotonic
from typing import Protocol

from app.core.common.log import LOG
from app.schemas.agent import AgentContext, AgentTask

from .models import CaseResult, EvaluationQuestion


class KnowledgeAgentProtocol(Protocol):
    async def __call__(self, task: AgentTask, context: AgentContext): ...


class KnowledgeAgentExecutor:
    def __init__(self, runner: KnowledgeAgentProtocol) -> None:
        self.runner = runner

    async def execute(self, case_no: int, question: EvaluationQuestion, *, config) -> CaseResult:
        started = monotonic()
        LOG.info(
            "自主评测Agent knowledge agent start case_no={} kb_id={} question_length={}",
            case_no,
            config.kb_id,
            len(question.question),
        )
        result = await self.runner(
            AgentTask(kb_id=config.kb_id, question=question.question, user_id=str(config.user_id)),
            AgentContext(kb_id=config.kb_id, user_id=str(config.user_id)),
        )
        status = "fallback" if result.termination_reason == "fallback" else "completed"
        LOG.info(
            "自主评测Agent knowledge agent finished "
            "case_no={} status={} citations={} hit_count={} duration_ms={}",
            case_no,
            status,
            len(result.citations),
            result.hit_count,
            max(result.duration_ms, int((monotonic() - started) * 1000)),
        )
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
                "citations": [citation.model_dump(mode="json") for citation in result.citations]
            },
        )
