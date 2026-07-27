"""Autonomous evaluation worker managed by the backend application."""

import asyncio
from datetime import UTC, datetime

from app.agents.evaluation.agent import EvaluationAgent
from app.agents.evaluation.dataset import load_questions, load_questions_content
from app.agents.evaluation.models import EvaluationConfig
from app.agents.evaluation.report import build_report
from app.agents.knowledge.agent import run_knowledge_agent
from app.config import CONF
from app.db import document_chunk as document_chunk_db
from app.db import evaluation_case_result as case_db
from app.db import evaluation_optimization as optimization_db
from app.db import evaluation_run as run_db
from app.db import evaluation_task as task_db
from app.db.api import check_db_connected
from app.db.base import DB


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
async def run_evaluation(run_id: int) -> int:
    db = DB.get()
    run = await run_db.get(db, id=run_id)
    if run is None or run["status"] not in {"pending", "running"}:
        return run_id
    task = await task_db.get(db, id=run["task_id"], status="active")
    if task is None:
        await run_db.update_(db, {"status": "failed", "finished_at": _now()}, id=run_id)
        return run_id
    await run_db.update_(
        db,
        {"status": "running", "stage": "prepare", "started_at": _now(), "updated_at": _now()},
        id=run_id,
    )
    try:
        config = EvaluationConfig.model_validate(task["config"])
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
        results, metrics = await EvaluationAgent(run_knowledge_agent).run(config, questions)
        failed_count = sum(result.status != "completed" for result in results)
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
        report = build_report(config, results, metrics)
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
    except Exception as exc:
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
    return run_id


@check_db_connected
async def run_pending_once() -> bool:
    """Claim and execute one pending evaluation run."""
    db = DB.get()
    pending = await run_db.list(db, status="pending")
    if not pending:
        return False
    await run_evaluation(int(pending[0]["id"]))
    return True


async def run_forever(stop_event: asyncio.Event) -> None:
    """Keep consuming autonomous evaluation runs until shutdown."""
    while not stop_event.is_set():
        try:
            handled = await run_pending_once()
            if not handled:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=max(1, int(CONF.default.evaluation_worker_poll_seconds)),
                )
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(max(1, int(CONF.default.evaluation_worker_poll_seconds)))
