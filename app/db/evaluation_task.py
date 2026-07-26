from typing import Any

from app.db import api as db_api
from app.db.models import EvaluationTask


async def insert_(db, **kwargs: Any):
    return await db_api.insert_(db, EvaluationTask, **kwargs)


async def get(db, **kwargs: Any):
    return await db_api.get(db, EvaluationTask, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any):
    return await db_api.update_(db, EvaluationTask, values, **kwargs)


async def page(db, **kwargs: Any):
    return await db_api.page(db, EvaluationTask, **kwargs)


async def list(db, **kwargs: Any):
    return await db_api.list(db, EvaluationTask, **kwargs)
