from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuleDecision:
    action: str
    severity: str | None
    threshold: float | None
    reason: str


def evaluate_rule(rule: dict[str, Any], value: float | None, sample_count: int) -> RuleDecision:
    if not rule.get("enabled", True):
        return RuleDecision("ignore", None, None, "rule_disabled")
    minimum = int(rule.get("minimum_sample_count") or 0)
    if value is None or sample_count < minimum:
        return RuleDecision("ignore", None, None, "insufficient_sample")
    critical = rule.get("critical_threshold")
    warning = rule.get("warning_threshold")
    recovery = rule.get("recovery_threshold")
    trigger_type = str(rule.get("trigger_type") or "higher_than")
    if trigger_type == "informational":
        return RuleDecision("recover", None, None, "informational_metric_ready")
    if trigger_type == "lower_than":
        if critical is not None and value <= float(critical):
            return RuleDecision("fire", "critical", float(critical), "critical_threshold_below")
        if warning is not None and value <= float(warning):
            return RuleDecision("fire", "warning", float(warning), "warning_threshold_below")
        if recovery is None or value >= float(recovery):
            return RuleDecision(
                "recover",
                None,
                float(recovery) if recovery is not None else None,
                "recovery_threshold_reached",
            )
        return RuleDecision("ignore", None, None, "within_threshold")
    if critical is not None and value >= float(critical):
        return RuleDecision("fire", "critical", float(critical), "critical_threshold_exceeded")
    if warning is not None and value >= float(warning):
        return RuleDecision("fire", "warning", float(warning), "warning_threshold_exceeded")
    if recovery is None or value <= float(recovery):
        return RuleDecision(
            "recover",
            None,
            float(recovery) if recovery is not None else None,
            "recovery_threshold_reached",
        )
    return RuleDecision("ignore", None, None, "within_threshold")


__all__ = ("RuleDecision", "evaluate_rule")
