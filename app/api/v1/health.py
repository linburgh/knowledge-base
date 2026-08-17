from fastapi import APIRouter

from app.db import base as db_base
from app.types.constants import PROJECT_NAME


router = APIRouter()


@router.get("")
async def health_check() -> dict[str, str | bool]:
    return {
        "service": PROJECT_NAME,
        "status": "ok",
        "database_connected": bool(db_base.DATABASE and db_base.DATABASE.is_connected),
    }
