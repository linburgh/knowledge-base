from __future__ import annotations

from datetime import timedelta

import pytest

from app.agents.monitoring import MonitoringAgent
from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.services import monitoring, monitoring_analysis
from app.db import api as db_api
from app.db.base import DB
from app.schemas.monitoring import AnalysisConversationRequest, AnalysisMessageRequest


@pytest.fixture
def service_context(monkeypatch):
    database = object()

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return None

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring, "tenant_scope", scope)
    return CurrentUser(user_id="11")


@pytest.mark.asyncio
async def test_analysis_overview_returns_structured_agent_result(service_context, monkeypatch):
    now = utils.utc_now()

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_p95",
                "metric_name": "问答 P95",
                "metric_domain": "qa",
                "status": "active",
                "version": 1,
            }
        ]

    async def alerts(*_, **__):
        return [
            {
                "id": 7,
                "metric_code": "qa_p95",
                "alert_title": "问答 P95 持续预警",
                "severity": "critical",
                "status": "firing",
                "resource_code": "qa-api",
                "first_fired_at": now - timedelta(minutes=15),
                "last_fired_at": now,
            }
        ]

    async def alert_evidence(*_, **__):
        return [
            {
                "id": 9,
                "alert_id": 7,
                "evidence_type": "trace",
                "evidence_id": "trace-7ac9",
                "summary": "关联问答请求链路",
                "occurred_at": now - timedelta(minutes=2),
            }
        ]

    async def values(*_, **__):
        return [
            {
                "id": 3,
                "metric_code": "qa_p95",
                "metric_value": 1.8,
                "sample_count": 30,
                "window_end": now,
            }
        ]

    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.alert_evidence_db, "list", alert_evidence)
    monkeypatch.setattr(monitoring.value_db, "list", values)

    result = await monitoring.analysis_overview(service_context)

    assert result["analysis_status"] == "completed"
    assert result["incident_id"] == "INC-7"
    assert result["confidence"] >= 55
    assert result["impacts"][0]["impact_status"] == "confirmed"
    assert {item["evidence_level"] for item in result["evidence"]} == {"direct", "context"}
    assert result["suggestions"][0]["confirmation_status"] == "manual_confirmation"
    assert result["data_status"] == "ready"


@pytest.mark.asyncio
async def test_analysis_failure_preserves_facts(service_context, monkeypatch):
    now = utils.utc_now()

    async def definitions(*_, **__):
        return []

    async def alerts(*_, **__):
        return [
            {
                "id": 8,
                "metric_code": "worker_age",
                "alert_title": "Worker 心跳过期",
                "severity": "warning",
                "status": "firing",
                "resource_code": "evaluation-worker",
                "first_fired_at": now,
                "last_fired_at": now,
            }
        ]

    async def empty(*_, **__):
        return []

    async def fail(*_, **__):
        raise TimeoutError("injected")

    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.alert_evidence_db, "list", empty)
    monkeypatch.setattr(monitoring.value_db, "list", empty)
    monkeypatch.setattr(MonitoringAgent, "build_overview", fail)

    result = await monitoring.analysis_overview(service_context)

    assert result["analysis_status"] == "unavailable"
    assert result["conclusion"] == "分析暂不可用"
    assert len(result["alerts"]) == 1
    assert len(result["evidence"]) == 1


@pytest.mark.asyncio
async def test_audit_page_options_and_detail_use_enriched_contract(service_context, monkeypatch):
    now = utils.utc_now()
    audit_rows = [
        {
            "id": 1,
            "actor_id": "11",
            "action": "monitor_alert_acknowledge",
            "action_cn": "确认告警",
            "target_type": "monitor_alert",
            "target_id": "7",
            "request_id": "request-1",
            "request_summary": {
                "tenant_id": 3,
                "status": "acknowledged",
                "resource_name": "Worker 心跳过期",
            },
            "result": "success",
            "error_message": None,
            "created_at": now,
        },
        {
            "id": 2,
            "actor_id": "system",
            "action": "monitor_notification_failed",
            "action_cn": "通知失败",
            "target_type": "monitor_alert",
            "target_id": "8",
            "request_summary": {"tenant_id": 4},
            "result": "failed",
            "created_at": now - timedelta(days=2),
        },
    ]

    async def audits(*_, **__):
        return audit_rows

    async def audit_get(*_, **filters):
        return next(
            (
                row
                for row in audit_rows
                if all(row.get(key) == value for key, value in filters.items())
            ),
            None,
        )

    async def users(*_, **__):
        return [{"id": 11, "username": "admin", "display_name": "林管理员"}]

    monkeypatch.setattr(monitoring.audit_log_db, "list", audits)
    monkeypatch.setattr(monitoring.audit_log_db, "get", audit_get)
    monkeypatch.setattr(monitoring.user_db, "list", users)

    page = await monitoring.audit_page(
        service_context,
        1,
        10,
        actor_id="11",
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(minutes=1),
    )
    options = await monitoring.audit_options(service_context)
    detail = await monitoring.audit_detail(service_context, 1)

    assert page["total"] == 1
    assert page["items"][0]["actor_name"] == "林管理员"
    assert page["items"][0]["result_name"] == "已完成"
    assert page["items"][0]["resource_name"] == "Worker 心跳过期"
    assert monitoring._audit_view(audit_rows[1], {})["resource_name"] is None
    assert ["11", "林管理员"] in [list(item) for item in options["actors"]]
    assert detail["target_type_name"] == "告警实例"
    assert detail["resource_name"] == "Worker 心跳过期"
    assert detail["request_summary"]["tenant_id"] == 3


@pytest.mark.asyncio
async def test_analysis_conversation_binds_server_context_and_persists_evidence(monkeypatch):
    class TransactionDatabase:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def transaction(self):
            return self

    database = TransactionDatabase()
    conversations = []
    messages = []
    audits = []
    overview = {
        "incident_id": "INC-7",
        "scope_name": "全平台",
        "alerts": [{"id": 7, "alert_title": "Worker 心跳过期"}],
        "evidence": [
            {
                "id": "alert-7",
                "evidence_type": "alert",
                "summary": "Worker 心跳过期",
            }
        ],
    }

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return None

    async def analysis(*_):
        return overview

    async def insert_conversation(_, **values):
        conversations.append({"id": 1, **values, "updated_at": utils.utc_now()})
        return 1

    async def get_conversation(_, **filters):
        return next(
            (
                row
                for row in conversations
                if all(row.get(key) == value for key, value in filters.items())
            ),
            None,
        )

    async def update_conversation(_, values, **filters):
        row = await get_conversation(_, **filters)
        row.update(values)

    async def insert_message(_, **values):
        message_id = len(messages) + 1
        messages.append({"id": message_id, **values, "created_at": utils.utc_now()})
        return message_id

    async def audit(*_, **values):
        audits.append(values)

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring_analysis, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring_analysis, "tenant_scope", scope)
    monkeypatch.setattr(monitoring, "analysis_overview", analysis)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "insert_", insert_conversation)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "get", get_conversation)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "update_", update_conversation)
    monkeypatch.setattr(monitoring_analysis.message_db, "insert_", insert_message)
    monkeypatch.setattr(monitoring_analysis.audit_service, "record", audit)

    user = CurrentUser(user_id="11")
    conversation = await monitoring_analysis.create_conversation(
        AnalysisConversationRequest(
            title="Worker 异常分析",
            scope_key="platform",
            context={"time_range": "1h", "evidence": [{"id": "forged"}]},
        ),
        user,
    )
    result = await monitoring_analysis.send_message(
        conversation["id"],
        AnalysisMessageRequest(content="有哪些直接证据？", context={}),
        user,
    )

    assert conversation["metadata"]["incident_id"] == "INC-7"
    assert conversation["metadata"]["evidence"][0]["id"] == "alert-7"
    assert all(item.get("id") != "forged" for item in conversation["metadata"]["evidence"])
    assert result["agent"] == "自主监控Agent"
    assert messages[-1]["metadata"]["evidence"][0]["id"] == "alert-7"
    assert {item["action"] for item in audits} == {
        "monitor_analysis_conversation_created",
        "monitor_analysis_message_sent",
    }
