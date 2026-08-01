from __future__ import annotations

from typing import Any, TypedDict


class EvaluationState(TypedDict, total=False):
    config: Any
    context: Any
    questions: list[Any]
    prepared_questions: list[Any]
    case_results: list[Any]
    metrics: Any
    report: dict[str, Any]
    conclusion: str
    current_node: str
    completed_count: int
    failed_count: int
    status: str
    termination_reason: str
    limitations: list[str]


__all__ = ("EvaluationState",)
