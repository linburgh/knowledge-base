# Copyright 2021 99cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from functools import wraps
from typing import Any

from sqlalchemy import and_, delete, insert, select, update

from app.types import Fn

from .base import DB, inject_db


def check_db_connected(fn: Fn) -> Any:
    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        await inject_db()
        db = DB.get()
        assert db is not None, "Database is not connected."
        return await fn(*args, **kwargs)

    return wrapper


def _build_conditions(table: Any, **kwargs: Any) -> list[Any]:
    conditions = []
    for key, value in kwargs.items():
        if value is None:
            continue
        conditions.append(getattr(table.c, key) == value)
    return conditions


async def insert_(db, table: Any, **kwargs: Any) -> Any:
    query = insert(table).values(**kwargs)
    return await db.execute(query)


async def update_(db, table: Any, values: dict[str, Any], **kwargs: Any) -> Any:
    conditions = _build_conditions(table, **kwargs)
    if not conditions:
        raise ValueError("Update conditions are required")

    query = update(table).where(and_(*conditions)).values(**values)
    return await db.execute(query)


async def delete_(db, table: Any, **kwargs: Any) -> Any:
    conditions = _build_conditions(table, **kwargs)
    if not conditions:
        raise ValueError("Delete conditions are required")

    query = delete(table).where(and_(*conditions))
    return await db.execute(query)


async def get(db, table: Any, **kwargs: Any) -> Any:
    conditions = _build_conditions(table, **kwargs)
    query = select(table)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.limit(1)

    row = await db.fetch_one(query)
    return dict(row) if row else None

