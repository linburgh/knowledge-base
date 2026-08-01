from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path

import pytest

from app.agents.evaluation.models import EvaluationConfig
from app.core.monitoring.gather import (
    MONITOR_GATHER_REGISTRY,
    MonitorGatherRegistry,
    _persist,
    _record_emit_failure,
    _safe_payload,
    _should_sample,
    flush_gather_failures,
    monitor_gather,
)

DML_PATH = Path("scripts/db/data_table_dml.sql")
EXPECTED_TARGETS = {
    "api.http",
    "capacity.database",
    "capacity.file_storage",
    "capacity.queue",
    "capacity.vector_storage",
    "collector.self",
    "db.execute",
    "document.indexing",
    "document.ingestion",
    "evaluation.run",
    "knowledge.qa",
    "probe.api",
    "probe.database",
    "probe.embedding",
    "probe.llm",
    "probe.qa",
    "probe.rerank",
    "probe.storage",
    "probe.task_backlog",
    "probe.vector",
    "probe.worker",
    "worker.lifecycle",
}
METHOD_TARGETS = {
    "knowledge.qa": ("app.agents.knowledge.agent", "run_knowledge_agent"),
    "evaluation.run": ("app.workers.evaluation", "run_evaluation"),
    "document.ingestion": ("app.core.services.knowledge_base.document", "upload"),
    "document.indexing": ("app.core.services.knowledge_base.ingestion", "run_claimed_task"),
}


def test_dml_contains_complete_target_baseline() -> None:
    dml = DML_PATH.read_text(encoding="utf-8")
    for target_code in EXPECTED_TARGETS:
        assert f"'{target_code}'" in dml
    assert "on conflict (target_code, version) do update" in dml
    assert "on conflict (target_code, event_type, version) do update" in dml
    assert "('probe.capacity'," not in dml
    assert '"probe":"capacity"' not in dml
    assert "password" not in dml.lower()


def test_method_targets_are_importable_and_registered() -> None:
    for target_code, (module_name, callable_name) in METHOD_TARGETS.items():
        module = import_module(module_name)
        assert callable(getattr(module, callable_name))
        registration = MONITOR_GATHER_REGISTRY.get(target_code)
        assert registration is not None
        assert registration.module == module_name


def test_sensitive_values_are_removed_from_payload() -> None:
    payload = _safe_payload(
        {
            "question": "不能写入事件",
            "answer": "不能写入事件",
            "api_key": "secret",
            "hit_count": 3,
            "model_version": "model-a",
        },
        ["question", "answer", "api_key", "hit_count", "model_version"],
    )
    assert payload == {"hit_count": 3, "model_version": "model-a"}


def test_sampling_supports_error_and_tenant_strategies() -> None:
    assert _should_sample(
        {"status": "failed", "sampling": {"mode": "errors_only"}},
        1,
        {},
        RuntimeError("failed"),
    )
    assert not _should_sample(
        {"status": "completed", "sampling": {"mode": "errors_only"}},
        1,
        {},
        None,
    )
    assert _should_sample(
        {"sampling": {"mode": "tenant", "tenant_ids": [12]}},
        1,
        {"tenant_id": 12},
        None,
    )
    assert not _should_sample(
        {"sampling": {"mode": "tenant", "tenant_ids": [12]}},
        1,
        {"tenant_id": 13},
        None,
    )


def test_persist_executes_real_mapping_branch(monkeypatch) -> None:
    inserted: list[dict] = []

    class FakeDatabase:
        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    fake_db = FakeDatabase()

    async def fake_database():
        return fake_db

    async def fake_get(db, **kwargs):
        del db, kwargs
        return None

    async def fake_insert(db, **kwargs):
        del db
        inserted.append(kwargs)
        return 1

    monkeypatch.setattr("app.core.monitoring.gather._database", fake_database)
    monkeypatch.setattr("app.core.monitoring.gather.event_db.get", fake_get)
    monkeypatch.setattr("app.core.monitoring.gather.event_db.insert_", fake_insert)

    asyncio.run(
        _persist(
            {
                "target_code": "api.http",
                "target_type": "api",
                "target_locator": {},
            },
            {
                "event_type": "http_request_completed",
                "sampling_rate": 1,
                "field_mapping": {
                    "source_type": "api",
                    "status": "completed",
                    "sampling": {"mode": "all"},
                    "payload_allowlist": ["method"],
                },
            },
            args=(),
            kwargs={},
            result=None,
            fields={"method": "GET"},
            error=None,
        )
    )
    assert inserted[0]["payload"] == {"method": "GET"}


def test_failed_emit_summary_is_flushed_after_recovery(monkeypatch) -> None:
    async def fake_emit(*args, **kwargs):
        del args, kwargs
        return 1

    monkeypatch.setattr("app.core.monitoring.gather.emit_gather_event", fake_emit)
    _record_emit_failure("knowledge.qa", "qa_started", ConnectionError("database down"))
    assert asyncio.run(flush_gather_failures()) >= 1


def test_evaluation_run_budget_enforces_hard_timeout() -> None:
    class SlowAgent:
        async def run(self, config, questions, *, monitoring_fields=None):
            del config, questions, monitoring_fields
            await asyncio.sleep(0.1)
            return [], None

    config = EvaluationConfig(
        kb_id=1,
        user_id=1,
        run_timeout_seconds=0.01,
    )
    with pytest.raises(TimeoutError):
        asyncio.run(
            asyncio.wait_for(
                SlowAgent().run(config, [], monitoring_fields={}),
                timeout=config.run_timeout_seconds,
            )
        )


def test_registry_rejects_duplicate_target_code() -> None:
    registry = MonitorGatherRegistry()

    async def first() -> None:
        return None

    async def second() -> None:
        return None

    registry.register("duplicate.target", first)
    with pytest.raises(ValueError, match="重复登记"):
        registry.register("duplicate.target", second)


def test_monitor_gather_rejects_sync_callable() -> None:
    with pytest.raises(TypeError, match="仅支持 async"):

        @monitor_gather("test.sync")
        def sync_target() -> None:
            return None


def test_monitor_gather_preserves_business_exception(monkeypatch) -> None:
    emitted: list[str | None] = []

    async def fake_emit(target_code: str, event_type=None, **kwargs):
        del target_code, kwargs
        emitted.append(event_type)
        return 1

    monkeypatch.setattr("app.core.monitoring.gather.emit_gather_event", fake_emit)

    @monitor_gather("test.failure")
    async def failing_target() -> None:
        raise RuntimeError("business failure")

    with pytest.raises(RuntimeError, match="business failure"):
        asyncio.run(failing_target())
    assert emitted == [None, None]
