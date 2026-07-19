import os
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.v1 import api_router
from app.config import CONF
from app.config import configure
from app.types import constants
from app.core.common.log import LOG, setup as log_setup
from app.db import setup as db_setup
from pathlib import Path


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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    LOG.warning(
        "request validation failed method={} path={} errors={}",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    LOG.exception(
        "unhandled exception method={} path={}",
        request.method,
        request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})
