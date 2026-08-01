"""Autonomous evaluation worker managed by the backend application."""

import asyncio
from datetime import UTC, datetime
from time import monotonic

from app.agents.evaluation.agent import EvaluationAgent
from app.agents.evaluation.dataset import load_questions, load_questions_content
from app.agents.evaluation.models import CaseResult, EvaluationConfig, EvaluationMetrics
from app.config import CONF
from app.core.common.log import LOG
from app.core.monitoring import emit_gather_event, monitor_gather
from app.core.services import knowledge_base_qa_config as qa_config_service
from app.db import document_chunk as document_chunk_db
from app.db import evaluation_case_result as case_db
from app.db import evaluation_optimization as optimization_db
from app.db import evaluation_run as run_db
from app.db import evaluation_task as task_db
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.evaluation import EvaluationAgentContext, EvaluationAgentTask


def _now():
    return datetime.now(UTC)


async def _load_generation_context(db, config, fallback: str | None) -> str | None:
    if config.business_scope_source not in {
        "knowledge_base",
        "description_and_knowledge_base",
    }:
        return fallback
    chunks = await document_chunk_db.list(db, kb_id=config.kb_id)
    knowledge_text = "\n".join(
        str(chunk.get("content") or "").strip()
        for chunk in chunks
        if str(chunk.get("content") or "").strip()
    )
    return knowledge_text or fallback


@check_db_connected
@monitor_gather("evaluation.run")
async def run_evaluation(run_id: int) -> int:
    LOG.info("自主评测Worker run start run_id={}", run_id)
    run_started_at = monotonic()
    db = DB.get()
    run = await run_db.get(db, id=run_id)
    if run is None or run["status"] not in {"pending", "running"}:
        LOG.info(
            "自主评测Worker run skipped run_id={} status={}",
            run_id,
            run.get("status") if run else "missing",
        )
        return run_id
    task = await task_db.get(db, id=run["task_id"], status="active")
    if task is None:
        LOG.warning("自主评测Worker task missing run_id={} task_id={}", run_id, run["task_id"])
        await run_db.update_(db, {"status": "failed", "finished_at": _now()}, id=run_id)
        await emit_gather_event(
            "evaluation.run",
            "evaluation_run_failed",
            run_id=run_id,
            task_id=run["task_id"],
            failure_stage="task_lookup",
        )
        return run_id
    LOG.info(
        "自主评测Worker preparation started run_id={} task_id={} kb_id={}",
        run_id,
        run["task_id"],
        task.get("kb_id"),
    )
    await run_db.update_(
        db,
        {"status": "running", "stage": "prepare", "started_at": _now(), "updated_at": _now()},
        id=run_id,
    )
    event_fields = {
        "run_id": run_id,
        "task_id": run["task_id"],
        "kb_id": task.get("kb_id"),
        "tenant_id": task.get("tenant_id"),
    }
    try:
        config = EvaluationConfig.model_validate(task["config"])
        await emit_gather_event(
            "evaluation.run",
            "evaluation_config_validated",
            questions_source=config.questions_source,
            **event_fields,
        )
        if config.questions_source == "imported":
            if task["config"].get("questions_content"):
                questions = load_questions_content(
                    task["config"]["questions_content"],
                    task["config"].get("questions_file") or ".txt",
                )
            elif config.questions_file:
                questions = load_questions(config.questions_file)
            else:
                raise ValueError("问题文件内容不存在")
        else:
            from app.agents.evaluation.generator import generate_questions

            questions = await generate_questions(
                config,
                await _load_generation_context(
                    db,
                    config,
                    task["config"].get("business_description"),
                ),
            )
        LOG.info(
            "自主评测Worker questions ready run_id={} source={} question_count={}",
            run_id,
            config.questions_source,
            len(questions),
        )
        await emit_gather_event(
            "evaluation.run",
            "evaluation_questions_ready",
            question_count=len(questions),
            questions_source=config.questions_source,
            **event_fields,
        )
        await run_db.update_(
            db,
            {
                "stage": "execute",
                "question_count": len(questions),
                "completed_count": 0,
                "failed_count": 0,
                "updated_at": _now(),
            },
            id=run_id,
        )
        LOG.info("自主评测Worker Agent execution started run_id={}", run_id)
        async def is_cancelled() -> bool:
            latest_run = await run_db.get(db, id=run_id)
            return latest_run is None or latest_run.get("status") == "cancelled"

        evaluation_agent = EvaluationAgent(cancel_check=is_cancelled)
        remaining_seconds = max(
            0.001,
            config.run_timeout_seconds - (monotonic() - run_started_at),
        )
        try:
            knowledge_base = await knowledge_base_db.get(db, id=config.kb_id)
            if knowledge_base is None or knowledge_base.get("status") == "deleted":
                raise ValueError("评测知识库不存在")
            qa_config = await qa_config_service.get_effective_config(
                db,
                config.kb_id,
                knowledge_base.get("system_prompt") or "",
            )
            agent_result = await asyncio.wait_for(
                evaluation_agent.run(
                    EvaluationAgentTask(
                        config=config.model_dump(mode="json"),
                        questions=[item.model_dump(mode="json") for item in questions],
                    ),
                    EvaluationAgentContext(
                        run_id=run_id,
                        task_id=int(run["task_id"]),
                        user_id=str(config.user_id),
                        tenant_id=task.get("tenant_id") or knowledge_base.get("tenant_id"),
                        organization_ids=list(
                            task["config"].get("organization_ids") or []
                        ),
                        kb_id=config.kb_id,
                        index_version_id=knowledge_base.get("active_index_version_id"),
                        knowledge_base_prompt=knowledge_base.get("system_prompt"),
                        qa_config=qa_config,
                        is_super_admin=True,
                        monitoring_fields=event_fields,
                    ),
                ),
                timeout=remaining_seconds,
            )
        except TimeoutError:
            await run_db.update_(
                db,
                {
                    "status": "failed",
                    "stage": "execute",
                    "error_message": "评测运行超过最大执行时间",
                    "finished_at": _now(),
                    "updated_at": _now(),
                },
                id=run_id,
            )
            await emit_gather_event(
                "evaluation.run",
                "evaluation_run_timeout",
                timeout_stage="agent_execution",
                completed_count=0,
                duration_ms=int((monotonic() - run_started_at) * 1000),
                **event_fields,
            )
            return run_id
        if agent_result.summary.status == "cancelled":
            cancelled_results = [
                CaseResult.model_validate(item) for item in agent_result.case_results
            ]
            async with db.transaction():
                for result in cancelled_results:
                    await case_db.insert_(db, run_id=run_id, **result.model_dump())
                await run_db.update_(
                    db,
                    {
                        "status": "cancelled",
                        "stage": "execute",
                        "completed_count": len(cancelled_results),
                        "failed_count": sum(
                            item.status != "completed" for item in cancelled_results
                        ),
                        "finished_at": _now(),
                    },
                    id=run_id,
                )
            return run_id
        results = [CaseResult.model_validate(item) for item in agent_result.case_results]
        metrics = EvaluationMetrics.model_validate(agent_result.metrics)
        report = agent_result.report
        LOG.info(
            "自主评测Worker Agent execution completed run_id={} result_count={} conclusion={}",
            run_id,
            len(results),
            metrics.conclusion,
        )
        failed_count = sum(result.status != "completed" for result in results)
        await emit_gather_event(
            "evaluation.run",
            "evaluation_metrics_completed",
            sample_count=len(results),
            conclusion=metrics.conclusion,
            **event_fields,
        )
        await run_db.update_(
            db,
            {
                "stage": "metrics",
                "completed_count": len(results),
                "failed_count": failed_count,
                "updated_at": _now(),
            },
            id=run_id,
        )
        LOG.info(
            "自主评测Worker persistence started run_id={} case_count={}",
            run_id,
            len(results),
        )
        async with db.transaction():
            for result in results:
                await case_db.insert_(db, run_id=run_id, **result.model_dump())
            await run_db.update_(
                db,
                {
                    "stage": "report",
                    "status": "completed",
                    "conclusion": metrics.conclusion,
                    "question_count": len(results),
                    "completed_count": len(results),
                    "failed_count": failed_count,
                    "metrics": metrics.model_dump(mode="json"),
                    "report": report,
                    "finished_at": _now(),
                    "updated_at": _now(),
                },
                id=run_id,
            )
            optimization_id = report.get("optimization_id") if isinstance(report, dict) else None
            if optimization_id:
                serialized_metrics = metrics.model_dump(mode="json").get("metrics") or {}
                after_metrics = {
                    name: metric.get("value")
                    for name, metric in serialized_metrics.items()
                    if isinstance(metric, dict) and metric.get("value") is not None
                }
                await optimization_db.update_(
                    db,
                    {"after_metrics": after_metrics, "status": "suggested"},
                    id=int(optimization_id),
                )
        LOG.info(
            "自主评测Worker run completed run_id={} status=completed conclusion={}",
            run_id,
            metrics.conclusion,
        )
        await emit_gather_event(
            "evaluation.run",
            "evaluation_report_persisted",
            result_count=len(results),
            **event_fields,
        )
        await emit_gather_event(
            "evaluation.run",
            "evaluation_run_completed",
            result_count=len(results),
            failed_count=failed_count,
            conclusion=metrics.conclusion,
            **event_fields,
        )
    except asyncio.CancelledError:
        await run_db.update_(
            db,
            {
                "status": "cancelled",
                "stage": "report",
                "finished_at": _now(),
                "updated_at": _now(),
            },
            id=run_id,
        )
        await emit_gather_event(
            "evaluation.run",
            "evaluation_run_cancelled",
            cancel_source="worker_shutdown",
            **event_fields,
        )
        raise
    except Exception as exc:
        LOG.opt(exception=exc).error("自主评测Worker run failed run_id={}", run_id)
        await run_db.update_(
            db,
            {
                "status": "failed",
                "stage": "report",
                "report": {"error": str(exc)[:500]},
                "error_message": str(exc)[:500],
                "finished_at": _now(),
                "updated_at": _now(),
            },
            id=run_id,
        )
        await emit_gather_event(
            "evaluation.run",
            "evaluation_run_failed",
            run_id=run_id,
            task_id=run.get("task_id"),
            kb_id=task.get("kb_id"),
            tenant_id=task.get("tenant_id"),
            failure_stage="run_execution",
            error=exc,
        )
    return run_id


@check_db_connected
async def run_pending_once() -> bool:
    """Claim and execute one pending evaluation run."""
    LOG.info("自主评测Worker poll start")
    db = DB.get()
    pending = await run_db.list(db, status="pending")
    if not pending:
        LOG.info("自主评测Worker poll empty")
        return False
    LOG.info("自主评测Worker poll claimed run_id={}", pending[0]["id"])
    await emit_gather_event(
        "evaluation.run",
        "evaluation_task_claimed",
        run_id=int(pending[0]["id"]),
        task_id=pending[0].get("task_id"),
        worker_name="evaluation",
    )
    await run_evaluation(int(pending[0]["id"]))
    return True


async def run_forever(stop_event: asyncio.Event) -> None:
    """Keep consuming autonomous evaluation runs until shutdown."""
    LOG.info("自主评测Worker loop started")
    await emit_gather_event(
        "worker.lifecycle",
        "worker_started",
        worker_name="evaluation",
        source_code="evaluation",
    )
    try:
        while not stop_event.is_set():
            try:
                handled = await run_pending_once()
                await emit_gather_event(
                    "worker.lifecycle",
                    "worker_heartbeat",
                    worker_name="evaluation",
                    source_code="evaluation",
                )
                if not handled:
                    await emit_gather_event(
                        "worker.lifecycle",
                        "worker_idle",
                        worker_name="evaluation",
                        source_code="evaluation",
                    )
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=max(1, int(CONF.default.evaluation_worker_poll_seconds)),
                    )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                LOG.info("自主评测Worker loop cancelled")
                raise
            except Exception as exc:
                LOG.opt(exception=exc).error("自主评测Worker loop error")
                await emit_gather_event(
                    "worker.lifecycle",
                    "worker_failed",
                    worker_name="evaluation",
                    source_code="evaluation",
                    error=exc,
                )
                await asyncio.sleep(max(1, int(CONF.default.evaluation_worker_poll_seconds)))
    finally:
        await emit_gather_event(
            "worker.lifecycle",
            "worker_stopped",
            worker_name="evaluation",
            source_code="evaluation",
        )
    LOG.info("自主评测Worker loop stopped")
