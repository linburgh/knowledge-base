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

from sqlalchemy import and_, delete, func, insert, select, update

from app.core.common.log_utils import trace
from app.types import Fn

from .base import DB, PageRecord, inject_db


def check_db_connected(fn: Fn) -> Any:
    """确保数据库连接可用，并为 Service 入口统一记录未处理异常。"""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        await inject_db()
        db = DB.get()
        assert db is not None, "Database is not connected."
        return await fn(*args, **kwargs)

    return trace(wrapper)


def _build_conditions(table: Any, **kwargs: Any) -> list[Any]:
    conditions = []
    for key, value in kwargs.items():
        if value is None:
            continue
        # 支持 status__ne 这类通用排除条件，供列表默认隐藏逻辑删除数据。
        if key.endswith("__ne"):
            conditions.append(getattr(table.c, key[:-4]) != value)
        else:
            conditions.append(getattr(table.c, key) == value)
    return conditions


async def insert_(db, table: Any, **kwargs: Any) -> Any:
    query = insert(table).values(**kwargs)
    return await db.execute(query)


async def batch_insert(db, table: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    query = insert(table)
    await db.execute_many(query, rows)


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


async def count(db, table: Any, **kwargs: Any) -> int:
    conditions = _build_conditions(table, **kwargs)
    query = select(func.count()).select_from(table)
    if conditions:
        query = query.where(and_(*conditions))

    return int(await db.fetch_val(query))


async def list(
    db,
    table: Any,
    order_by: list[Any] | None = None,
    limit: int | None = None,
    offset: int | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    conditions = _build_conditions(table, **kwargs)
    query = select(table)
    if conditions:
        query = query.where(and_(*conditions))
    if order_by:
        query = query.order_by(*order_by)
    if limit is not None:
        query = query.limit(limit)
    if offset is not None:
        query = query.offset(offset)

    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def page(
    db,
    table: Any,
    page: int = 1,
    page_size: int = 20,
    order_by: list[Any] | None = None,
    **kwargs: Any,
) -> PageRecord:
    record = PageRecord(rows=[], total=0, page=page, page_size=page_size)
    record.total = await count(db, table, **kwargs)
    record.rows = await list(
        db,
        table,
        order_by=order_by,
        limit=page_size,
        offset=(page - 1) * page_size,
        **kwargs,
    )
    record.page = page
    record.page_size = page_size
    return record
    return record
