from __future__ import annotations

from typing import Any, TypedDict


class EvaluationState(TypedDict, total=False):
    evaluation_id: int
    task_id: int
    config_snapshot: dict[str, Any]
    questions: list[dict[str, Any]]
    question_index: int
    case_results: list[dict[str, Any]]
    metrics: dict[str, Any]
    conclusion: str
    status: str
    error: dict[str, str]
