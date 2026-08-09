from __future__ import annotations

import operator
from collections.abc import Callable
from statistics import quantiles

from .models import CaseResult, EvaluationMetrics, Gate, MetricValue

OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}


def _percentile(values: list[int], percentile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    points = quantiles(values, n=100, method="inclusive")
    return float(values[0] if percentile == 0 else points[percentile - 1])


def calculate_metrics(results: list[CaseResult], gates: dict[str, Gate]) -> EvaluationMetrics:
    total = len(results)
    if not total:
        return EvaluationMetrics(
            conclusion="indeterminate", metrics={"total": MetricValue(value=0, sample_count=0)}
        )
    completed = sum(item.status == "completed" for item in results)
    errors = sum(item.status == "error" for item in results)
    timeouts = sum(item.status == "timeout" for item in results)
    fallback = sum(item.status == "fallback" for item in results)
    cited = sum(item.citation_count > 0 and item.status == "completed" for item in results)
    durations = [item.duration_ms for item in results if item.duration_ms >= 0]
    values = {
        "total": MetricValue(value=float(total), sample_count=total),
        "success_rate": MetricValue(value=completed / total, sample_count=total),
        "error_rate": MetricValue(value=errors / total, sample_count=total),
        "timeout_rate": MetricValue(value=timeouts / total, sample_count=total),
        "fallback_rate": MetricValue(value=fallback / total, sample_count=total),
        "citation_rate": MetricValue(value=cited / total, sample_count=total),
        "p50_duration_ms": MetricValue(
            value=_percentile(durations, 50), sample_count=len(durations)
        ),
        "p95_duration_ms": MetricValue(
            value=_percentile(durations, 95), sample_count=len(durations)
        ),
        "p99_duration_ms": MetricValue(
            value=_percentile(durations, 99), sample_count=len(durations)
        ),
        "recall_at_k": MetricValue(
            available=False,
            reason="评测数据未标注该问题应命中的标准文档或证据片段",
        ),
        "answer_correctness": MetricValue(available=False, reason="缺少标准答案或人工标注"),
    }
    failed: list[str] = []
    indeterminate = False
    for name, gate in gates.items():
        metric = values.get(name)
        if metric is None or not metric.available or metric.value is None:
            indeterminate = True
            continue
        if not OPS[gate.operator](metric.value, gate.value):
            failed.append(name)
    conclusion = "failed" if failed else ("indeterminate" if indeterminate else "passed")
    return EvaluationMetrics(metrics=values, failed_gates=failed, conclusion=conclusion)
