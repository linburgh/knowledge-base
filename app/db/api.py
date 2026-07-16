from __future__ import annotations

from functools import wraps
from typing import Any

from app.types import Fn

from app.db.base import DB, inject_db


def check_db_connected(fn: Fn) -> Any:
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        await inject_db()
        db = DB.get()
        assert db is not None, "Database is not connected."
        return await fn(*args, **kwargs)

    return wrapper
