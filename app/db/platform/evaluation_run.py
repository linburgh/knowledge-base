from typing import Any

from app.db import api as db_api
from app.db.models import EvaluationRun


async def insert_(db, **kwargs: Any):
    return await db_api.insert_(db, EvaluationRun, **kwargs)


async def get(db, **kwargs: Any):
    return await db_api.get(db, EvaluationRun, **kwargs)


async def list(db, **kwargs: Any):
    return await db_api.list(db, EvaluationRun, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any):
    return await db_api.update_(db, EvaluationRun, values, **kwargs)
