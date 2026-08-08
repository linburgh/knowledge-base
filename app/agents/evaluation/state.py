from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.evaluation import EvaluationAgentContext

from .metrics import calculate_metrics
from .models import CaseResult, EvaluationConfig, EvaluationMetrics, EvaluationQuestion


@dataclass(slots=True)
class EvaluationSession:
    """一次 Deep Agent 调用独占的评测工作状态。"""

    config: EvaluationConfig
    questions: list[EvaluationQuestion]
    trusted_context: EvaluationAgentContext
    executor: Any
    runtime: Any
    results: dict[int, CaseResult] = field(default_factory=dict)
    review_round: int = 0
    reviewed_case_numbers: list[int] = field(default_factory=list)

    def ordered_results(self) -> list[CaseResult]:
        return [self.results[case_no] for case_no in sorted(self.results)]

    def metrics(self) -> EvaluationMetrics:
        return calculate_metrics(self.ordered_results(), self.config.gates)

    def all_cases_completed(self) -> bool:
        return set(self.results) == set(range(1, len(self.questions) + 1))


@dataclass(frozen=True, slots=True)
class EvaluationHarnessContext:
    """仅通过 ToolRuntime 注入的可信依赖，不暴露为模型工具参数。"""

    session: Any


__all__ = ("EvaluationHarnessContext", "EvaluationSession")
