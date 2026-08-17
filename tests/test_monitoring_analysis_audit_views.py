from __future__ import annotations

from datetime import timedelta

import pytest

from app.agents.monitoring import MonitoringAgent
from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services.monitoring import analysis as monitoring_analysis
from app.core.services.monitoring import mgr as monitoring
from app.db import api as db_api
from app.db.base import DB
from app.schemas.monitoring import (
    AnalysisConversationModifyRequest,
    AnalysisConversationRequest,
    AnalysisMessageRequest,
    AnalysisMessageResponse,
)


@pytest.fixture
def service_context(monkeypatch):
    database = object()

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return None

    async def empty(*_, **__):
        return []

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring, "tenant_scope", scope)
    monkeypatch.setattr(monitoring.event_db, "list", empty)
    monkeypatch.setattr(monitoring, "_task_records", empty)
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
    assert result["presentation_state"] == "alert"
    assert result["impact_overview"]["status_name"] == "已确认影响"
    assert result["action_overview"]["status_name"] == "优先处理"
    assert result["report_no"].startswith("AMR-")
    assert result["generated_at"]
    assert len(result["checks"]) == 4
    assert result["judgment_boundary"]
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
    assert result["presentation_state"] == "unknown"
    assert result["impact_overview"]["status_name"] == "无法判断"
    assert result["action_overview"]["status_name"] == "补充证据"
    assert len(result["alerts"]) == 1
    assert len(result["evidence"]) == 1


@pytest.mark.asyncio
async def test_analysis_overview_uses_metric_evidence_without_active_alerts(
    service_context,
    monkeypatch,
):
    now = utils.utc_now()

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_success_rate",
                "metric_name": "问答成功率",
                "metric_domain": "qa",
                "status": "active",
                "version": 1,
            }
        ]

    async def alerts(*_, **__):
        return []

    async def evidence(*_, **__):
        return []

    async def values(*_, **filters):
        assert filters["scope_key"] == "platform"
        return [
            {
                "id": 31,
                "metric_code": "qa_success_rate",
                "metric_value": 1,
                "sample_count": 5,
                "data_status": "ready",
                "assessment_status": "ready",
                "window_end": now,
            }
        ]

    async def events(*_, **__):
        return [
            {
                "id": 61,
                "event_id": "event-normal-61",
                "event_type": "probe_completed",
                "source_type": "probe",
                "source_code": "probe.qa",
                "status": "healthy",
                "occurred_at": now,
                "data_status": "ready",
            }
        ]

    async def tasks(*_, **__):
        return [
            {
                "task_key": "indexing-71",
                "task_name": "索引构建 71",
                "status": "completed",
                "status_name": "已完成",
                "created_at": now,
                "updated_at": now,
            }
        ]

    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.alert_evidence_db, "list", evidence)
    monkeypatch.setattr(monitoring.value_db, "list", values)
    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring, "_task_records", tasks)

    result = await monitoring.analysis_overview(service_context)

    assert result["analysis_status"] == "completed"
    assert result["attention_status"] == "none"
    assert result["presentation_state"] == "normal"
    assert result["impact_overview"]["title"] == "未发现已确认影响"
    assert result["action_overview"]["title"] == "当前无需处置"
    assert result["conclusion"] == "当前平台运行正常，未发现已确认的业务影响"
    assert result["data_status"] == "ready"
    assert any(item["title"] == "问答成功率" for item in result["evidence"])
    assert result["timeline"] == result["evidence"]
    checks = {item["dimension"]: item for item in result["checks"]}
    assert checks["core_metrics"]["status_name"] == "达标"
    assert checks["runtime_events"]["evidence_count"] == 1
    assert checks["task_runtime"]["evidence_count"] == 1


@pytest.mark.asyncio
async def test_analysis_overview_is_empty_only_when_all_facts_are_empty(
    service_context,
    monkeypatch,
):
    async def empty(*_, **__):
        return []

    monkeypatch.setattr(monitoring.definition_db, "list", empty)
    monkeypatch.setattr(monitoring.alert_db, "list", empty)
    monkeypatch.setattr(monitoring.alert_evidence_db, "list", empty)
    monkeypatch.setattr(monitoring.value_db, "list", empty)

    result = await monitoring.analysis_overview(service_context)

    assert result["analysis_status"] == "not_required"
    assert result["conclusion"] == "现有证据不足，暂时无法判断平台运行状态和影响范围"
    assert result["presentation_state"] == "unknown"
    assert result["impact_overview"]["status_name"] == "无法判断"
    assert result["action_overview"]["status_name"] == "补充证据"
    assert result["data_status"] == "empty"
    assert result["evidence"] == []
    assert result["confidence"] is None
    assert result["checks"][1]["status_name"] == "缺少数据"


@pytest.mark.asyncio
async def test_analysis_overview_marks_warning_metric_as_pending_impact(
    service_context,
    monkeypatch,
):
    now = utils.utc_now()

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_p95",
                "metric_name": "问答响应耗时",
                "metric_domain": "qa",
                "status": "active",
                "version": 1,
            }
        ]

    async def values(*_, **__):
        return [
            {
                "id": 41,
                "metric_code": "qa_p95",
                "metric_value": 1.8,
                "sample_count": 12,
                "data_status": "ready",
                "assessment_status": "warning",
                "window_end": now,
            }
        ]

    async def empty(*_, **__):
        return []

    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.alert_db, "list", empty)
    monkeypatch.setattr(monitoring.alert_evidence_db, "list", empty)
    monkeypatch.setattr(monitoring.value_db, "list", values)

    result = await monitoring.analysis_overview(service_context)

    assert result["presentation_state"] == "warning"
    assert result["impact_overview"]["status_name"] == "待验证影响"
    assert result["action_overview"]["status_name"] == "人工核查"
    assert result["impacts"][0]["impact_status"] == "pending"
    assert result["suggestions"][0]["target_module"] == "metrics"


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
        conversation_id = len(conversations) + 1
        conversations.append({"id": conversation_id, **values, "updated_at": utils.utc_now()})
        return conversation_id

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

    async def list_conversations(_, keyword=None, **filters):
        return [
            row
            for row in conversations
            if row.get("conversation_type") == filters.get("conversation_type")
            and row.get("status") != "deleted"
            and (not keyword or keyword.lower() in str(row.get("title") or "").lower())
        ]

    async def insert_message(_, **values):
        message_id = len(messages) + 1
        messages.append({"id": message_id, **values, "created_at": utils.utc_now()})
        return message_id

    async def list_messages(_, **filters):
        return [
            row for row in messages if all(row.get(key) == value for key, value in filters.items())
        ]

    async def audit(*_, **values):
        audits.append(values)

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring_analysis, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring_analysis, "tenant_scope", scope)
    monkeypatch.setattr(monitoring, "analysis_overview", analysis)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "insert_", insert_conversation)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "get", get_conversation)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "update_", update_conversation)
    monkeypatch.setattr(monitoring_analysis.conversation_db, "list", list_conversations)
    monkeypatch.setattr(monitoring_analysis.message_db, "insert_", insert_message)
    monkeypatch.setattr(monitoring_analysis.message_db, "list", list_messages)
    monkeypatch.setattr(monitoring_analysis.audit_service, "record", audit)
    monkeypatch.setattr(
        monitoring_analysis,
        "build_monitoring_tool_registry",
        lambda **_: MonitoringToolRegistry(),
    )

    seen_prior_fact_sets = []

    class StubMonitoringAgent:
        def __init__(self, **_kwargs):
            pass

        async def analyze(self, *, question, context):
            del question
            values = context.model_dump()
            seen_prior_fact_sets.append(values.get("prior_fact_set") or {})
            return {
                "intent": "evidence_review",
                "answer": "已根据中国标准时间内的授权证据完成分析。",
                "conclusion": "unknown",
                "data_status": "complete",
                "time_range": {
                    "label": "最近1小时",
                    "timezone": "Asia/Shanghai",
                    "source": "conversation",
                },
                "scope": {"type": "platform", "name": "全平台"},
                "status": "completed",
                "agent": "自主监控智能体",
                "evidence": values.get("evidence") or [],
                "limitations": [],
                "tool_calls": [],
                "planning": {"mode": "llm", "goal": "查看授权监控证据"},
                "answering": {"mode": "llm"},
                "fact_set": {
                    "id": "monitor-facts-alerts",
                    "sources": [
                        {
                            "tool_name": "query_alerts",
                            "fact_type": "alert",
                            "presentation": {"title": "告警明细"},
                            "items": [
                                {
                                    "id": "alert-7",
                                    "title": "Worker 心跳过期",
                                    "status": "firing",
                                }
                            ],
                        }
                    ],
                },
                "presentation": {
                    "type": "alert_list",
                    "fact_type": "alert",
                    "title": "告警明细",
                    "summary_markdown": "### 查询结果",
                },
            }

    monkeypatch.setattr(monitoring_analysis, "MonitoringAgent", StubMonitoringAgent)

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
    followup = await monitoring_analysis.send_message(
        conversation["id"],
        AnalysisMessageRequest(
            content="这1条具体是什么？",
            context={
                "prior_fact_set": {
                    "id": "forged-client-facts",
                    "sources": [{"items": [{"id": "forged-alert"}]}],
                }
            },
        ),
        user,
    )
    with pytest.raises(BusiException, match="会话名称不能为空"):
        await monitoring_analysis.modify_conversation(
            conversation["id"], AnalysisConversationModifyRequest(title="   "), user
        )
    renamed = await monitoring_analysis.modify_conversation(
        conversation["id"], AnalysisConversationModifyRequest(title="Worker 心跳分析"), user
    )
    filtered = await monitoring_analysis.list_conversations(user, "心跳")
    deleted = await monitoring_analysis.remove_conversation(conversation["id"], user)
    remaining = await monitoring_analysis.list_conversations(user, "心跳")
    default_conversation = await monitoring_analysis.create_conversation(
        AnalysisConversationRequest(scope_key="platform", context={"time_range": "1h"}),
        user,
    )

    assert conversation["metadata"]["incident_id"] == "INC-7"
    assert conversation["metadata"]["evidence"][0]["id"] == "alert-7"
    assert all(item.get("id") != "forged" for item in conversation["metadata"]["evidence"])
    assert result["agent"] == "自主监控智能体"
    assert followup["agent"] == "自主监控智能体"
    assert seen_prior_fact_sets[0] == {}
    assert seen_prior_fact_sets[1]["id"] == "monitor-facts-alerts"
    assert seen_prior_fact_sets[1]["id"] != "forged-client-facts"
    assert result["intent"] == "evidence_review"
    assert result["time_range"]["source"] == "conversation"
    assert renamed["title"] == "Worker 心跳分析"
    assert [item["id"] for item in filtered] == [conversation["id"]]
    assert deleted["status"] == "deleted"
    assert remaining == []
    assert default_conversation["title"] == "新建分析会话"
    assert messages[-1]["metadata"]["evidence"][0]["id"] == "alert-7"
    assert messages[-1]["metadata"]["intent"] == "evidence_review"
    assert messages[-1]["metadata"]["time_range"]["source"] == "conversation"
    assert messages[-1]["metadata"]["fact_set"]["id"] == "monitor-facts-alerts"
    assert messages[-1]["metadata"]["presentation"]["type"] == "alert_list"
    AnalysisMessageResponse.model_validate(result)
    assert {item["action"] for item in audits} == {
        "monitor_analysis_conversation_created",
        "monitor_analysis_conversation_deleted",
        "monitor_analysis_conversation_renamed",
        "monitor_analysis_message_sent",
    }
