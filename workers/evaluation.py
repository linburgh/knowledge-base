"""自主评测运行 Worker。"""

import asyncio
from datetime import UTC, datetime

from app.agents.evaluation.agent import EvaluationAgent
from app.agents.evaluation.dataset import load_questions, load_questions_content
from app.agents.evaluation.models import EvaluationConfig
from app.agents.evaluation.report import build_report
from app.agents.knowledge.agent import run_knowledge_agent
from app.config import CONF
from app.db import evaluation_case_result as case_db
from app.db import evaluation_run as run_db
from app.db import evaluation_task as task_db
from app.db.api import check_db_connected
from app.db.base import DB


def _now():
    return datetime.now(UTC)


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
    await run_db.update_(db, {"status": "running", "started_at": _now()}, id=run_id)
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
                task["config"].get("business_description"),
            )
        results, metrics = await EvaluationAgent(run_knowledge_agent).run(config, questions)
        report = build_report(config, results, metrics)
        async with db.transaction():
            for result in results:
                await case_db.insert_(db, run_id=run_id, **result.model_dump())
            await run_db.update_(
                db,
                {
                    "status": "completed",
                    "conclusion": metrics.conclusion,
                    "question_count": len(results),
                    "metrics": metrics.model_dump(mode="json"),
                    "report": report,
                    "finished_at": _now(),
                },
                id=run_id,
            )
    except Exception as exc:
        await run_db.update_(
            db,
            {
                "status": "failed",
                "report": {"error": str(exc)[:500]},
                "finished_at": _now(),
            },
            id=run_id,
        )
    return run_id


@check_db_connected
async def run_pending_once() -> bool:
    """领取并执行一个待运行评测，供常驻 Worker 调用。"""
    db = DB.get()
    pending = await run_db.list(db, status="pending")
    if not pending:
        return False
    await run_evaluation(int(pending[0]["id"]))
    return True


async def run_forever(stop_event: asyncio.Event) -> None:
    """持续消费自主评测运行，服务停止时优雅退出。"""
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
