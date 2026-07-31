from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.common.log import LOG
from app.core.monitoring import emit_gather_event

from .models import CaseResult, EvaluationQuestion


@dataclass(slots=True)
class EvaluationRuntime:
    concurrency: int
    timeout_seconds: float
    retry_count: int = 0

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
                LOG.info(
                    "自主评测Agent case start case_no={} source={} question_length={}",
                    case_no,
                    question.source,
                    len(question.question),
                )
                for attempt in range(self.retry_count + 1):
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
        results = list(
            await asyncio.gather(
                *(one(index, question) for index, question in enumerate(questions, 1))
            )
        )
        LOG.info(
            "自主评测Agent runtime completed question_count={} result_count={}",
            len(questions),
            len(results),
        )
        return results
