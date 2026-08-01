from typing import Any

from app.db import api as db_api
from app.db.models import EvaluationOptimization


async def insert_(db, **kwargs: Any):
    return await db_api.insert_(db, EvaluationOptimization, **kwargs)


async def get(db, **kwargs: Any):
    return await db_api.get(db, EvaluationOptimization, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any):
    return await db_api.update_(db, EvaluationOptimization, values, **kwargs)
