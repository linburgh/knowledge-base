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


async def on_startup() -> None:
    configure("app")
    log_setup(
        Path(CONF.default.log_dir).joinpath(CONF.default.log_file),
        debug=CONF.default.debug,
    )
    await db_setup()

app = None

environment = os.getenv("ENVIRONMENT", "development")

if environment == "production":
    app = FastAPI(
        title=constants.PROJECT_NAME,
        on_startup=[on_startup],
        docs_url=None, 
        redoc_url=None,
        openapi_url=None)
else:
    app = FastAPI(
        title=constants.PROJECT_NAME,
        on_startup=[on_startup]
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
