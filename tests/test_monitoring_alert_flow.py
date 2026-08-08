from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage

from app.agents.monitoring.models import MonitoringAgentOutput
from app.core.common.auth import CurrentUser
from app.core.services.monitoring import access as monitoring_access
from app.core.services.monitoring import mgr as monitoring
from app.db import api as db_api
from app.db.base import DB
from app.schemas.monitoring import MonitorEventRequest
from app.workers import monitoring_aggregate, monitoring_notify


class _StaticMonitoringDeepAgent:
    def __init__(self, intent: str) -> None:
        self.intent = intent

    async def ainvoke(self, inputs, *, context, config):
        del inputs, context, config
        return {
            "structured_response": MonitoringAgentOutput(
                intent=self.intent,
                goal="分析当前授权监控事实",
                answer_markdown=("当前告警证据不足，需要结合中国标准时间内的监控事实继续核查。"),
                conclusion_ack="unknown",
                layout_reason="事实不足，使用简短说明",
                confidence=0.3,
                termination_reason="evidence_insufficient",
            ),
            "messages": [AIMessage(content="完成分析")],
        }


class FakeDatabase:
    class _Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    def transaction(self):
        return self._Transaction()


@pytest.fixture
def monitoring_flow(monkeypatch):
    state = {
        "events": [],
        "values": [],
        "alerts": [],
        "records": [],
        "audits": [],
        "next_alert": 1,
        "next_event": 1,
        "next_record": 1,
    }
    database = FakeDatabase()

    async def inject_db():
        DB.set(database)

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring_access, "require_monitoring_access", lambda *_: _allow())
    monkeypatch.setattr(monitoring_access, "tenant_scope", lambda *_: _scope())
    monkeypatch.setattr(monitoring, "require_monitoring_access", lambda *_: _allow())
    monkeypatch.setattr(monitoring, "tenant_scope", lambda *_: _scope())

    async def _allow():
        return {}

    async def _scope():
        return 10

    async def event_get(_, **filters):
        return next(
            (row for row in state["events"] if all(row.get(k) == v for k, v in filters.items())),
            None,
        )

    async def event_insert(_, **values):
        row = {"id": state["next_event"], **values}
        state["next_event"] += 1
        state["events"].append(row)
        return row["id"]

    async def event_list(_, **filters):
        return [row for row in state["events"] if _match(row, filters)]

    async def alert_get(_, **filters):
        return next((row for row in state["alerts"] if _match(row, filters)), None)

    async def alert_insert(_, **values):
        row = {"id": state["next_alert"], **values}
        state["next_alert"] += 1
        state["alerts"].append(row)
        return row["id"]

    async def alert_update(_, values, **filters):
        row = next(row for row in state["alerts"] if _match(row, filters))
        row.update(values)

    async def rule_list(_, **filters):
        return [
            {
                "id": 7,
                "metric_code": "error_rate",
                "enabled": True,
                "warning_threshold": 0.2,
                "critical_threshold": 0.8,
                "recovery_threshold": 0.1,
                "minimum_sample_count": 1,
                "scope_type": "tenant",
            }
        ]

    async def definition_list(_, **filters):
        return [
            {
                "metric_code": "error_rate",
                "metric_name": "问答错误率",
                "metric_domain": "qa",
                "unit": "ratio",
                "minimum_sample_count": 1,
                "dimensions": {"scope": ["platform", "tenant"]},
                "status": "active",
                "version": 1,
            }
        ]

    async def value_insert(_, **values):
        state["values"].append({"id": len(state["values"]) + 1, **values})

    async def value_update(_, values, **filters):
        row = next(row for row in state["values"] if _match(row, filters))
        row.update(values)

    async def value_list(_, **filters):
        return [row for row in state["values"] if _match(row, filters)]

    async def policy_list(_, **filters):
        return [{"id": 3, "severity": "warning", "status": "enabled", "event_types": []}]

    async def policy_channel_list(_, **filters):
        return [{"policy_id": 3, "channel_id": 4}]

    async def channel_get(_, **filters):
        return {
            "id": 4,
            "status": "enabled",
            "endpoint_ref": "mock://success",
            "receiver_scope": {"type": "oncall"},
        }

    async def record_get(_, **filters):
        return next((row for row in state["records"] if _match(row, filters)), None)

    async def record_insert(_, **values):
        row = {"id": state["next_record"], **values}
        state["next_record"] += 1
        state["records"].append(row)
        return row["id"]

    async def record_list(_, **filters):
        return [row for row in state["records"] if _match(row, filters)]

    async def record_update(_, values, **filters):
        row = next(row for row in state["records"] if _match(row, filters))
        row.update(values)

    async def audit(*_, **kwargs):
        state["audits"].append(kwargs)

    monkeypatch.setattr(monitoring.event_db, "get", event_get)
    monkeypatch.setattr(monitoring.event_db, "insert_", event_insert)
    monkeypatch.setattr(monitoring.event_db, "list", event_list)
    monkeypatch.setattr(monitoring.alert_db, "get", alert_get)
    monkeypatch.setattr(monitoring.alert_db, "insert_", alert_insert)
    monkeypatch.setattr(monitoring.alert_db, "update_", alert_update)
    monkeypatch.setattr(monitoring.rule_db, "list", rule_list)
    monkeypatch.setattr(monitoring_aggregate.definition_db, "list", definition_list)
    monkeypatch.setattr(monitoring.value_db, "insert_", value_insert)
    monkeypatch.setattr(monitoring.value_db, "update_", value_update)
    monkeypatch.setattr(monitoring.value_db, "list", value_list)
    monkeypatch.setattr(monitoring.policy_db, "list", policy_list)
    monkeypatch.setattr(monitoring.policy_channel_db, "list", policy_channel_list)
    monkeypatch.setattr(monitoring.channel_db, "get", channel_get)
    monkeypatch.setattr(monitoring.notification_record_db, "get", record_get)
    monkeypatch.setattr(monitoring.notification_record_db, "insert_", record_insert)
    monkeypatch.setattr(monitoring_notify.record_db, "list", record_list)
    monkeypatch.setattr(monitoring_notify.record_db, "update_", record_update)
    monkeypatch.setattr(monitoring_notify.channel_db, "get", channel_get)
    monkeypatch.setattr(monitoring.audit_service, "record", audit)
    monkeypatch.setattr(monitoring_notify.audit_service, "record", audit)
    return state


def _match(row, filters):
    for key, value in filters.items():
        if key.endswith("__ne"):
            if row.get(key[:-4]) == value:
                return False
        elif key.endswith("__gte"):
            if row.get(key[:-5]) < value:
                return False
        elif key.endswith("__lte"):
            if row.get(key[:-5]) > value:
                return False
        elif row.get(key) != value:
            return False
    return True


@pytest.mark.asyncio
async def test_alert_full_lifecycle_from_event_to_agent(monitoring_flow):
    state = monitoring_flow
    user = CurrentUser(user_id="11", tenant_id=10)
    current = datetime.now(UTC)
    window_end = current.replace(
        minute=current.minute - current.minute % 5,
        second=0,
        microsecond=0,
    )
    now = window_end - timedelta(minutes=1)
    for index, status in enumerate(("error", "ok", "error", "ok", "error")):
        await monitoring.ingest_event(
            MonitorEventRequest(
                event_id=f"event-{index}",
                event_type="qa.request",
                source_type="service",
                source_code="qa-api",
                status=status,
                occurred_at=now,
                duration_ms=100,
                tenant_id=10,
            ),
            user,
        )

    assert len(state["events"]) == 5
    await monitoring_aggregate.run_once()
    assert state["values"][0]["metric_value"] == 0.6
    assert state["alerts"][0]["status"] == "firing"
    assert state["alerts"][0]["alert_title"] == "指标异常：问答错误率"
    assert "error_rate" not in state["alerts"][0]["alert_title"]
    assert any(
        event.get("source_type") == "alert" and event.get("event_type") == "alert_fired"
        for event in state["events"]
    )
    assert len(state["records"]) == 1
    assert {item["action"] for item in state["audits"]} >= {
        "monitor_event_ingested",
        "monitor_alert_fired",
        "monitor_notification_enqueued",
    }
    await monitoring_aggregate.run_once()
    assert len(state["alerts"]) == 1
    assert len(state["records"]) == 1

    acknowledged = await monitoring.alert_action(state["alerts"][0]["id"], "acknowledge", user)
    assert acknowledged["status"] == "acknowledged"
    suppressed = await monitoring.alert_action(
        state["alerts"][0]["id"], "suppress", user, "计划维护期间暂停通知"
    )
    assert suppressed["status"] == "acknowledged"
    await monitoring.alert_action(state["alerts"][0]["id"], "note", user, "已通知值班人员")

    state["events"] = [
        {
            "event_type": "qa.request",
            "status": "ok",
            "tenant_id": 10,
            "occurred_at": now,
        }
    ]
    state["values"] = []
    await monitoring_aggregate.run_once()
    assert state["alerts"][0]["status"] == "resolved"
    assert any(event.get("event_type") == "alert_recovered" for event in state["events"])
    assert any(item["event_type"] == "recovery" for item in state["records"])
    assert "monitor_alert_recovered" in {item["action"] for item in state["audits"]}
    closed = await monitoring.alert_action(
        state["alerts"][0]["id"], "close", user, "恢复证据已确认"
    )
    assert closed["status"] == "closed"
    assert {item["action"] for item in state["audits"]} >= {
        "monitor_alert_suppress",
        "monitor_alert_note",
        "monitor_alert_close",
    }

    sent = await monitoring_notify.run_once()
    assert sent == 2
    assert all(item["status"] == "sent" for item in state["records"])

    from app.agents.monitoring import MonitoringAgent

    result = await MonitoringAgent(
        agent_factory=lambda runtime: _StaticMonitoringDeepAgent("incident_cause")
    ).analyze(
        question="为什么刚才触发告警？",
        context={"role": "tenant_admin", "alerts": state["alerts"], "evidence": state["events"]},
    )
    assert result["agent"] == "自主监控智能体"
    assert result["status"] == "completed"
    assert "告警" in result["answer"]


@pytest.mark.asyncio
async def test_monitoring_agent_introduces_itself_without_unrelated_evidence():
    from app.agents.monitoring import MonitoringAgent

    result = await MonitoringAgent(
        agent_factory=lambda runtime: _StaticMonitoringDeepAgent("identity")
    ).analyze(
        question="你是谁？介绍一下自己",
        context={
            "role": "tenant_admin",
            "alerts": [{"id": 1, "alert_title": "测试告警"}],
            "evidence": [{"id": 1, "evidence_type": "event"}],
        },
    )

    assert result["agent"] == "自主监控智能体"
    assert result["status"] == "completed"
    assert result["answer"].startswith("### 你好，我是自主监控智能分析助手")
    assert "运行状态排查搭档" in result["answer"]
    assert "你可以直接问我" in result["answer"]
    assert "### 能力范围" not in result["answer"]
    assert "### 安全边界" not in result["answer"]
    assert "不会替你修改配置、重试任务或执行处置" in result["answer"]
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_notification_failure_is_retried_and_bounded(monitoring_flow, monkeypatch):
    state = monitoring_flow
    state["records"].append({"id": 1, "channel_id": 4, "status": "pending", "retry_count": 0})
    monkeypatch.setattr(monitoring_notify, "_deliver", lambda *_: _failed_delivery())

    for expected in (1, 2, 3):
        await monitoring_notify.run_once()
        assert state["records"][0]["retry_count"] == expected
        assert state["records"][0]["status"] == "failed"
    await monitoring_notify.run_once()
    assert state["records"][0]["retry_count"] == 3
    assert "monitor_notification_failed" in {item["action"] for item in state["audits"]}


async def _failed_delivery():
    return False, "TEST_CHANNEL_FAILURE"
