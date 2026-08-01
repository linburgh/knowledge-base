from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from app.core.common.log import LOG
from app.core.monitoring import emit_gather_event
from app.schemas.agent import AgentSkillRef, AgentToolTrace
from app.schemas.evaluation import EvaluationAgentContext

from .models import CaseResult, EvaluationQuestion
from .policies import authorize_evaluation_tool
from .tools.registry import EvaluationToolRegistry


class EvaluationAgentError(Exception):
    code = "EVALUATION_AGENT_ERROR"


class EvaluationCancelled(EvaluationAgentError):
    code = "EVALUATION_CANCELLED"


class EvaluationBudgetExceeded(EvaluationAgentError):
    code = "EVALUATION_BUDGET_EXCEEDED"


@dataclass(slots=True)
class EvaluationRuntime:
    concurrency: int
    timeout_seconds: float
    retry_count: int = 0
    total_timeout_seconds: float = 3600
    max_tool_calls: int = 1000
    cancel_check: Callable[[], Awaitable[bool]] | None = None
    tool_call_count: int = 0
    model_call_count: int = 0
    stop_reason: str = ""
    tool_traces: list[AgentToolTrace] = field(default_factory=list)
    skill_refs: list[AgentSkillRef] = field(default_factory=list)
    partial_results: list[CaseResult] = field(default_factory=list)

    def register_skill(self, skill: AgentSkillRef) -> None:
        if all(item.name != skill.name for item in self.skill_refs):
            self.skill_refs.append(skill)
            LOG.info("自主评测Agent skill loaded name={} version={}", skill.name, skill.version)

    async def check_cancelled(self) -> None:
        if self.cancel_check is not None and await self.cancel_check():
            self.stop_reason = "cancelled"
            raise EvaluationCancelled("自主评测任务已取消")

    async def invoke_tool(
        self,
        *,
        registry: EvaluationToolRegistry,
        name: str,
        payload: dict[str, Any],
        context: EvaluationAgentContext,
    ):
        await self.check_cancelled()
        if self.tool_call_count >= self.max_tool_calls:
            self.stop_reason = "budget_exceeded"
            raise EvaluationBudgetExceeded("自主评测工具调用超过预算")
        authorize_evaluation_tool(
            name=name,
            payload=payload,
            context=context,
            registered_tools=registry.names(),
        )
        self.tool_call_count += 1
        started = monotonic()
        try:
            result = await asyncio.wait_for(
                registry.invoke(name, payload, context),
                timeout=self.timeout_seconds,
            )
            agent_result = getattr(result, "result", None)
            self.tool_traces.append(
                AgentToolTrace(
                    name=name,
                    status="completed",
                    duration_ms=int((monotonic() - started) * 1000),
                    result_count=getattr(agent_result, "hit_count", 0),
                )
            )
            return result
        except TimeoutError:
            self.tool_traces.append(
                AgentToolTrace(
                    name=name,
                    status="timeout",
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code="REQUEST_TIMEOUT",
                )
            )
            raise
        except Exception as exc:
            self.tool_traces.append(
                AgentToolTrace(
                    name=name,
                    status="failed",
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=type(exc).__name__,
                )
            )
            raise

    async def run(
        self,
        questions: list[EvaluationQuestion],
        execute: Callable[[int, EvaluationQuestion], Awaitable[CaseResult]],
        *,
        monitoring_fields: dict | None = None,
    ) -> list[CaseResult]:
        semaphore = asyncio.Semaphore(self.concurrency)
        event_fields = monitoring_fields or {}

        async def one(case_no: int, question: EvaluationQuestion) -> CaseResult:
            async with semaphore:
                await self.check_cancelled()
                LOG.info(
                    "自主评测Agent case start case_no={} source={} question_length={}",
                    case_no,
                    question.source,
                    len(question.question),
                )
                for attempt in range(self.retry_count + 1):
                    await self.check_cancelled()
                    await emit_gather_event(
                        "evaluation.run",
                        "evaluation_case_started",
                        case_no=case_no,
                        attempt=attempt + 1,
                        **event_fields,
                    )
                    try:
                        LOG.info(
                            "自主评测Agent case attempt case_no={} attempt={}",
                            case_no,
                            attempt + 1,
                        )
                        result = await asyncio.wait_for(
                            execute(case_no, question), self.timeout_seconds
                        )
                        LOG.info(
                            "自主评测Agent case finished case_no={} status={}",
                            case_no,
                            result.status,
                        )
                        await emit_gather_event(
                            "evaluation.run",
                            "evaluation_case_completed",
                            case_no=case_no,
                            duration_ms=result.duration_ms,
                            hit_count=result.hit_count,
                            citation_count=result.citation_count,
                            status=result.status,
                            **event_fields,
                        )
                        return result
                    except TimeoutError:
                        LOG.warning(
                            "自主评测Agent case timeout case_no={} attempt={}",
                            case_no,
                            attempt + 1,
                        )
                        if attempt == self.retry_count:
                            result = CaseResult(
                                case_no=case_no,
                                question=question.question,
                                question_source=question.source,
                                question_basis=question.question_basis,
                                status="timeout",
                                termination_reason="timeout",
                                error_code="REQUEST_TIMEOUT",
                            )
                            LOG.info(
                                "自主评测Agent case finished case_no={} status={}",
                                case_no,
                                result.status,
                            )
                            await emit_gather_event(
                                "evaluation.run",
                                "evaluation_case_completed",
                                case_no=case_no,
                                duration_ms=result.duration_ms,
                                hit_count=0,
                                citation_count=0,
                                status="timeout",
                                **event_fields,
                            )
                            return result
                        await emit_gather_event(
                            "evaluation.run",
                            "evaluation_case_retry",
                            case_no=case_no,
                            attempt=attempt + 1,
                            error_category="timeout",
                            **event_fields,
                        )
                    except EvaluationCancelled:
                        raise
                    except EvaluationBudgetExceeded:
                        raise
                    except Exception as exc:
                        LOG.opt(exception=exc).warning(
                            "自主评测Agent case error case_no={} attempt={}",
                            case_no,
                            attempt + 1,
                        )
                        if attempt == self.retry_count:
                            result = CaseResult(
                                case_no=case_no,
                                question=question.question,
                                question_source=question.source,
                                question_basis=question.question_basis,
                                status="error",
                                error_code="CASE_EXECUTION_ERROR",
                                error_message=str(exc)[:500],
                            )
                            LOG.info(
                                "自主评测Agent case finished case_no={} status={}",
                                case_no,
                                result.status,
                            )
                            await emit_gather_event(
                                "evaluation.run",
                                "evaluation_case_completed",
                                case_no=case_no,
                                duration_ms=result.duration_ms,
                                hit_count=0,
                                citation_count=0,
                                status="failed",
                                **event_fields,
                            )
                            return result
                        await emit_gather_event(
                            "evaluation.run",
                            "evaluation_case_retry",
                            case_no=case_no,
                            attempt=attempt + 1,
                            error_category=type(exc).__name__,
                            **event_fields,
                        )
                raise AssertionError("unreachable")

        LOG.info(
            "自主评测Agent runtime start question_count={} concurrency={} timeout_seconds={}",
            len(questions),
            self.concurrency,
            self.timeout_seconds,
        )
        gathered = await asyncio.gather(
            *(one(index, question) for index, question in enumerate(questions, 1)),
            return_exceptions=True,
        )
        results = [item for item in gathered if isinstance(item, CaseResult)]
        self.partial_results = results
        cancellation = next(
            (item for item in gathered if isinstance(item, EvaluationCancelled)),
            None,
        )
        if cancellation is not None:
            raise cancellation
        budget_error = next(
            (item for item in gathered if isinstance(item, EvaluationBudgetExceeded)),
            None,
        )
        if budget_error is not None:
            raise budget_error
        LOG.info(
            "自主评测Agent runtime completed question_count={} result_count={}",
            len(questions),
            len(results),
        )
        return results
