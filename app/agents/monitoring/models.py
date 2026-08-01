from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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
        }


class StructuredTimeRange(BaseModel):
    expression: str | None = Field(default=None, max_length=100)
    label: str | None = Field(default=None, max_length=100)
    start: datetime | None = None
    end: datetime | None = None


class StructuredAnalysisPlan(BaseModel):
    intent: str = Field(min_length=1, max_length=64)
    goal: str = Field(min_length=1, max_length=500)
    time: StructuredTimeRange = Field(default_factory=StructuredTimeRange)
    entities: list[str] = Field(default_factory=list, max_length=20)
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    required_tools: list[str] = Field(default_factory=list, max_length=10)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.5, ge=0, le=1)


__all__ = (
    "AnalysisConclusion",
    "AnalysisIntent",
    "AnalysisPlan",
    "AnalysisTimeRange",
    "StructuredAnalysisPlan",
    "StructuredTimeRange",
)
