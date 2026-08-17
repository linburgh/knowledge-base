import asyncio
import os
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.config import CONF, configure
from app.core.common import audit as audit_context
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.core.common.log import setup as log_setup
from app.core.monitoring import emit_gather_event
from app.db import setup as db_setup
from app.types import constants
from app.workers import evaluation as evaluation_worker
from app.workers import indexing as indexing_worker
from app.workers.monitoring import aggregate as monitoring_aggregate
from app.workers.monitoring import collect as monitoring_collect
from app.workers.monitoring import notify as monitoring_notify

evaluation_stop_event = asyncio.Event()
monitoring_stop_event = asyncio.Event()
evaluation_worker_task: asyncio.Task | None = None
monitoring_worker_tasks: list[asyncio.Task] = []


async def on_startup() -> None:
    global evaluation_worker_task, monitoring_worker_tasks
    configure("app")
    log_setup(
        Path(CONF.default.log_dir).joinpath(CONF.default.log_file),
        debug=CONF.default.debug,
    )
    await db_setup()
    await indexing_worker.recover_stale_tasks()
    indexing_worker.start()
    evaluation_stop_event.clear()
    evaluation_worker_task = asyncio.create_task(
        evaluation_worker.run_forever(evaluation_stop_event),
        name="autonomous-evaluation-worker",
    )
    monitoring_stop_event.clear()
    monitoring_worker_tasks = [
        asyncio.create_task(
            monitoring_collect.run_forever(monitoring_stop_event), name="monitoring-collect-worker"
        ),
        asyncio.create_task(
            monitoring_aggregate.run_forever(monitoring_stop_event),
            name="monitoring-aggregate-worker",
        ),
        asyncio.create_task(
            monitoring_notify.run_forever(monitoring_stop_event), name="monitoring-notify-worker"
        ),
    ]


async def on_shutdown() -> None:
    monitoring_stop_event.set()
    evaluation_stop_event.set()
    indexing_worker.stop()
    if evaluation_worker_task is not None:
        evaluation_worker_task.cancel()
        await asyncio.gather(evaluation_worker_task, return_exceptions=True)
    for task in monitoring_worker_tasks:
        task.cancel()
    await asyncio.gather(*monitoring_worker_tasks, return_exceptions=True)


app = None

environment = os.getenv("ENVIRONMENT", "development")

if environment == "production":
    app = FastAPI(
        title=constants.PROJECT_NAME,
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
else:
    app = FastAPI(
        title=constants.PROJECT_NAME,
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
    )

app.include_router(api_router, prefix=constants.API_PREFIX)


@app.middleware("http")
async def monitoring_http_middleware(request: Request, call_next):
    excluded_paths = {"/api/v1/health", "/docs", "/openapi.json"}
    if request.url.path in excluded_paths:
        return await call_next(request)
    started_at = monotonic()
    trace_id = request.headers.get("X-Trace-ID") or common_utils.new_request_id()
    try:
        response = await call_next(request)
    except Exception as exc:
        await emit_gather_event(
            "api.http",
            "http_request_failed",
            method=request.method,
            path=request.url.path,
            status_code=500,
            request_id=request.headers.get("X-Request-ID"),
            trace_id=trace_id,
            duration_ms=int((monotonic() - started_at) * 1000),
            error=exc,
        )
        raise
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or request.url.path
    await emit_gather_event(
        "api.http",
        ("http_request_failed" if response.status_code >= 500 else "http_request_completed"),
        method=request.method,
        path=route_path,
        status_code=response.status_code,
        request_id=request.headers.get("X-Request-ID"),
        trace_id=trace_id,
        duration_ms=int((monotonic() - started_at) * 1000),
    )
    response.headers["X-Trace-ID"] = trace_id
    return response


@app.middleware("http")
async def audit_context_middleware(request: Request, call_next):
    try:
        request_id_header = CONF.default.request_id_header
    except AttributeError:
        request_id_header = "X-Request-ID"
    request_id = request.headers.get(request_id_header)
    token = audit_context.set_context(
        actor_id=audit_context.actor_from_request(request.headers.get("Authorization")),
        request_id=request_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    try:
        return await call_next(request)
    finally:
        audit_context.reset_context(token)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    LOG.warning(
        "request validation failed method={} path={} errors={}",
        request.method,
        request.url.path,
        exc.errors(),
    )
    if request.url.path.startswith("/api/v1/open/"):
        return JSONResponse(
            status_code=422,
            content={
                "request_id": audit_context.get_context().get("request_id")
                or common_utils.new_request_id(),
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败",
                "retryable": False,
                "detail": exc.errors(),
            },
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(BusiException)
async def business_exception_handler(request: Request, exc: BusiException):
    if request.url.path.startswith("/api/v1/open/"):
        code = (
            "RATE_LIMITED"
            if exc.status_code == 429
            else (
                "UNAUTHORIZED"
                if exc.status_code == 401
                else (
                    "RESOURCE_FORBIDDEN"
                    if exc.status_code == 403
                    else ("RESOURCE_NOT_FOUND" if exc.status_code == 404 else "BUSINESS_ERROR")
                )
            )
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "request_id": audit_context.get_context().get("request_id")
                or common_utils.new_request_id(),
                "code": code,
                "message": exc.message,
                "retryable": exc.status_code in {408, 429, 500, 502, 503, 504},
            },
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    LOG.exception(
        "unhandled exception method={} path={}",
        request.method,
        request.url.path,
    )
    if request.url.path.startswith("/api/v1/open/"):
        return JSONResponse(
            status_code=500,
            content={
                "request_id": audit_context.get_context().get("request_id")
                or common_utils.new_request_id(),
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "retryable": True,
            },
        )
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})
