import os
from fastapi import FastAPI, Depends
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
