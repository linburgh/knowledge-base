from fastapi import APIRouter

from app.db.base import get_database
from app.types.constants import PROJECT_NAME


router = APIRouter()


@router.get("")
async def health_check() -> dict[str, str | bool]:
    database = get_database()
    return {
        "service": PROJECT_NAME,
        "status": "ok",
        "database_connected": bool(database and database.is_connected),
    }
