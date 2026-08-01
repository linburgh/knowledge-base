from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.services.monitoring import _aggregate_metric_window
from app.core.services.monitoring_rule import evaluate_rule
from app.workers.monitoring_aggregate import _aggregate, _definition_scopes

ROOT = Path(__file__).resolve().parents[1]


def _definition(metric_code: str = "qa_success_rate") -> dict:
    return {
        "metric_code": metric_code,
        "metric_name": "问答成功率",
        "metric_domain": "qa",
        "unit": "percent",
        "formula": "成功数 / 总数",
        "dimensions": {"scope": ["platform", "tenant"]},
        "minimum_sample_count": 1,
        "status": "active",
        "version": 1,
    }


def _rule(trigger_type: str = "lower_than") -> dict:
    return {
        "metric_code": "qa_success_rate",
        "scope_type": "all",
        "trigger_type": trigger_type,
        "warning_threshold": 0.98,
        "critical_threshold": 0.95,
        "recovery_threshold": 0.99,
        "minimum_sample_count": 1,
        "enabled": True,
        "version": 1,
    }


def test_lower_is_worse_rule_supports_warning_critical_and_recovery() -> None:
    rule = _rule()
    assert evaluate_rule(rule, 0.94, 10).severity == "critical"
    assert evaluate_rule(rule, 0.97, 10).severity == "warning"
    assert evaluate_rule(rule, 0.995, 10).action == "recover"


def test_platform_and_each_tenant_are_aggregated_independently() -> None:
    definition = _definition()
    events = [
        {"tenant_id": 3, "event_type": "qa_completed"},
        {"tenant_id": 4, "event_type": "qa_failed"},
        {"tenant_id": None, "event_type": "vector_probe_completed"},
    ]
    scopes = _definition_scopes(definition, events)
    assert [tenant_id for tenant_id, _ in scopes] == [None, 3, 4]
    assert len(scopes[0][1]) == 3
    assert {event["tenant_id"] for event in scopes[1][1]} == {3}
    assert {event["tenant_id"] for event in scopes[2][1]} == {4}


def test_failed_then_degraded_events_are_one_terminal_qa_request() -> None:
    now = datetime.now(UTC)
    events = [
        {
            "event_type": "qa_failed",
            "status": "failed",
            "tenant_id": 3,
            "kb_id": 8,
            "occurred_at": now,
            "payload": {"failure_stage": "agent_execution"},
        },
        {
            "event_type": "qa_degraded",
            "status": "degraded",
            "tenant_id": 3,
            "kb_id": 8,
            "occurred_at": now + timedelta(milliseconds=30),
            "payload": {"degraded_reason": "agent_error"},
        },
    ]
    request_count = _aggregate("qa_request_count", events)
    error_rate = _aggregate("qa_error_rate", events)
    assert request_count["sample_count"] == 1
    assert error_rate["sample_count"] == 1
    assert error_rate["metric_value"] == 1


def test_time_range_uses_all_ready_windows_and_does_not_let_latest_empty_hide_data() -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    rows = [
        {
            "metric_code": "qa_success_rate",
            "window_start": now - timedelta(minutes=15),
            "window_end": now - timedelta(minutes=10),
            "calculated_at": now - timedelta(minutes=10),
            "metric_value": 0.9,
            "sample_count": 10,
            "numerator": 9,
            "denominator": 10,
            "data_status": "ready",
            "assessment_status": "unknown",
            "source_summary": {"event_count": 10},
            "unit": "percent",
        },
        {
            "metric_code": "qa_success_rate",
            "window_start": now - timedelta(minutes=10),
            "window_end": now - timedelta(minutes=5),
            "calculated_at": now - timedelta(minutes=5),
            "metric_value": 1.0,
            "sample_count": 10,
            "numerator": 10,
            "denominator": 10,
            "data_status": "ready",
            "assessment_status": "unknown",
            "source_summary": {"event_count": 10},
            "unit": "percent",
        },
        {
            "metric_code": "qa_success_rate",
            "window_start": now - timedelta(minutes=5),
            "window_end": now,
            "calculated_at": now,
            "metric_value": None,
            "sample_count": 0,
            "numerator": None,
            "denominator": None,
            "data_status": "empty",
            "assessment_status": "unknown",
            "source_summary": {"event_count": 0},
            "unit": "percent",
        },
    ]
    result = _aggregate_metric_window(_definition(), rows, _rule())
    assert result["metric_value"] == 0.95
    assert result["sample_count"] == 20
    assert result["data_status"] == "partial"
    assert result["assessment_status"] == "failed"
    assert result["source_summary"] == {
        "window_count": 3,
        "ready_window_count": 2,
        "event_count": 20,
    }


def test_all_published_metric_definitions_have_seeded_rules() -> None:
    source = (ROOT / "scripts/db/data_table_dml.sql").read_text(encoding="utf-8")
    definition_section, rule_section = source.split(
        "-- 指标判定规则由系统发布", maxsplit=1
    )
    metric_codes = {
        line.split("'", 2)[1]
        for line in definition_section.splitlines()
        if line.lstrip().startswith("('") and "_" in line
    }
    for metric_code in (
        "qa_request_count",
        "qa_success_rate",
        "qa_error_rate",
        "qa_timeout_rate",
        "qa_reference_rate",
        "qa_p95",
        "database_connection_usage",
        "task_queue_usage",
        "file_storage_usage",
        "vector_storage_usage",
        "vector_service_availability",
        "task_backlog_count",
        "task_wait_p95",
        "task_success_rate",
        "evaluation_completion_rate",
        "evaluation_evidence_completeness",
    ):
        assert metric_code in metric_codes
        assert f"('{metric_code}', 'all'" in rule_section
