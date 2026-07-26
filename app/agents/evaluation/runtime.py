from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
    ) -> list[CaseResult]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def one(case_no: int, question: EvaluationQuestion) -> CaseResult:
            async with semaphore:
                for attempt in range(self.retry_count + 1):
                    try:
                        return await asyncio.wait_for(
                            execute(case_no, question), self.timeout_seconds
                        )
                    except TimeoutError:
                        if attempt == self.retry_count:
                            return CaseResult(
                                case_no=case_no,
                                question=question.question,
                                question_source=question.source,
                                question_basis=question.question_basis,
                                status="timeout",
                                termination_reason="timeout",
                                error_code="REQUEST_TIMEOUT",
                            )
                    except Exception as exc:
                        if attempt == self.retry_count:
                            return CaseResult(
                                case_no=case_no,
                                question=question.question,
                                question_source=question.source,
                                question_basis=question.question_basis,
                                status="error",
                                error_code="CASE_EXECUTION_ERROR",
                                error_message=str(exc)[:500],
                            )
                raise AssertionError("unreachable")

        return list(
            await asyncio.gather(
                *(one(index, question) for index, question in enumerate(questions, 1))
            )
        )
