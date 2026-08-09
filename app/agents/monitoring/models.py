from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AnalysisIntent(StrEnum):
    PLATFORM_HEALTH = "platform_health"
    INCIDENT_CAUSE = "incident_cause"
    IMPACT_SCOPE = "impact_scope"
    EVIDENCE_REVIEW = "evidence_review"
    NEXT_ACTION = "next_action"
    TASK_DIAGNOSIS = "task_diagnosis"
    PERIOD_REVIEW = "period_review"
    GENERAL_ANALYSIS = "general_analysis"
    IDENTITY = "identity"


class AnalysisConclusion(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    ABNORMAL = "abnormal"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AnalysisTimeRange:
    start: datetime
    end: datetime
    timezone: str
    label: str
    source: str
    limitation: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "timezone": self.timezone,
            "label": self.label,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    intent: AnalysisIntent
    time_range: AnalysisTimeRange
    tools: tuple[str, ...]
    goal: str = "分析授权范围内的监控运行事实"
    time_expression: str | None = None
    entities: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    confidence: float | None = None
    planning_mode: str = "fallback"
    planning_error: str | None = None
    requested_view: str | None = None
    referenced_fact_ids: tuple[str, ...] = ()

    def planning_metadata(self) -> dict[str, object]:
        return {
            "mode": self.planning_mode,
            "goal": self.goal,
            "time_expression": self.time_expression,
            "entities": list(self.entities),
            "dimensions": list(self.dimensions),
            "uncertainties": list(self.uncertainties),
            "confidence": self.confidence,
            "error": self.planning_error,
            "requested_view": self.requested_view,
            "referenced_fact_ids": list(self.referenced_fact_ids),
        }


class MonitoringAgentOutput(BaseModel):
    """Deep Agent 的语义分析输出；确定性结论仍由程序计算。"""

    intent: AnalysisIntent
    goal: str = Field(min_length=1, max_length=500)
    # 保留用户希望看到的结果形态原文，不压缩成持续膨胀的固定枚举。
    requested_view: str | None = Field(default=None, max_length=500)
    answer_markdown: str = Field(min_length=1, max_length=6000)
    conclusion_ack: AnalysisConclusion
    time_expression: str | None = Field(default=None, max_length=100)
    entities: list[str] = Field(default_factory=list, max_length=20)
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    uncertainties: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    fact_refs: list[str] = Field(default_factory=list, max_length=20)
    hypotheses: list[str] = Field(default_factory=list, max_length=10)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=10)
    layout_reason: str = Field(min_length=1, max_length=300)
    confidence: float = Field(default=0.5, ge=0, le=1)
    termination_reason: Literal["completed", "evidence_insufficient", "tool_failed"] = "completed"


__all__ = (
    "AnalysisConclusion",
    "AnalysisIntent",
    "AnalysisPlan",
    "AnalysisTimeRange",
    "MonitoringAgentOutput",
)
