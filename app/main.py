import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.config import CONF, configure
from app.core.common import audit as audit_context
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.core.common.log import setup as log_setup
from app.db import setup as db_setup
from app.types import constants
from workers import evaluation as evaluation_worker
from workers import indexing as indexing_worker

indexing_stop_event = asyncio.Event()
indexing_worker_task: asyncio.Task | None = None
evaluation_stop_event = asyncio.Event()
evaluation_worker_task: asyncio.Task | None = None


async def on_startup() -> None:
    global evaluation_worker_task, indexing_worker_task
    configure("app")
    log_setup(
        Path(CONF.default.log_dir).joinpath(CONF.default.log_file),
        debug=CONF.default.debug,
    )
    await db_setup()
    indexing_stop_event.clear()
    evaluation_stop_event.clear()
    indexing_worker_task = asyncio.create_task(
        indexing_worker.run_forever(indexing_stop_event),
        name="document-indexing-worker",
    )
    evaluation_worker_task = asyncio.create_task(
        evaluation_worker.run_forever(evaluation_stop_event),
        name="autonomous-evaluation-worker",
    )


async def on_shutdown() -> None:
    evaluation_stop_event.set()
    indexing_stop_event.set()
    if indexing_worker_task is not None:
        indexing_worker_task.cancel()
        await asyncio.gather(indexing_worker_task, return_exceptions=True)
    if evaluation_worker_task is not None:
        evaluation_worker_task.cancel()
        await asyncio.gather(evaluation_worker_task, return_exceptions=True)

app = None

environment = os.getenv("ENVIRONMENT", "development")

if environment == "production":
    app = FastAPI(
        title=constants.PROJECT_NAME,
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
        docs_url=None, 
        redoc_url=None,
        openapi_url=None)
else:
    app = FastAPI(
        title=constants.PROJECT_NAME,
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
    )

app.include_router(api_router, prefix=constants.API_PREFIX)


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
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(BusiException)
async def business_exception_handler(request: Request, exc: BusiException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    LOG.exception(
        "unhandled exception method={} path={}",
        request.method,
        request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})
