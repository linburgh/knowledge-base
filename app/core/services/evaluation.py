from __future__ import annotations

from typing import Any

from app.core.common import utils
from app.core.common import validation as common_validation
from app.core.common import form_limits
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import evaluation_case_result as case_db
from app.db import evaluation_optimization as optimization_db
from app.db import evaluation_run as run_db
from app.db import evaluation_task as task_db
from app.db import knowledge_base as knowledge_base_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.evaluation import EvaluationTaskRequest, OptimizationRequest

from .evaluation_access import require_super_admin


async def _resolve_execution_user(payload: EvaluationTaskRequest, current_user: CurrentUser) -> int:
    configured_user_id = payload.execution.get("user_id")
    if configured_user_id is None:
        return int(current_user.user_id)
    if isinstance(configured_user_id, bool) or not str(configured_user_id).isdigit():
        raise BusiException("CONFIG_INVALID: execution.user_id 必须是数据库用户数字 ID")
    execution_user_id = int(configured_user_id)
    user = await user_db.get(DB.get(), id=execution_user_id)
    if user is None or user.get("status") != "active":
        raise BusiException("CONFIG_INVALID: execution.user_id 对应的有效用户不存在")
    return execution_user_id


def _config(payload: EvaluationTaskRequest, execution_user_id: int) -> dict[str, Any]:
    return {
        "kb_id": payload.kb_id,
        "questions_source": payload.questions_source,
        "questions_file": payload.questions_file,
        "questions_content": payload.questions_content,
        "questions_instruction": payload.questions_instruction,
        "questions_count": payload.questions_count,
        "business_scope_source": payload.business_scope_source,
        "business_description": payload.business_description,
        "user_id": execution_user_id,
        "concurrency": payload.execution.get("concurrency", 3),
        "request_timeout_seconds": payload.execution.get("request_timeout_seconds", 120),
        "retry_count": payload.execution.get("retry_count", 0),
        "keep_conversation": payload.execution.get("keep_conversation", False),
        "gates": payload.gates,
    }


@check_db_connected
async def create(payload: EvaluationTaskRequest, current_user: CurrentUser) -> dict[str, Any]:
    await require_super_admin(current_user)
    _validate_text_fields(payload)
    db = DB.get()
    execution_user_id = await _resolve_execution_user(payload, current_user)
    config = _config(payload, execution_user_id)
    async with db.transaction():
        task_id = await task_db.insert_(
            db,
            name=payload.name,
            kb_id=payload.kb_id,
            config=config,
            status="active",
            created_by=current_user.user_id,
        )
        row = await task_db.get(db, id=task_id)
        await audit_service.record(
            db,
            action="create_evaluation_task",
            target_type="evaluation_task",
            target_id=task_id,
            summary={"name": payload.name, "kb_id": payload.kb_id},
        )
    return row


@check_db_connected
async def page(
    current_user: CurrentUser,
    *,
    page: int = 1,
    page_size: int = 20,
    name: str | None = None,
    kb_id: int | None = None,
    status: str | None = None,
    conclusion: str | None = None,
):
    await require_super_admin(current_user)
    if page < 1 or page_size < 1 or page_size > 100:
        raise BusiException("分页参数无效")
    db = DB.get()
    rows = await task_db.list(db, status="active", kb_id=kb_id)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        history = await run_db.list(db, task_id=row["id"])
        latest = max(history, key=lambda item: int(item["run_no"]), default=None)
        created_by_name = row["created_by"]
        try:
            creator = await user_db.get(db, id=int(row["created_by"]))
            if creator:
                created_by_name = creator.get("display_name") or creator.get("username")
        except (TypeError, ValueError):
            pass
        item = {
            **row,
            "created_by_name": created_by_name,
            "latest_run_id": latest.get("id") if latest else None,
            "latest_run_status": latest.get("status") if latest else "pending",
            "latest_conclusion": latest.get("conclusion") if latest else None,
            "latest_question_count": latest.get("question_count", 0) if latest else 0,
            "latest_run_created_at": latest.get("created_at") if latest else None,
        }
        if name and name.lower() not in str(item["name"]).lower():
            continue
        if status and item["latest_run_status"] != status:
            continue
        if conclusion and item["latest_conclusion"] != conclusion:
            continue
        enriched.append(item)
    start = (page - 1) * page_size
    return {
        "items": enriched[start : start + page_size],
        "total": len(enriched),
        "page": page,
        "page_size": page_size,
    }


@check_db_connected
async def get(task_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await require_super_admin(current_user)
    row = await task_db.get(DB.get(), id=task_id, status="active")
    if row is None:
        raise BusiException("评测任务不存在", status_code=404)
    return row


@check_db_connected
async def update(
    task_id: int, payload: EvaluationTaskRequest, current_user: CurrentUser
) -> dict[str, Any]:
    await require_super_admin(current_user)
    _validate_text_fields(payload)
    db = DB.get()
    execution_user_id = await _resolve_execution_user(payload, current_user)
    config = _config(payload, execution_user_id)
    async with db.transaction():
        task = await task_db.get(db, id=task_id, status="active")
        if task is None:
            raise BusiException("评测任务不存在", status_code=404)
        history = await run_db.list(db, task_id=task_id)
        if history:
            raise BusiException("已有运行记录的评测任务不可修改", status_code=409)
        await task_db.update_(
            db,
            {
                "name": payload.name,
                "kb_id": payload.kb_id,
                "config": config,
                "updated_at": utils.utc_now(),
            },
            id=task_id,
            status="active",
        )
        row = await task_db.get(db, id=task_id)
        await audit_service.record(
            db,
            action="update_evaluation_task",
            target_type="evaluation_task",
            target_id=task_id,
            summary={"name": payload.name, "kb_id": payload.kb_id},
        )
    return row


def _validate_text_fields(payload: EvaluationTaskRequest) -> None:
    common_validation.validate_text(
        payload.name, "name", max_length=form_limits.RESOURCE_NAME, required=True, forbid_path=True
    )
    common_validation.validate_text(
        payload.questions_file, "questions_file", max_length=form_limits.FILE_NAME, forbid_path=True
    )
    common_validation.validate_free_text(
        payload.questions_content, "questions_content", max_length=10 * 1024 * 1024
    )
    common_validation.validate_free_text(
        payload.questions_instruction, "questions_instruction", max_length=form_limits.EVALUATION_INSTRUCTION
    )
    common_validation.validate_free_text(
        payload.business_description, "business_description", max_length=form_limits.EVALUATION_SCOPE
    )
    for field, value in payload.execution.items():
        if isinstance(value, str):
            common_validation.validate_free_text(value, f"execution.{field}", max_length=255)


@check_db_connected
async def create_run(task_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await require_super_admin(current_user)
    db = DB.get()
    async with db.transaction():
        task = await task_db.get(db, id=task_id, status="active")
        if task is None:
            raise BusiException("评测任务不存在", status_code=404)
        active = await run_db.list(db, task_id=task_id, status="pending")
        active += await run_db.list(db, task_id=task_id, status="running")
        if active:
            raise BusiException("该任务已有运行中的评测", status_code=409)
        history = await run_db.list(db, task_id=task_id)
        run_no = len(history) + 1
        run_id = await run_db.insert_(
            db,
            task_id=task_id,
            run_no=run_no,
            status="pending",
            config_snapshot=task["config"],
            metrics={},
            report={},
        )
        row = await run_db.get(db, id=run_id)
        await audit_service.record(
            db,
            action="create_evaluation_run",
            target_type="evaluation_run",
            target_id=run_id,
            summary={"task_id": task_id},
        )
    return row


@check_db_connected
async def runs(task_id: int, current_user: CurrentUser) -> list[dict[str, Any]]:
    await require_super_admin(current_user)
    return await run_db.list(DB.get(), task_id=task_id)


@check_db_connected
async def run_detail(task_id: int, run_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await require_super_admin(current_user)
    row = await run_db.get(DB.get(), id=run_id, task_id=task_id)
    if row is None:
        raise BusiException("评测运行不存在", status_code=404)
    return row


@check_db_connected
async def cases(
    task_id: int,
    run_id: int,
    current_user: CurrentUser,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
):
    await run_detail(task_id, run_id, current_user)
    result = await case_db.page(
        DB.get(), page=page, page_size=page_size, run_id=run_id, status=status
    )
    return {"items": result.rows, "total": result.total, "page": page, "page_size": page_size}


@check_db_connected
async def remove(task_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await require_super_admin(current_user)
    db = DB.get()
    async with db.transaction():
        row = await task_db.get(db, id=task_id, status="active")
        if row is None:
            raise BusiException("评测任务不存在", status_code=404)
        await task_db.update_(db, {"status": "deleted", "updated_at": utils.utc_now()}, id=task_id)
        await audit_service.record(
            db,
            action="delete_evaluation_task",
            target_type="evaluation_task",
            target_id=task_id,
            summary={"task_id": task_id},
        )
    return {"id": task_id, "status": "deleted"}


@check_db_connected
async def case_detail(
    task_id: int, run_id: int, case_id: int, current_user: CurrentUser
) -> dict[str, Any]:
    await run_detail(task_id, run_id, current_user)
    row = await case_db.get(DB.get(), id=case_id, run_id=run_id)
    if row is None:
        raise BusiException("评测题目不存在", status_code=404)
    return row


@check_db_connected
async def create_optimization(
    task_id: int,
    run_id: int,
    payload: OptimizationRequest,
    current_user: CurrentUser,
) -> dict[str, Any]:
    run = await run_detail(task_id, run_id, current_user)
    db = DB.get()
    task = await task_db.get(db, id=task_id, status="active")
    if task is None:
        raise BusiException("评测任务不存在", status_code=404)
    knowledge_base = await knowledge_base_db.get(db, id=task["kb_id"], status="active")
    report = run.get("report") or {}
    failures = report.get("failures") or []
    first_failure = failures[0] if failures else {}
    case_no = first_failure.get("case_no")
    question = first_failure.get("question")
    failure_status = first_failure.get("status") or "异常"
    if case_no and question:
        suggestion = (
            f"第 {case_no} 题“{question}”触发 {failure_status}；"
            "建议补充相关操作文档并调整检索配置后复测。"
        )
    else:
        suggestion = "根据本次评测的失败、超时、降级和无引用样品生成候选优化方案。"

    raw_metrics = (run.get("metrics") or {}).get("metrics") or {}
    before_metrics = {
        name: metric.get("value")
        for name, metric in raw_metrics.items()
        if isinstance(metric, dict) and metric.get("value") is not None
    }
    current_chunk_size = (knowledge_base or {}).get("chunk_size") or 600
    current_top_k = (knowledge_base or {}).get("retrieval_top_k") or 5
    failure_hint = (
        f"补充{question}相关操作说明" if question else "补充失败问题相关操作说明"
    )
    candidate_config = payload.candidate_config or {
        "chunk_size": {
            "current": current_chunk_size,
            "suggested": max(200, current_chunk_size - 200),
        },
        "retrieval_top_k": {
            "current": current_top_k,
            "suggested": current_top_k + 3,
        },
        "document_processing": {
            "current": "保持不变",
            "suggested": failure_hint,
        },
    }
    async with db.transaction():
        optimization_id = await optimization_db.insert_(
            db,
            run_id=run_id,
            suggestion=suggestion,
            evidence={"metrics": run.get("metrics", {}), "failure": first_failure},
            candidate_config=candidate_config,
            status="suggested",
            before_metrics=before_metrics,
            requires_confirmation=True,
            created_by=current_user.user_id,
        )
        return await optimization_db.get(db, id=optimization_id)


@check_db_connected
async def save_optimization_draft(
    task_id: int,
    run_id: int,
    optimization_id: int,
    current_user: CurrentUser,
) -> dict[str, Any]:
    await run_detail(task_id, run_id, current_user)
    db = DB.get()
    async with db.transaction():
        optimization = await optimization_db.get(db, id=optimization_id, run_id=run_id)
        if optimization is None:
            raise BusiException("优化方案不存在", status_code=404)
        await optimization_db.update_(
            db, {"status": "draft_saved"}, id=optimization_id, run_id=run_id
        )
        return await optimization_db.get(db, id=optimization_id)


@check_db_connected
async def get_optimization(
    task_id: int,
    run_id: int,
    optimization_id: int,
    current_user: CurrentUser,
) -> dict[str, Any]:
    await run_detail(task_id, run_id, current_user)
    optimization = await optimization_db.get(DB.get(), id=optimization_id, run_id=run_id)
    if optimization is None:
        raise BusiException("优化方案不存在", status_code=404)
    return optimization


@check_db_connected
async def retest_optimization(
    task_id: int,
    run_id: int,
    optimization_id: int,
    current_user: CurrentUser,
) -> dict[str, Any]:
    await require_super_admin(current_user)
    source_run = await run_detail(task_id, run_id, current_user)
    db = DB.get()
    task = await task_db.get(db, id=task_id, status="active")
    if task is None:
        raise BusiException("评测任务不存在", status_code=404)
    async with db.transaction():
        optimization = await optimization_db.get(db, id=optimization_id, run_id=run_id)
        if optimization is None:
            raise BusiException("优化方案不存在", status_code=404)
        existing_runs = await run_db.list(db, task_id=task_id)
        next_run_no = max((int(item["run_no"]) for item in existing_runs), default=0) + 1
        retest_id = await run_db.insert_(
            db,
            task_id=task_id,
            run_no=next_run_no,
            status="pending",
            config_snapshot=task.get("config") or source_run.get("config_snapshot", {}),
            metrics={},
            report={
                "retest_of_run_id": run_id,
                "optimization_id": optimization_id,
                "candidate_config": optimization.get("candidate_config") or {},
            },
        )
        await optimization_db.update_(
            db,
            {"status": "retesting", "retest_run_id": retest_id},
            id=optimization_id,
            run_id=run_id,
        )
        return await run_db.get(db, id=retest_id)
