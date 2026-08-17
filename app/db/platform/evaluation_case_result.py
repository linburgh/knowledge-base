from typing import Any

from app.db import api as db_api
from app.db.models import EvaluationCaseResult


async def insert_(db, **kwargs: Any):
    return await db_api.insert_(db, EvaluationCaseResult, **kwargs)


async def get(db, **kwargs: Any):
    return await db_api.get(db, EvaluationCaseResult, **kwargs)


async def list(db, **kwargs: Any):
    return await db_api.list(db, EvaluationCaseResult, **kwargs)


async def page(db, **kwargs: Any):
    return await db_api.page(db, EvaluationCaseResult, **kwargs)
