from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import auth, utils
from app.core.common.exception import BusiException
from app.core.services import evaluation as service
from app.schemas.evaluation import EvaluationRunRequest, EvaluationTaskRequest, OptimizationRequest

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


@router.get("/page")
async def page(
    current_user: auth.CurrentUser = current_user_dependency,
    page: int = 1,
    page_size: int = 20,
    name: str | None = None,
    kb_id: int | None = None,
    status: str | None = None,
    conclusion: str | None = None,
) -> Any:
    try:
        return await service.page(
            current_user,
            page=page,
            page_size=page_size,
            name=name,
            kb_id=kb_id,
            status=status,
            conclusion=conclusion,
        )
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.post("")
async def create(
    payload: EvaluationTaskRequest, current_user: auth.CurrentUser = current_user_dependency
) -> Any:
    try:
        return await service.create(payload, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.get("/{task_id}")
async def get(task_id: int, current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await service.get(task_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.put("/{task_id}")
async def update(
    task_id: int,
    payload: EvaluationTaskRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await service.update(task_id, payload, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.post("/{task_id}/runs")
async def create_run(
    task_id: int, _: EvaluationRunRequest, current_user: auth.CurrentUser = current_user_dependency
) -> Any:
    try:
        return await service.create_run(task_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.get("/{task_id}/runs")
async def runs(task_id: int, current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await service.runs(task_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.get("/{task_id}/runs/{run_id}")
async def run_detail(
    task_id: int, run_id: int, current_user: auth.CurrentUser = current_user_dependency
) -> Any:
    try:
        return await service.run_detail(task_id, run_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.get("/{task_id}/runs/{run_id}/cases")
async def cases(
    task_id: int,
    run_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> Any:
    try:
        return await service.cases(
            task_id,
            run_id,
            current_user,
            page=page,
            page_size=page_size,
            status=status,
        )
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.get("/{task_id}/runs/{run_id}/cases/{case_id}")
async def case_detail(
    task_id: int,
    run_id: int,
    case_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await service.case_detail(task_id, run_id, case_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.post("/{task_id}/runs/{run_id}/optimizations")
async def create_optimization(
    task_id: int,
    run_id: int,
    payload: OptimizationRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await service.create_optimization(task_id, run_id, payload, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.post("/{task_id}/runs/{run_id}/optimizations/{optimization_id}/save-draft")
async def save_optimization_draft(
    task_id: int,
    run_id: int,
    optimization_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await service.save_optimization_draft(task_id, run_id, optimization_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.post("/{task_id}/runs/{run_id}/optimizations/{optimization_id}/retest")
async def retest_optimization(
    task_id: int,
    run_id: int,
    optimization_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await service.retest_optimization(task_id, run_id, optimization_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.delete("/{task_id}")
async def remove(task_id: int, current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await service.remove(task_id, current_user)
    except BusiException as exc:
        utils.raise_http_exception(exc)
